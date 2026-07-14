"""One-time script to merge duplicate Lead records.

Modes:
  unit (default) — bare building vs unit suffix (e.g. "2553 N Drake" vs "2553 N Drake 1")
  normalized     — same owner + normalized street variants (e.g. "Schiller" vs "Schiller St")
  pin            — same owner + normalized county assessor PIN (dash format variants)

Run from the backend/ directory:
    python scripts/merge_duplicate_leads.py [--mode unit|normalized] [--dry-run]
"""
import re
import sys
import argparse
import logging
import os
from collections import defaultdict

# Allow imports from backend/app when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from app.services.lead_dedup_service import COPYABLE_FIELDS  # noqa: E402
from app.services.lead_merge_utils import (  # noqa: E402
    cluster_leads_by_normalized_street,
    cluster_same_building_by_owner_name,
    dedup_street_key,
    merge_mailer_history,
    owner_group_key,
    pick_merge_winner,
)
from app.services.plugins.pin_utils import normalize_pin_for_socrata  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

UNIT_RE = re.compile(
    r'\s+(apt|apartment|unit|ste|suite|#|fl|floor|no\.?)\s*\S+$'
    r'|\s+\d+[a-z]?$',
    re.IGNORECASE,
)


def strip_unit(street: str) -> str:
    if not street:
        return street
    return UNIT_RE.sub('', street.strip()).strip()


def has_unit(street: str) -> bool:
    """Return True if the street address contains a unit designator."""
    if not street:
        return False
    return strip_unit(street).lower() != street.strip().lower()


# FK tables that reference leads.id — confirmed via information_schema query
# Format: (table_name, column_name)
FK_TABLES = [
    ('lead_audit_trail',            'lead_id'),
    ('lead_tasks',                  'lead_id'),
    ('lead_timeline_entries',       'lead_id'),
    ('lead_scores',                 'lead_id'),
    ('enrichment_records',          'lead_id'),
    ('hubspot_signals',             'lead_id'),
    ('lead_deal_links',             'lead_id'),
    ('marketing_list_members',      'lead_id'),
    ('property_contacts',           'property_id'),
    ('property_organization_links', 'property_id'),
    ('owner_organization_links',    'owner_id'),
    ('tasks',                       'lead_id'),
]


def _fetch_confirmed_hubspot_lead_ids(cur) -> set[int]:
    cur.execute("""
        SELECT DISTINCT internal_record_id
        FROM hubspot_matches
        WHERE internal_record_type = 'lead'
          AND status = 'confirmed'
          AND internal_record_id IS NOT NULL
    """)
    return {int(r['internal_record_id']) for r in cur.fetchall()}


def _repoint_hubspot_matches(cur, winner_id: int, loser_id: int) -> None:
    """Move hubspot_matches from loser to winner, resolving unique conflicts."""
    import psycopg2

    cur.execute("""
        SELECT id, hubspot_record_type, hubspot_id
        FROM hubspot_matches
        WHERE internal_record_type = 'lead' AND internal_record_id = %s
    """, (loser_id,))
    loser_matches = cur.fetchall()

    for hm in loser_matches:
        cur.execute("""
            SELECT id FROM hubspot_matches
            WHERE hubspot_record_type = %s AND hubspot_id = %s
              AND internal_record_id = %s
        """, (hm['hubspot_record_type'], hm['hubspot_id'], winner_id))
        if cur.fetchone():
            cur.execute("DELETE FROM hubspot_matches WHERE id = %s", (hm['id'],))
            logger.debug(
                "  hubspot_matches id=%d: winner already linked, deleted loser row",
                hm['id'],
            )
        else:
            try:
                cur.execute("SAVEPOINT sp_hs")
                cur.execute(
                    "UPDATE hubspot_matches SET internal_record_id = %s WHERE id = %s",
                    (winner_id, hm['id']),
                )
                cur.execute("RELEASE SAVEPOINT sp_hs")
            except psycopg2.errors.UniqueViolation:
                cur.execute("ROLLBACK TO SAVEPOINT sp_hs")
                cur.execute("RELEASE SAVEPOINT sp_hs")
                cur.execute("DELETE FROM hubspot_matches WHERE id = %s", (hm['id'],))


def _merge_loser_into_winner(cur, winner: dict, loser: dict) -> None:
    """Re-point FKs, copy fields, repoint hubspot_matches, delete loser."""
    import psycopg2

    loser_id = loser['id']
    winner_id = winner['id']

    for table, col in FK_TABLES:
        cur.execute(f"SELECT id FROM {table} WHERE {col} = %s", (loser_id,))
        loser_rows = [r['id'] for r in cur.fetchall()]

        for row_id in loser_rows:
            try:
                cur.execute("SAVEPOINT sp_fk")
                cur.execute(
                    f"UPDATE {table} SET {col} = %s WHERE id = %s",
                    (winner_id, row_id),
                )
                cur.execute("RELEASE SAVEPOINT sp_fk")
            except psycopg2.errors.UniqueViolation:
                cur.execute("ROLLBACK TO SAVEPOINT sp_fk")
                cur.execute("RELEASE SAVEPOINT sp_fk")
                cur.execute(f"DELETE FROM {table} WHERE id = %s", (row_id,))
                logger.debug(
                    "  %s id=%d: unique conflict, deleted loser row",
                    table, row_id,
                )
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_fk")
                cur.execute("RELEASE SAVEPOINT sp_fk")
                raise

    _repoint_hubspot_matches(cur, winner_id, loser_id)

    cur.execute("SELECT * FROM leads WHERE id = %s", (winner_id,))
    winner_row = cur.fetchone()
    cur.execute("SELECT * FROM leads WHERE id = %s", (loser_id,))
    loser_row = cur.fetchone()

    if winner_row and loser_row:
        from psycopg2.extras import Json

        updates = {}
        for field in COPYABLE_FIELDS:
            if field in winner_row and field in loser_row:
                w_val = winner_row[field]
                l_val = loser_row[field]
                if field == 'mailer_history':
                    merged = merge_mailer_history(w_val, l_val)
                    if merged is not None and merged != w_val:
                        updates[field] = Json(merged)
                elif field == 'lead_score':
                    # Single writer — refresh_lead_scoring after commit.
                    continue
                elif (w_val is None or w_val == '') and l_val not in (None, ''):
                    updates[field] = l_val

        if updates:
            set_clause = ', '.join(f'"{k}" = %s' for k in updates)
            cur.execute(
                f"UPDATE leads SET {set_clause} WHERE id = %s",
                list(updates.values()) + [winner_id],
            )
            logger.debug("  Copied %d field(s) from loser to winner", len(updates))

    logger.info("  Deleting loser id=%d '%s'", loser_id, loser.get('property_street'))
    cur.execute("DELETE FROM leads WHERE id = %s", (loser_id,))


def _find_unit_merge_groups(rows: list[dict]) -> list[tuple]:
    groups: dict = {}
    for row in rows:
        key = (
            (row['owner_first_name'] or '').strip().lower(),
            (row['owner_last_name'] or '').strip().lower(),
            strip_unit(row['property_street'] or '').strip().lower(),
            row['owner_user_id'],
        )
        groups.setdefault(key, []).append(dict(row))

    merge_groups = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        bare = [m for m in members if not has_unit(m['property_street'])]
        with_unit = [m for m in members if has_unit(m['property_street'])]
        if bare and with_unit:
            merge_groups.append((key, bare, with_unit))
    return merge_groups


def _find_normalized_merge_groups(rows: list[dict]) -> list[list[dict]]:
    owner_buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = owner_group_key(
            row.get('owner_first_name'),
            row.get('owner_last_name'),
            row.get('property_street'),
            row.get('owner_user_id'),
        )
        owner_buckets[key].append(dict(row))

    merge_groups: list[list[dict]] = []
    for members in owner_buckets.values():
        merge_groups.extend(cluster_leads_by_normalized_street(members))
    return merge_groups


def _find_dedup_merge_groups(rows: list[dict]) -> list[list[dict]]:
    """Group by owner + building-level dedup_street_key (matches DB unique index)."""
    return cluster_same_building_by_owner_name(
        [dict(row) for row in rows],
        owner_user_id_of=lambda r: r.get('owner_user_id'),
        street_of=lambda r: r.get('property_street'),
        first_of=lambda r: r.get('owner_first_name'),
        last_of=lambda r: r.get('owner_last_name'),
    )


def _find_pin_merge_groups(rows: list[dict]) -> list[list[dict]]:
    """Group leads with the same normalized county assessor PIN."""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        pin = (row.get('county_assessor_pin') or '').strip()
        if not pin:
            continue
        pin_digits = normalize_pin_for_socrata(pin)
        if not pin_digits or len(pin_digits) != 14:
            continue
        key = (
            row.get('owner_user_id'),
            (row.get('owner_first_name') or '').strip().lower(),
            (row.get('owner_last_name') or '').strip().lower(),
            pin_digits,
        )
        buckets[key].append(dict(row))
    return [members for members in buckets.values() if len(members) >= 2]


def run(dry_run: bool = False, mode: str = 'unit'):
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/real_estate_analysis',
    )
    dsn = db_url.replace('postgresql+psycopg2://', 'postgresql://')

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        if mode in ('normalized', 'dedup', 'pin'):
            if mode == 'pin':
                cur.execute("""
                    SELECT id, owner_first_name, owner_last_name, property_street,
                           owner_user_id, lead_status, has_phone, has_email,
                           last_hubspot_sync_at, county_assessor_pin
                    FROM leads
                    WHERE county_assessor_pin IS NOT NULL AND county_assessor_pin != ''
                """)
            else:
                cur.execute("""
                    SELECT id, owner_first_name, owner_last_name, property_street,
                           owner_user_id, lead_status, has_phone, has_email,
                           last_hubspot_sync_at
                    FROM leads
                    WHERE owner_first_name IS NOT NULL AND owner_first_name != ''
                      AND property_street  IS NOT NULL AND property_street  != ''
                """)
            rows = cur.fetchall()
            confirmed_hs_ids = _fetch_confirmed_hubspot_lead_ids(cur)
            if mode == 'dedup':
                merge_groups = _find_dedup_merge_groups(rows)
                label = 'dedup-key'
            elif mode == 'pin':
                merge_groups = _find_pin_merge_groups(rows)
                label = 'pin'
            else:
                merge_groups = _find_normalized_merge_groups(rows)
                label = 'normalized'
            logger.info(
                "Found %d %s duplicate group(s) to merge",
                len(merge_groups), label,
            )

            total_merged = 0
            winners_to_rescore: set[int] = set()
            for members in merge_groups:
                winner = pick_merge_winner(members, confirmed_hs_ids)
                losers = [m for m in members if m['id'] != winner['id']]
                owner_display = (
                    f"{(members[0]['owner_first_name'] or '').strip().title()} "
                    f"{(members[0]['owner_last_name'] or '').strip().title()}"
                )
                logger.info(
                    "Group '%s' -> KEEP id=%d '%s' (%s), MERGE %d record(s): %s",
                    owner_display,
                    winner['id'], winner['property_street'],
                    winner.get('lead_status'),
                    len(losers), [r['id'] for r in losers],
                )

                if dry_run:
                    total_merged += len(losers)
                    continue

                for loser in losers:
                    _merge_loser_into_winner(cur, winner, loser)
                    total_merged += 1
                    winners_to_rescore.add(winner['id'])

        else:
            cur.execute("""
                SELECT id, owner_first_name, owner_last_name, property_street, owner_user_id
                FROM leads
                WHERE owner_first_name IS NOT NULL AND owner_first_name != ''
                  AND owner_last_name  IS NOT NULL AND owner_last_name  != ''
                  AND property_street  IS NOT NULL AND property_street  != ''
            """)
            rows = cur.fetchall()
            merge_groups = _find_unit_merge_groups(rows)
            logger.info("Found %d unit duplicate group(s) to merge", len(merge_groups))

            total_merged = 0
            winners_to_rescore = set()
            for key, bare_records, unit_records in merge_groups:
                winner = max(
                    unit_records,
                    key=lambda r: (len(r['property_street'] or ''), -r['id']),
                )
                losers = [r for r in bare_records + unit_records if r['id'] != winner['id']]

                owner_display = f"{key[0].title()} {key[1].title()}"
                logger.info(
                    "Group '%s' base='%s' -> KEEP id=%d '%s', MERGE %d record(s): %s",
                    owner_display, key[2],
                    winner['id'], winner['property_street'],
                    len(losers), [r['id'] for r in losers],
                )

                if dry_run:
                    total_merged += len(losers)
                    continue

                for loser in losers:
                    _merge_loser_into_winner(cur, winner, loser)
                    total_merged += 1
                    winners_to_rescore.add(winner['id'])

        if not dry_run:
            conn.commit()
            logger.info("Done. Merged %d duplicate record(s).", total_merged)
            if winners_to_rescore:
                from app import create_app
                from app.services.lead_refresh import refresh_lead_scoring

                app = create_app()
                with app.app_context():
                    for winner_id in winners_to_rescore:
                        refresh_lead_scoring(winner_id)
                logger.info("Rescored %d winner lead(s)", len(winners_to_rescore))
        else:
            conn.rollback()
            logger.info("[DRY RUN] Would merge %d duplicate record(s).", total_merged)

    except Exception as exc:
        conn.rollback()
        logger.error("Script failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Merge duplicate lead records')
    parser.add_argument('--dry-run', action='store_true', help='Preview without making changes')
    parser.add_argument(
        '--mode',
        choices=['unit', 'normalized', 'dedup', 'pin'],
        default='unit',
        help='Merge mode: unit, normalized, dedup, or pin (normalized assessor PIN)',
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, mode=args.mode)
