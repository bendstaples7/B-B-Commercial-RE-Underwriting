"""Terminate stale PostgreSQL sessions that block migrations or long-running scripts.

Dry-run by default — pass --apply to terminate matching backends.
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2
from dotenv import load_dotenv

_STALE_QUERY = """
    SELECT pid, state, left(query, 120) AS query_preview
    FROM pg_stat_activity
    WHERE datname = current_database()
      AND pid != pg_backend_pid()
      AND (
        state = 'idle in transaction'
        OR query ILIKE '%normalized_street%'
        OR query ILIKE '%merge_duplicate%'
      )
      AND NOT (
        state = 'active'
        AND (
          query ILIKE '%ALTER TABLE%'
          OR query ILIKE '%CREATE INDEX%'
          OR query ILIKE '%DROP TABLE%'
          OR query ILIKE '%ADD COLUMN%'
        )
      )
"""


def _connect():
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    url = os.environ['DATABASE_URL'].replace('postgresql+psycopg2://', 'postgresql://')
    return psycopg2.connect(url)


def find_stale_sessions(cur):
    cur.execute(_STALE_QUERY)
    return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Terminate stale PG sessions (dry-run unless --apply).',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Terminate matching sessions (default is dry-run report only).',
    )
    args = parser.parse_args()

    conn = _connect()
    cur = conn.cursor()
    rows = find_stale_sessions(cur)

    if not rows:
        print('No stale sessions found.')
        cur.close()
        conn.close()
        return 0

    if not args.apply:
        print(f'DRY-RUN: would terminate {len(rows)} session(s):')
        for pid, state, preview in rows:
            print(f'  pid={pid} state={state} query={preview!r}')
        print('Re-run with --apply to terminate.')
        cur.close()
        conn.close()
        return 0

    conn.autocommit = True
    for pid, state, preview in rows:
        print(f'Terminating pid {pid} ({state}): {preview!r}')
        cur.execute('SELECT pg_terminate_backend(%s)', (pid,))
    print(f'Terminated {len(rows)} session(s)')
    cur.close()
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
