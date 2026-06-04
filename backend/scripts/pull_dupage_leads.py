"""Bulk DuPage County absentee-owner lead ingestion script.

Pulls all residential absentee-owner records from the DuPage County
ParcelsWithRealEstateCC FeatureServer and inserts or updates them in
the leads table using PostgreSQL INSERT ... ON CONFLICT (county_assessor_pin)
DO UPDATE for high-throughput upsert without per-record table scans.

Usage
-----
From the backend/ directory:

    python scripts/pull_dupage_leads.py --owner-user-id <user_id>
    python scripts/pull_dupage_leads.py --owner-user-id <user_id> --limit 1000
    python scripts/pull_dupage_leads.py --owner-user-id <user_id> --dry-run

Options
-------
--owner-user-id  Platform user ID that will own the created leads (required)
--limit          Max records to pull (default: all)
--batch-size     Records per API page (default: 500, max 2000)
--dry-run        Fetch records and print stats without writing to DB
"""

import argparse
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

import requests

# Ensure backend/ is on sys.path before any app imports
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# Load .env before anything Flask-related
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

# Ensure SECRET_KEY won't block startup
if not os.environ.get('SECRET_KEY') or os.environ['SECRET_KEY'] == 'dev-secret-key':
    os.environ['SECRET_KEY'] = 'dupage-bulk-pull-local-key-not-for-production'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger('pull_dupage_leads')

# ---------------------------------------------------------------------------
# DuPage GIS FeatureServer
# ---------------------------------------------------------------------------
FEATURE_SERVER = (
    "https://gis.dupageco.org/arcgis/rest/services/"
    "DuPage_County_IL/ParcelsWithRealEstateCC/FeatureServer/0/query"
)
OUT_FIELDS = "PIN,PROPNAME,PROPADDRL1,PROPADDRL2,BILLADDRL1,BILLADDRL2,REA017_PROP_CLASS,PARCEL_STATUS"

# Residential absentee owners: mailing address ≠ property address
ABSENTEE_WHERE = (
    "REA017_PROP_CLASS = 'R' "
    "AND PARCEL_STATUS = 'Approved' "
    "AND BILLADDRL1 <> PROPADDRL1"
)


def _get_count(where: str) -> int:
    for attempt in range(4):
        try:
            r = requests.get(FEATURE_SERVER,
                             params={"where": where, "returnCountOnly": "true", "f": "json"},
                             timeout=30)
            r.raise_for_status()
            return r.json().get("count", 0)
        except Exception as e:
            wait = 20 * (attempt + 1)
            logger.warning("Count query attempt %d failed: %s — waiting %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError("Failed to get record count after 4 attempts")


def _fetch_page(where: str, offset: int, batch_size: int) -> list[dict]:
    params = {
        "where": where,
        "outFields": OUT_FIELDS,
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": batch_size,
        "orderByFields": "OBJECTID",
        "f": "json",
    }
    for attempt in range(3):
        try:
            r = requests.get(FEATURE_SERVER, params=params, timeout=45)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"ArcGIS error: {data['error']}")
            return data.get("features", [])
        except Exception as e:
            if attempt < 2:
                wait = 15 * (attempt + 1)
                logger.warning("Fetch attempt %d failed at offset %d: %s — waiting %ds",
                               attempt + 1, offset, e, wait)
                time.sleep(wait)
            else:
                raise


def _parse_city_state_zip(line2: Optional[str]):
    if not line2:
        return None, None, None
    parts = line2.strip().split()
    if len(parts) >= 3:
        return ' '.join(parts[:-2]) or None, parts[-2] or None, parts[-1] or None
    elif len(parts) == 2:
        return parts[0], parts[1], None
    return line2.strip() or None, None, None


def _parse_owner(propname: Optional[str]):
    if not propname:
        return None, None
    name = propname.strip()
    if not name:
        return None, None
    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        return (parts[1] if len(parts) > 1 else None), parts[0]
    parts = name.split()
    if len(parts) == 1:
        return None, parts[0]
    return ' '.join(parts[:-1]), parts[-1]


def _feature_to_row(attrs: dict, owner_user_id: str) -> Optional[dict]:
    """Convert FeatureServer attributes to a DB row dict.  Returns None to skip."""
    prop_street = (attrs.get("PROPADDRL1") or "").strip() or None
    if not prop_street:
        return None

    first, last = _parse_owner(attrs.get("PROPNAME"))
    prop_city, prop_state, prop_zip = _parse_city_state_zip(attrs.get("PROPADDRL2"))
    mail_city, mail_state, mail_zip = _parse_city_state_zip(attrs.get("BILLADDRL2"))

    return {
        "county_assessor_pin": (attrs.get("PIN") or "").strip() or None,
        "owner_first_name": first,
        "owner_last_name": last,
        "property_street": prop_street,
        "property_city": prop_city,
        "property_state": prop_state or "IL",
        "property_zip": prop_zip,
        "mailing_address": (attrs.get("BILLADDRL1") or "").strip() or None,
        "mailing_city": mail_city,
        "mailing_state": mail_state,
        "mailing_zip": mail_zip,
        "source_type": "absentee_owner",
        "data_source": "dupage_gis",
        "lead_category": "residential",
        "owner_user_id": owner_user_id,
        "needs_skip_trace": True,
    }


def _bulk_upsert(rows: list[dict], conn) -> tuple[int, int]:
    """Insert new leads or update existing ones, matched by county_assessor_pin.

    Uses a SELECT-then-INSERT/UPDATE approach — fast because each lookup
    is a targeted index scan on county_assessor_pin, not a full table scan.
    Rows without a PIN are always inserted as new leads.

    Returns (upserted_count, skipped_count).
    """
    from sqlalchemy import text
    from datetime import datetime

    now = datetime.utcnow()
    upserted = 0
    skipped = 0

    for row in rows:
        pin = row.get("county_assessor_pin")
        sp = conn.begin_nested()  # savepoint — lets us rollback just this row on failure
        try:
            if pin:
                existing = conn.execute(
                    text("SELECT id FROM leads WHERE county_assessor_pin = :pin"),
                    {"pin": pin}
                ).fetchone()

                if existing:
                    conn.execute(text("""
                        UPDATE leads SET
                            owner_first_name  = COALESCE(owner_first_name,  :owner_first_name),
                            owner_last_name   = COALESCE(owner_last_name,   :owner_last_name),
                            property_street   = COALESCE(property_street,   :property_street),
                            property_city     = COALESCE(property_city,     :property_city),
                            property_state    = COALESCE(property_state,    :property_state),
                            property_zip      = COALESCE(property_zip,      :property_zip),
                            mailing_address   = COALESCE(mailing_address,   :mailing_address),
                            mailing_city      = COALESCE(mailing_city,      :mailing_city),
                            mailing_state     = COALESCE(mailing_state,     :mailing_state),
                            mailing_zip       = COALESCE(mailing_zip,       :mailing_zip),
                            source_type       = CASE WHEN source_type IS NULL
                                                THEN :source_type ELSE source_type END,
                            owner_user_id     = COALESCE(owner_user_id,     :owner_user_id),
                            updated_at        = :now
                        WHERE county_assessor_pin = :county_assessor_pin
                    """), {**row, "now": now})
                    sp.commit()
                    upserted += 1
                    continue

            conn.execute(text("""
                INSERT INTO leads (
                    county_assessor_pin, owner_first_name, owner_last_name,
                    property_street, property_city, property_state, property_zip,
                    mailing_address, mailing_city, mailing_state, mailing_zip,
                    source_type, data_source, lead_category, owner_user_id,
                    needs_skip_trace, lead_score, created_at, updated_at
                ) VALUES (
                    :county_assessor_pin, :owner_first_name, :owner_last_name,
                    :property_street, :property_city, :property_state, :property_zip,
                    :mailing_address, :mailing_city, :mailing_state, :mailing_zip,
                    :source_type, :data_source, :lead_category, :owner_user_id,
                    :needs_skip_trace, 0, :now, :now
                )
            """), {**row, "now": now})
            sp.commit()
            upserted += 1
        except Exception:
            sp.rollback()  # rollback just this row, connection stays healthy
            logger.warning("Failed to upsert row PIN=%s: %s", pin, traceback.format_exc())
            skipped += 1

    return upserted, skipped


def run_pull(owner_user_id: str, limit: Optional[int],
             batch_size: int, dry_run: bool) -> None:

    total_available = _get_count(ABSENTEE_WHERE)
    logger.info("DuPage County absentee owner leads available: %s", f"{total_available:,}")

    total = min(total_available, limit) if limit else total_available
    logger.info("Will pull: %s records", f"{total:,}")

    if dry_run:
        logger.info("DRY RUN — not writing to database. Fetching first batch to verify fields...")
        sample = _fetch_page(ABSENTEE_WHERE, 0, min(5, batch_size))
        for feat in sample:
            row = _feature_to_row(feat.get("attributes", {}), owner_user_id)
            logger.info("Sample: %s", row)
        logger.info("Dry run complete. %s records would be ingested.", f"{total:,}")
        return

    # Direct DB connection — bypasses the slow dedup engine for bulk loads
    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/real_estate_analysis'
    )

    import sqlalchemy as sa
    engine = sa.create_engine(db_url, pool_pre_ping=True)

    offset = 0
    total_upserted = 0
    total_skipped = 0
    batch_num = 0
    start_time = time.time()

    with engine.connect() as conn:
        while offset < total:
            fetch_count = min(batch_size, total - offset)
            logger.info(
                "Batch %d: fetching records %d–%d of %s...",
                batch_num + 1, offset + 1, offset + fetch_count, f"{total:,}"
            )

            try:
                features = _fetch_page(ABSENTEE_WHERE, offset, fetch_count)
            except Exception as e:
                logger.error("Failed to fetch batch at offset %d: %s — skipping", offset, e)
                offset += fetch_count
                continue

            if not features:
                logger.info("Empty batch at offset %d — done.", offset)
                break

            rows = []
            for feat in features:
                row = _feature_to_row(feat.get("attributes", {}), owner_user_id)
                if row:
                    rows.append(row)
                else:
                    total_skipped += 1

            if rows:
                try:
                    upserted, skipped = _bulk_upsert(rows, conn)
                    conn.commit()
                    total_upserted += upserted
                    total_skipped += skipped
                except Exception as e:
                    logger.error("Upsert failed for batch %d: %s", batch_num + 1, e)

            batch_num += 1
            offset += len(features)
            elapsed = time.time() - start_time
            rate = total_upserted / elapsed if elapsed > 0 else 0
            eta_s = (total - offset) / rate if rate > 0 else 0
            eta_min = eta_s / 60

            logger.info(
                "Batch %d done: %d rows | Total: %s upserted | %.1f rows/sec | ETA: %.1f min",
                batch_num, len(rows), f"{total_upserted:,}", rate, eta_min
            )

            # Brief pause to be polite to the API
            time.sleep(0.3)

    elapsed = time.time() - start_time
    logger.info(
        "=== Pull complete in %.1f min: %s leads upserted, %s skipped ===",
        elapsed / 60, f"{total_upserted:,}", f"{total_skipped:,}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-pull DuPage County absentee-owner leads from the GIS FeatureServer"
    )
    parser.add_argument(
        "--owner-user-id",
        required=True,
        help="Platform user ID that will own the created leads",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to pull (default: all ~70,589)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Records per API page (default 500; max 2000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch records and print stats without writing to DB",
    )
    args = parser.parse_args()

    if args.batch_size > 2000:
        parser.error("--batch-size cannot exceed 2000 (ArcGIS server limit)")

    logger.info(
        "Starting DuPage absentee owner pull — owner=%s limit=%s dry_run=%s",
        args.owner_user_id, args.limit or "all", args.dry_run
    )

    run_pull(
        owner_user_id=args.owner_user_id,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
