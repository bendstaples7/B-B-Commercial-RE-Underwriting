"""Preflight checks for the f9 owner+street dedup unique index migration.

Used by deploy.sh before ``flask db upgrade`` and by CI regression tests.

Run from backend/:
    python scripts/preflight_dedup_migration.py --verify
    python scripts/preflight_dedup_migration.py --f9-pending
    python scripts/preflight_dedup_migration.py --report
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import load_dotenv

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

load_dotenv(os.path.join(_BACKEND_DIR, '.env'))

from app.services.lead_merge_utils import dedup_street_key  # noqa: E402

F8_REVISION = 'f8a9b0c1d2e3'
F9_REVISION = 'f9a0b1c2d3e4'

_STREET_DUPE_SQL = sa.text("""
    SELECT owner_user_id,
           lower(trim(owner_first_name)),
           lower(trim(owner_last_name)),
           normalized_street,
           count(*) AS cluster_size
    FROM leads
    WHERE normalized_street IS NOT NULL AND normalized_street != ''
      AND owner_first_name IS NOT NULL AND owner_first_name != ''
      AND owner_last_name IS NOT NULL AND owner_last_name != ''
      AND owner_user_id IS NOT NULL
    GROUP BY 1, 2, 3, 4
    HAVING count(*) > 1
""")

_PIN_DUPE_SQL = sa.text("""
    SELECT owner_user_id, county_assessor_pin, count(*) AS cluster_size
    FROM leads
    WHERE owner_user_id IS NOT NULL
      AND county_assessor_pin IS NOT NULL AND county_assessor_pin != ''
    GROUP BY 1, 2
    HAVING count(*) > 1
""")


@dataclass
class PreflightReport:
    current_revision: str | None
    f9_pending: bool
    normalized_street_present: bool
    street_duplicate_clusters: int
    pin_duplicate_clusters: int
    street_examples: list[dict]
    pin_examples: list[dict]

    @property
    def safe_for_f9(self) -> bool:
        return self.street_duplicate_clusters == 0


def _database_url() -> str:
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is not set')
    return url.replace('postgresql+psycopg2://', 'postgresql://')


def _engine() -> sa.Engine:
    return sa.create_engine(_database_url())


def get_current_revision(conn: sa.Connection) -> str | None:
    try:
        row = conn.execute(sa.text('SELECT version_num FROM alembic_version LIMIT 1')).fetchone()
    except sa.exc.ProgrammingError:
        return None
    return row[0] if row else None


def normalized_street_column_exists(conn: sa.Connection) -> bool:
    if conn.dialect.name == 'sqlite':
        rows = conn.execute(sa.text('PRAGMA table_info(leads)')).fetchall()
        return any(row[1] == 'normalized_street' for row in rows)
    row = conn.execute(sa.text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'leads'
          AND column_name = 'normalized_street'
        LIMIT 1
    """)).fetchone()
    return row is not None


def _count_street_dupes_sql(conn: sa.Connection) -> tuple[int, list[dict]]:
    rows = conn.execute(_STREET_DUPE_SQL).fetchall()
    examples = [
        {
            'owner_user_id': row[0],
            'owner_first_name': row[1],
            'owner_last_name': row[2],
            'normalized_street': row[3],
            'cluster_size': row[4],
        }
        for row in rows[:5]
    ]
    return len(rows), examples


def _count_street_dupes_from_property_street(conn: sa.Connection) -> tuple[int, list[dict]]:
    rows = conn.execute(sa.text("""
        SELECT owner_user_id, owner_first_name, owner_last_name, property_street
        FROM leads
        WHERE property_street IS NOT NULL AND property_street != ''
          AND owner_first_name IS NOT NULL AND owner_first_name != ''
          AND owner_last_name IS NOT NULL AND owner_last_name != ''
          AND owner_user_id IS NOT NULL
    """)).fetchall()

    clusters: dict[tuple, list[str]] = defaultdict(list)
    for owner_user_id, first_name, last_name, property_street in rows:
        street_key = dedup_street_key(property_street)
        if not street_key:
            continue
        key = (
            owner_user_id,
            (first_name or '').strip().lower(),
            (last_name or '').strip().lower(),
            street_key,
        )
        clusters[key].append(property_street)

    dupes = {k: v for k, v in clusters.items() if len(v) > 1}
    examples = [
        {
            'owner_user_id': key[0],
            'owner_first_name': key[1],
            'owner_last_name': key[2],
            'normalized_street': key[3],
            'cluster_size': len(streets),
        }
        for key, streets in list(dupes.items())[:5]
    ]
    return len(dupes), examples


def count_street_duplicate_clusters(conn: sa.Connection) -> tuple[int, list[dict]]:
    if normalized_street_column_exists(conn):
        return _count_street_dupes_sql(conn)
    return _count_street_dupes_from_property_street(conn)


def count_pin_duplicate_clusters(conn: sa.Connection) -> tuple[int, list[dict]]:
    rows = conn.execute(_PIN_DUPE_SQL).fetchall()
    examples = [
        {
            'owner_user_id': row[0],
            'county_assessor_pin': row[1],
            'cluster_size': row[2],
        }
        for row in rows[:5]
    ]
    return len(rows), examples


def _script_directory() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option('script_location', os.path.join(_BACKEND_DIR, 'alembic_migrations'))
    return ScriptDirectory.from_config(cfg)


def is_f9_pending(conn: sa.Connection) -> bool:
    current = get_current_revision(conn)
    script = _script_directory()
    head = script.get_current_head()

    if current is None:
        for rev in script.walk_revisions(base='base', head=head):
            if rev.revision == F9_REVISION:
                return True
        return False

    if current == F9_REVISION:
        return False

    for rev in script.iterate_revisions(head, current):
        if rev.revision == F9_REVISION:
            return True
    return False


def build_report(conn: sa.Connection) -> PreflightReport:
    street_count, street_examples = count_street_duplicate_clusters(conn)
    pin_count, pin_examples = count_pin_duplicate_clusters(conn)
    return PreflightReport(
        current_revision=get_current_revision(conn),
        f9_pending=is_f9_pending(conn),
        normalized_street_present=normalized_street_column_exists(conn),
        street_duplicate_clusters=street_count,
        pin_duplicate_clusters=pin_count,
        street_examples=street_examples,
        pin_examples=pin_examples,
    )


def _print_report(report: PreflightReport) -> None:
    print(f'Current Alembic revision: {report.current_revision or "(none)"}')
    print(f'f9 dedup migration pending: {report.f9_pending}')
    print(f'normalized_street column present: {report.normalized_street_present}')
    print(f'Owner+street duplicate clusters: {report.street_duplicate_clusters}')
    print(f'Owner+PIN duplicate clusters: {report.pin_duplicate_clusters}')
    if report.street_examples:
        print('Street duplicate examples:')
        for ex in report.street_examples:
            print(
                f"  user={ex['owner_user_id']} "
                f"{ex['owner_first_name']} {ex['owner_last_name']} "
                f"@ {ex['normalized_street']} ({ex['cluster_size']})"
            )
    if report.pin_examples:
        print('PIN duplicate examples:')
        for ex in report.pin_examples:
            print(
                f"  user={ex['owner_user_id']} pin={ex['county_assessor_pin']} "
                f"({ex['cluster_size']})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description='Preflight checks for f9 dedup migration')
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Exit 0 when no owner+street duplicate clusters remain; exit 1 otherwise',
    )
    parser.add_argument(
        '--f9-pending',
        action='store_true',
        help='Exit 0 when f9 migration is pending; exit 1 when already at or past f9',
    )
    parser.add_argument(
        '--report',
        action='store_true',
        help='Print duplicate cluster summary (always exits 0)',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Print report as JSON (always exits 0)',
    )
    args = parser.parse_args()

    if not any((args.verify, args.f9_pending, args.report, args.json)):
        args.report = True

    engine = _engine()
    with engine.connect() as conn:
        report = build_report(conn)

    if args.json:
        print(json.dumps({
            'current_revision': report.current_revision,
            'f9_pending': report.f9_pending,
            'normalized_street_present': report.normalized_street_present,
            'street_duplicate_clusters': report.street_duplicate_clusters,
            'pin_duplicate_clusters': report.pin_duplicate_clusters,
            'street_examples': report.street_examples,
            'pin_examples': report.pin_examples,
            'safe_for_f9': report.safe_for_f9,
        }, indent=2))
        return

    if args.report:
        _print_report(report)
        return

    if args.f9_pending:
        if report.f9_pending:
            print(f'f9 dedup migration ({F9_REVISION}) is pending')
            raise SystemExit(0)
        print(f'Already at or past f9 dedup migration ({F9_REVISION})')
        raise SystemExit(1)

    if args.verify:
        if report.safe_for_f9:
            print('No owner+street duplicate clusters — safe for f9 migration')
            if report.pin_duplicate_clusters:
                print(
                    f'WARNING: {report.pin_duplicate_clusters} owner+PIN duplicate '
                    'cluster(s) remain; f9 will skip the PIN unique index'
                )
            raise SystemExit(0)
        print(
            f'ERROR: {report.street_duplicate_clusters} owner+street duplicate '
            'cluster(s) remain — run merge_duplicate_leads.py --mode dedup'
        )
        _print_report(report)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
