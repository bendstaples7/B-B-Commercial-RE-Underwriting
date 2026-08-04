"""Enrich DuPage leads with acquisition dates from the Illinois MyDec PTAX-203 API.

Uses the Illinois Open Data Portal (data.illinois.gov) Socrata API — no
authentication or manual download required. Updated weekly by IDOR.

What this does:
  1. Pulls all PTAX-203 deed transfer records for DuPage County from 2013–present.
  2. Finds the MOST RECENT deed date per PIN (= current owner's acquisition date).
  3. Updates leads.acquisition_date where:
       - The lead has a county_assessor_pin matching a PTAX record
       - The lead's acquisition_date is currently NULL
  4. Flags leads owned 15+ years as also having source_type_eligible for
     long_owned scoring signal (scored higher in years_owned dimension).
  5. Rescores all updated leads.

Note: PTAX-203 only covers 2013–present. Leads whose most recent deed
predates 2013 will still have acquisition_date=NULL after this enrichment,
but they are likely the longest-owned (best leads).

Usage:
    python scripts/enrich_dupage_acquisition_dates.py
    python scripts/enrich_dupage_acquisition_dates.py --dry-run
    python scripts/enrich_dupage_acquisition_dates.py --limit 1000
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

_env_file = _backend_dir / '.env'
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

if not os.environ.get('SECRET_KEY') or os.environ['SECRET_KEY'] == 'dev-secret-key':
    os.environ['SECRET_KEY'] = 'enrich-acq-dates-local-key'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('enrich_acq_dates')

# ---------------------------------------------------------------------------
# PTAX-203 Socrata API (shared Illinois MyDec helper)
# ---------------------------------------------------------------------------
from app.services.helpers.illinois_mydec import (  # noqa: E402
    fetch_county_pin_to_date_map,
    normalize_mydec_pin,
)

PAGE_SIZE = 5000


def _normalize_pin(pin: str) -> str:
    """Normalize PIN to match leads.county_assessor_pin (DuPage: 10 digits)."""
    return normalize_mydec_pin(pin, keep_digits=10)


def fetch_all_dupage_transfers(limit: Optional[int] = None) -> dict[str, date]:
    """Fetch all DuPage transfer records and return a dict of PIN → most recent deed date."""
    logger.info("Fetching DuPage transfer records from Illinois MyDec API...")
    pin_to_date = fetch_county_pin_to_date_map(
        'DuPage',
        pin_digits=10,
        limit=limit,
        page_size=PAGE_SIZE,
    )
    logger.info(
        "Fetch complete: %s unique DuPage PINs with deed dates",
        f"{len(pin_to_date):,}",
    )
    return pin_to_date


def enrich_leads(pin_to_date: dict[str, date], dry_run: bool) -> dict:
    """Update leads.acquisition_date for leads whose PIN is in the transfer data."""
    import sqlalchemy as sa

    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required — "
            "set it in .env or the shell environment before running this script"
        )
    engine = sa.create_engine(db_url, pool_pre_ping=True)

    stats = {'updated': 0, 'already_set': 0, 'no_pin_match': 0}

    with engine.connect() as conn:
        # Get all leads with a PIN that have no acquisition_date
        rows = conn.execute(sa.text("""
            SELECT id, county_assessor_pin, acquisition_date
            FROM leads
            WHERE county_assessor_pin IS NOT NULL
              AND source_type = 'absentee_owner'
        """)).fetchall()

        logger.info("Leads with PIN to check: %s", f"{len(rows):,}")

        updated_ids = []
        update_tuples = []  # (lead_id, deed_date)
        for row in rows:
            lead_id = row[0]
            pin = (row[1] or '').strip()
            existing_date = row[2]

            if existing_date is not None:
                stats['already_set'] += 1
                continue

            deed_date = pin_to_date.get(pin)
            if deed_date is None:
                stats['no_pin_match'] += 1
                continue

            update_tuples.append((lead_id, deed_date))
            stats['updated'] += 1

        if update_tuples and not dry_run:
            # Bulk UPDATE using executemany with bound parameters
            conn.execute(
                sa.text("""
                    UPDATE leads
                    SET acquisition_date = :acq_date,
                        updated_at = NOW()
                    WHERE id = :lead_id
                """),
                [{"lead_id": str(lid), "acq_date": d} for lid, d in update_tuples]
            )
            updated_ids.extend(lead_id for lead_id, _ in update_tuples)

        if not dry_run:
            conn.commit()

    logger.info(
        "Enrichment complete: %s updated, %s already set, %s no PIN match",
        f"{stats['updated']:,}", f"{stats['already_set']:,}", f"{stats['no_pin_match']:,}"
    )
    return stats


def rescore_enriched_leads(dry_run: bool) -> None:
    """Rescore all absentee_owner leads that now have an acquisition_date."""
    if dry_run:
        logger.info("DRY RUN — skipping rescore")
        return

    from app import create_app
    app = create_app('development')

    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.deterministic_scoring_engine import DeterministicScoringEngine

        engine = DeterministicScoringEngine()
        leads = (
            db.session.query(Property)
            .filter(
                Property.source_type == 'absentee_owner',
                Property.acquisition_date.isnot(None),
            )
            .all()
        )
        logger.info("Rescoring %s leads with acquisition_date...", f"{len(leads):,}")
        scored = 0
        for lead in leads:
            try:
                engine.recalculate_lead_score(lead)
                scored += 1
            except Exception as e:
                logger.error("Score failed for lead %s: %s", lead.id, e)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Commit failed during rescore: %s — rolled back", e)
            raise
        logger.info("Rescore complete: %s leads rescored", f"{scored:,}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich DuPage leads with acquisition dates from Illinois MyDec PTAX-203 API"
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Fetch data and show stats without writing to DB')
    parser.add_argument('--limit', type=int, default=None,
                        help='Max PTAX records to fetch (default: all)')
    parser.add_argument('--skip-rescore', action='store_true',
                        help='Skip rescoring after enrichment')
    args = parser.parse_args()

    logger.info("Starting DuPage acquisition date enrichment — dry_run=%s", args.dry_run)

    # Step 1: Fetch all DuPage deed transfer records from PTAX API
    pin_to_date = fetch_all_dupage_transfers(limit=args.limit)

    if not pin_to_date:
        logger.error("No records fetched — aborting")
        return

    # Step 2: Update leads
    stats = enrich_leads(pin_to_date, dry_run=args.dry_run)

    # Step 3: Rescore enriched leads
    if not args.skip_rescore and stats['updated'] > 0:
        rescore_enriched_leads(dry_run=args.dry_run)

    logger.info("Done.")


if __name__ == '__main__':
    main()
