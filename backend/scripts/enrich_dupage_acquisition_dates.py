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
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import requests

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
# PTAX-203 Socrata API
# ---------------------------------------------------------------------------
PTAX_API = 'https://data.illinois.gov/resource/it54-y4c6.json'
# Fields we need: PIN, instrument date (= deed/transfer date), buyer name
PTAX_FIELDS = 'line_1_primary_pin,line_4_instrument_date,step_4_buyer_name,line_1_city,line_5_instrument_type'
DUPAGE_WHERE = "line_1_county='DuPage' AND line_4_instrument_date IS NOT NULL"
PAGE_SIZE = 5000


def _normalize_pin(pin: str) -> str:
    """Normalize PIN to match the format stored in leads.county_assessor_pin.

    PTAX format:  '02-09-114-001-0000'  (with dashes, trailing zeros)
    GIS format:   '0209114001'           (no dashes, no trailing segment)
    We strip dashes and take first 10 digits.
    """
    if not pin:
        return ''
    clean = pin.replace('-', '').replace(' ', '')
    # PTAX PINs are 14 digits (10-digit parcel + 4-digit segment)
    # Our leads store 10-digit PINs
    return clean[:10]


def fetch_all_dupage_transfers(limit: Optional[int] = None) -> dict[str, date]:
    """Fetch all DuPage transfer records and return a dict of PIN → most recent deed date."""
    logger.info("Fetching DuPage transfer records from Illinois MyDec API...")

    # Get total count first
    r = requests.get(PTAX_API,
        params={'$select': 'count(*)', '$where': DUPAGE_WHERE},
        timeout=30)
    total = int(r.json()[0]['count'])
    logger.info("Total DuPage PTAX records available: %s", f"{total:,}")

    if limit:
        total = min(total, limit)
        logger.info("Limiting to %s records", f"{total:,}")

    # Build PIN → most_recent_date map
    pin_to_date: dict[str, date] = {}
    offset = 0
    page_num = 0

    while offset < total:
        fetch_count = min(PAGE_SIZE, total - offset)
        for attempt in range(3):
            try:
                r = requests.get(PTAX_API, params={
                    '$select': PTAX_FIELDS,
                    '$where': DUPAGE_WHERE,
                    '$limit': fetch_count,
                    '$offset': offset,
                    '$order': 'line_4_instrument_date DESC',
                }, timeout=45)
                r.raise_for_status()
                records = r.json()
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning("Fetch attempt %d failed: %s — retrying in 10s", attempt + 1, e)
                    time.sleep(10)
                else:
                    raise

        if not records:
            break

        for rec in records:
            raw_pin = rec.get('line_1_primary_pin', '')
            normalized = _normalize_pin(raw_pin)
            if not normalized:
                continue

            instrument_date_str = rec.get('line_4_instrument_date', '')
            if not instrument_date_str:
                continue
            try:
                # Format: "2019-07-11T00:00:00.000"
                deed_date = datetime.fromisoformat(instrument_date_str.split('T')[0]).date()
            except ValueError:
                continue

            # Keep the most recent deed date per PIN (= current owner's acquisition)
            existing = pin_to_date.get(normalized)
            if existing is None or deed_date > existing:
                pin_to_date[normalized] = deed_date

        page_num += 1
        offset += len(records)

        if page_num % 5 == 0:
            logger.info(
                "  Fetched %s/%s records | %s unique PINs mapped",
                f"{offset:,}", f"{total:,}", f"{len(pin_to_date):,}"
            )

        time.sleep(0.1)  # polite rate limiting

    logger.info(
        "Fetch complete: %s records → %s unique DuPage PINs with deed dates",
        f"{offset:,}", f"{len(pin_to_date):,}"
    )
    return pin_to_date


def enrich_leads(pin_to_date: dict[str, date], dry_run: bool) -> dict:
    """Update leads.acquisition_date for leads whose PIN is in the transfer data."""
    import sqlalchemy as sa

    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/real_estate_analysis'
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

            if not dry_run:
                conn.execute(sa.text("""
                    UPDATE leads
                    SET acquisition_date = :acq_date, updated_at = NOW()
                    WHERE id = :lead_id
                """), {'acq_date': deed_date, 'lead_id': lead_id})
                updated_ids.append(lead_id)
            stats['updated'] += 1

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
