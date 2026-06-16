"""One-time script to merge duplicate Lead records where the same owner
appears at both a bare building address and a specific unit address.

Pattern:
  Lead A: "2553 N Drake Ave"      (bare building address — no unit)
  Lead B: "2553 N Drake Ave 1"    (specific unit address — keep this one)

Strategy:
  1. Find all (owner_name, base_street, owner_user_id) groups with > 1 record
     where at least one record has a bare address (no unit suffix).
  2. Within each group, keep the record with the most specific address
     (has a unit), or if ambiguous, keep the oldest (lowest id).
  3. Re-point all FK references from the "loser" to the "winner".
  4. Copy any non-null fields from loser -> winner that winner is missing.
  5. Delete the loser.

Run from the backend/ directory:
    python scripts/merge_duplicate_leads.py [--dry-run]
"""
import re
import sys
import argparse
import logging
import os

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

# Fields we copy from loser -> winner only when winner is NULL
COPYABLE_FIELDS = [
    'phone_1', 'phone_2', 'phone_3', 'phone_4', 'phone_5', 'phone_6', 'phone_7',
    'email_1', 'email_2', 'email_3', 'email_4', 'email_5',
    'mailing_address', 'mailing_city', 'mailing_state', 'mailing_zip',
    'notes', 'source', 'date_identified',
    'needs_skip_trace', 'skip_tracer', 'date_skip_traced',
    'date_added_to_hubspot', 'county_assessor_pin',
    'ownership_type', 'acquisition_date',
    'bedrooms', 'bathrooms', 'square_footage', 'lot_size', 'year_built',
    'units', 'units_allowed', 'zoning',
    'most_recent_sale', 'owner_2_first_name', 'owner_2_last_name',
    'address_2', 'returned_addresses', 'up_next_to_mail',
    'lead_score', 'lead_category', 'property_type',
]


def run(dry_run: bool = False):
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/real_estate_analysis')
    # Convert SQLAlchemy URL format to psycopg2 DSN if needed
    dsn = db_url.replace('postgresql+psycopg2://', 'postgresql://')

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # ----------------------------------------------------------------
        # Step 1: find candidate groups
        # ----------------------------------------------------------------
        cur.execute("""
            SELECT id, owner_first_name, owner_last_name, property_street, owner_user_id
            FROM leads
            WHERE owner_first_name IS NOT NULL AND owner_first_name != ''
              AND owner_last_name  IS NOT NULL AND owner_last_name  != ''
              AND property_street  IS NOT NULL AND property_street  != ''
        """)
        rows = cur.fetchall()

        # Group by (lower first, lower last, base_street, user_id)
        groups: dict = {}
        for row in rows:
            key = (
                (row['owner_first_name'] or '').strip().lower(),
                (row['owner_last_name']  or '').strip().lower(),
                strip_unit(row['property_street'] or '').strip().lower(),
                row['owner_user_id'],
            )
            groups.setdefault(key, []).append(dict(row))

        # Keep only groups where bare + unit both exist
        merge_groups = []
        for key, members in groups.items():
            if len(members) < 2:
                continue
            bare = [m for m in members if not has_unit(m['property_street'])]
            with_unit = [m for m in members if has_unit(m['property_street'])]
            if bare and with_unit:
                merge_groups.append((key, bare, with_unit))

        logger.info("Found %d duplicate group(s) to merge", len(merge_groups))

        # ----------------------------------------------------------------
        # Step 2: merge each group
        # ----------------------------------------------------------------
        total_merged = 0

        for key, bare_records, unit_records in merge_groups:
            # Winner: most specific address (longest), then lowest id
            winner = max(unit_records, key=lambda r: (len(r['property_street'] or ''), -r['id']))
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
                loser_id = loser['id']
                winner_id = winner['id']

                # Re-point FK tables — use savepoints so a constraint conflict
                # on one table doesn't abort the whole transaction
                for table, col in FK_TABLES:
                    try:
                        cur.execute("SAVEPOINT sp_fk")
                        cur.execute(
                            f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                            (winner_id, loser_id)
                        )
                        cur.execute("RELEASE SAVEPOINT sp_fk")
                        logger.debug("  Re-pointed %d row(s) in %s.%s", cur.rowcount, table, col)
                    except psycopg2.errors.UniqueViolation:
                        cur.execute("ROLLBACK TO SAVEPOINT sp_fk")
                        cur.execute("RELEASE SAVEPOINT sp_fk")
                        # Unique conflict (e.g. already member of same marketing list)
                        # — delete the loser's conflicting rows instead
                        cur.execute(f"DELETE FROM {table} WHERE {col} = %s", (loser_id,))
                        logger.debug("  Deleted conflicting rows in %s.%s", table, col)
                    except Exception as e:
                        cur.execute("ROLLBACK TO SAVEPOINT sp_fk")
                        cur.execute("RELEASE SAVEPOINT sp_fk")
                        logger.debug("  Skipping %s.%s (%s)", table, col, e)

                # Copy non-null fields from loser -> winner where winner is null
                cur.execute("SELECT * FROM leads WHERE id = %s", (winner_id,))
                winner_row = cur.fetchone()
                cur.execute("SELECT * FROM leads WHERE id = %s", (loser_id,))
                loser_row = cur.fetchone()

                if winner_row and loser_row:
                    updates = {}
                    for field in COPYABLE_FIELDS:
                        if field in winner_row and field in loser_row:
                            w_val = winner_row[field]
                            l_val = loser_row[field]
                            if (w_val is None or w_val == '') and l_val not in (None, ''):
                                updates[field] = l_val

                    if updates:
                        set_clause = ', '.join(f'"{k}" = %s' for k in updates)
                        cur.execute(
                            f"UPDATE leads SET {set_clause} WHERE id = %s",
                            list(updates.values()) + [winner_id]
                        )
                        logger.debug("  Copied %d field(s) from loser to winner", len(updates))

                # Delete the loser
                logger.info("  Deleting loser id=%d '%s'", loser_id, loser['property_street'])
                cur.execute("DELETE FROM leads WHERE id = %s", (loser_id,))
                total_merged += 1

        if not dry_run:
            conn.commit()
            logger.info("Done. Merged %d duplicate record(s).", total_merged)
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
    args = parser.parse_args()
    run(dry_run=args.dry_run)
