"""Apply lead dedup migrations without full Flask app startup.

Run from backend/:
    python scripts/apply_dedup_migrations.py
"""
import os
import subprocess
import sys

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from app.services.lead_merge_utils import dedup_street_key

F8 = 'f8a9b0c1d2e3'
F9 = 'f9a0b1c2d3e4'


def connect():
    url = os.environ['DATABASE_URL'].replace('postgresql+psycopg2://', 'postgresql://')
    return psycopg2.connect(url)


def current_revision(cur) -> str:
    cur.execute('SELECT version_num FROM alembic_version')
    row = cur.fetchone()
    return row[0] if row else ''


def set_revision(cur, rev: str) -> None:
    cur.execute('UPDATE alembic_version SET version_num = %s', (rev,))


def apply_f8(cur) -> None:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='leads' AND column_name='normalized_street'"
    )
    if not cur.fetchone():
        print('Adding normalized_street column...')
        cur.execute('ALTER TABLE leads ADD COLUMN normalized_street VARCHAR(500)')
        cur.execute(
            'CREATE INDEX IF NOT EXISTS ix_leads_normalized_street ON leads (normalized_street)'
        )

    print('Backfilling normalized_street...')
    cur.execute(
        "SELECT id, property_street FROM leads "
        "WHERE property_street IS NOT NULL AND property_street != ''"
    )
    batch = []
    for row in cur.fetchall():
        key = dedup_street_key(row[1])
        if key:
            batch.append((key, row[0]))
        if len(batch) >= 2000:
            psycopg2.extras.execute_batch(
                cur,
                'UPDATE leads SET normalized_street = %s WHERE id = %s',
                batch,
            )
            batch.clear()
    if batch:
        psycopg2.extras.execute_batch(
            cur,
            'UPDATE leads SET normalized_street = %s WHERE id = %s',
            batch,
        )


def assert_no_dupes(cur) -> None:
    cur.execute(
        """
        SELECT owner_user_id,
               lower(trim(owner_first_name)),
               lower(trim(owner_last_name)),
               normalized_street,
               count(*)
        FROM leads
        WHERE normalized_street IS NOT NULL AND normalized_street != ''
          AND owner_first_name IS NOT NULL AND owner_first_name != ''
          AND owner_last_name IS NOT NULL AND owner_last_name != ''
          AND owner_user_id IS NOT NULL
        GROUP BY 1, 2, 3, 4
        HAVING count(*) > 1
        LIMIT 5
        """
    )
    rows = cur.fetchall()
    if rows:
        raise SystemExit(
            'Duplicate clusters remain. Run: python scripts/merge_duplicate_leads.py --mode dedup\n'
            f'Examples: {rows}'
        )


def apply_f9(cur) -> None:
    assert_no_dupes(cur)
    print('Creating unique owner+street dedup index...')
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_owner_normalized_street
        ON leads (
            owner_user_id,
            lower(trim(owner_first_name)),
            lower(trim(owner_last_name)),
            normalized_street
        )
        WHERE owner_user_id IS NOT NULL
          AND owner_first_name IS NOT NULL AND owner_first_name != ''
          AND owner_last_name IS NOT NULL AND owner_last_name != ''
          AND normalized_street IS NOT NULL AND normalized_street != ''
    """)
    cur.execute(
        """
        SELECT owner_user_id, county_assessor_pin, count(*)
        FROM leads
        WHERE owner_user_id IS NOT NULL
          AND county_assessor_pin IS NOT NULL AND county_assessor_pin != ''
        GROUP BY 1, 2
        HAVING count(*) > 1
        LIMIT 1
        """
    )
    if cur.fetchone():
        print(
            'WARNING: Skipping uq_leads_owner_assessor_pin — duplicate PINs exist '
            'for the same owner.'
        )
        return
    print('Creating unique owner+PIN dedup index...')
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_owner_assessor_pin
        ON leads (owner_user_id, county_assessor_pin)
        WHERE owner_user_id IS NOT NULL
          AND county_assessor_pin IS NOT NULL AND county_assessor_pin != ''
    """)


def main() -> None:
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()
    rev = current_revision(cur)
    print(f'Current alembic revision: {rev}')

    try:
        if rev < F8 or rev == 'e7f8a9b0c1d2':
            apply_f8(cur)
            set_revision(cur, F8)
            conn.commit()
            print(f'Stamped {F8}')
            rev = F8

        if rev == F8:
            conn.commit()
            cur.close()
            conn.close()
            print('Running dedup merge...')
            subprocess.run(
                [sys.executable, 'scripts/merge_duplicate_leads.py', '--mode', 'dedup'],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                check=True,
            )
            conn = connect()
            conn.autocommit = False
            cur = conn.cursor()

        if current_revision(cur) == F8:
            apply_f9(cur)
            set_revision(cur, F9)
            conn.commit()
            print(f'Stamped {F9} — dedup migrations complete.')
        else:
            print(f'Nothing to do (revision {current_revision(cur)}).')
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
