#!/usr/bin/env python3
"""Postgres lock / idle-in-transaction probes for Deploy + cron watchdog.

Modes:
  preflight  — fail if dangerous blockers exist (Deploy Track 4; no kill)
  smoke      — cheap contacts/leads reads + assert no exclusive locks / stale idle-xact
  watchdog   — terminate dangerous idle-in-transaction sessions (Track 3)

Exit codes:
  0 = ok (or watchdog found nothing / dry-run)
  1 = blockers found / smoke failed / terminate attempted with errors
  2 = usage / connection error

Env:
  DATABASE_URL — required (postgresql:// or postgresql+psycopg2://)
  BB_IDLE_XACT_GRACE_SEC — preflight/smoke idle-in-xact age (default 60)
  BB_WATCHDOG_EXCL_IDLE_SEC — exclusive+idle threshold (default 600)
  BB_WATCHDOG_ANY_IDLE_SEC — any idle-in-xact threshold (default 1800)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

DEFAULT_RELATIONS = (
    'contacts',
    'leads',
    'property_contacts',
    'alembic_version',
)


def _normalize_url(url: str) -> str:
    if url.startswith('postgresql+psycopg2://'):
        return 'postgresql://' + url[len('postgresql+psycopg2://'):]
    return url


def _connect():
    import psycopg2

    url = os.environ.get('DATABASE_URL')
    if not url:
        print('DATABASE_URL is required', file=sys.stderr)
        sys.exit(2)
    return psycopg2.connect(_normalize_url(url))


def _fetch_blockers(cur, grace_sec: int, relations: tuple[str, ...]) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT a.pid,
               a.usename,
               a.state,
               a.wait_event_type,
               a.wait_event,
               EXTRACT(EPOCH FROM (now() - a.xact_start)) AS xact_age_sec,
               EXTRACT(EPOCH FROM (now() - a.state_change)) AS state_age_sec,
               left(a.query, 200) AS query
        FROM pg_stat_activity a
        WHERE a.datname = current_database()
          AND a.pid <> pg_backend_pid()
          AND a.state = 'idle in transaction'
          AND a.xact_start IS NOT NULL
          AND EXTRACT(EPOCH FROM (now() - a.xact_start)) >= %s
        ORDER BY a.xact_start
        """,
        (grace_sec,),
    )
    rows = []
    for r in cur.fetchall():
        rows.append({
            'kind': 'idle_in_transaction',
            'pid': r[0],
            'usename': r[1],
            'state': r[2],
            'wait_event_type': r[3],
            'wait_event': r[4],
            'xact_age_sec': float(r[5] or 0),
            'state_age_sec': float(r[6] or 0),
            'query': r[7],
        })

    cur.execute(
        """
        SELECT a.pid,
               a.usename,
               a.state,
               l.mode,
               c.relname,
               EXTRACT(EPOCH FROM (now() - a.xact_start)) AS xact_age_sec,
               left(a.query, 200) AS query
        FROM pg_locks l
        JOIN pg_class c ON c.oid = l.relation
        JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.granted
          AND l.mode = 'AccessExclusiveLock'
          AND c.relname = ANY(%s)
          AND a.datname = current_database()
          AND a.pid <> pg_backend_pid()
        ORDER BY a.pid
        """,
        (list(relations),),
    )
    for r in cur.fetchall():
        rows.append({
            'kind': 'access_exclusive',
            'pid': r[0],
            'usename': r[1],
            'state': r[2],
            'mode': r[3],
            'relname': r[4],
            'xact_age_sec': float(r[5] or 0) if r[5] is not None else None,
            'query': r[6],
        })
    return rows


def cmd_preflight(args: argparse.Namespace) -> int:
    grace = int(os.environ.get('BB_IDLE_XACT_GRACE_SEC', args.grace_sec))
    conn = _connect()
    try:
        cur = conn.cursor()
        blockers = _fetch_blockers(cur, grace, DEFAULT_RELATIONS)
        if blockers:
            print('PREFLIGHT FAIL: migration blockers present', file=sys.stderr)
            print(json.dumps(blockers, indent=2, default=str), file=sys.stderr)
            return 1
        print('PREFLIGHT OK: no idle-in-xact (>%ss) or AccessExclusiveLock on app tables' % grace)
        return 0
    finally:
        conn.close()


def cmd_smoke(args: argparse.Namespace) -> int:
    grace = int(os.environ.get('BB_IDLE_XACT_GRACE_SEC', args.grace_sec))
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '5s'")
        cur.execute("SET lock_timeout = '5s'")
        for table in ('contacts', 'leads'):
            cur.execute(f'SELECT 1 FROM {table} LIMIT 1')
            cur.fetchone()
        blockers = _fetch_blockers(cur, grace, DEFAULT_RELATIONS)
        if blockers:
            print('SMOKE FAIL: post-migrate lock / idle-in-xact check failed', file=sys.stderr)
            print(json.dumps(blockers, indent=2, default=str), file=sys.stderr)
            return 1
        print('SMOKE OK: contacts/leads readable; no exclusive locks / stale idle-in-xact')
        return 0
    except Exception as exc:
        print(f'SMOKE FAIL: {exc}', file=sys.stderr)
        return 1
    finally:
        conn.close()


def _watchdog_targets(cur, excl_sec: int, any_sec: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        WITH idle AS (
            SELECT a.pid,
                   a.usename,
                   a.state,
                   EXTRACT(EPOCH FROM (now() - a.xact_start)) AS xact_age_sec,
                   left(a.query, 200) AS query,
                   EXISTS (
                       SELECT 1
                       FROM pg_locks l
                       JOIN pg_class c ON c.oid = l.relation
                       WHERE l.pid = a.pid
                         AND l.granted
                         AND l.mode = 'AccessExclusiveLock'
                   ) AS holds_exclusive
            FROM pg_stat_activity a
            WHERE a.datname = current_database()
              AND a.pid <> pg_backend_pid()
              AND a.state = 'idle in transaction'
              AND a.xact_start IS NOT NULL
        )
        SELECT pid, usename, state, xact_age_sec, query, holds_exclusive
        FROM idle
        WHERE (holds_exclusive AND xact_age_sec >= %s)
           OR (xact_age_sec >= %s)
        ORDER BY xact_age_sec DESC
        """,
        (excl_sec, any_sec),
    )
    out = []
    for r in cur.fetchall():
        out.append({
            'pid': r[0],
            'usename': r[1],
            'state': r[2],
            'xact_age_sec': float(r[3] or 0),
            'query': r[4],
            'holds_exclusive': bool(r[5]),
        })
    return out


def cmd_watchdog(args: argparse.Namespace) -> int:
    excl_sec = int(os.environ.get('BB_WATCHDOG_EXCL_IDLE_SEC', args.excl_idle_sec))
    any_sec = int(os.environ.get('BB_WATCHDOG_ANY_IDLE_SEC', args.any_idle_sec))
    conn = _connect()
    try:
        cur = conn.cursor()
        targets = _watchdog_targets(cur, excl_sec, any_sec)
        if not targets:
            print('WATCHDOG OK: no dangerous idle-in-transaction sessions')
            return 0
        print(json.dumps({'targets': targets}, indent=2, default=str))
        if args.dry_run:
            print('WATCHDOG dry-run: would terminate %d session(s)' % len(targets))
            return 0
        failed = 0
        for t in targets:
            cur.execute('SELECT pg_terminate_backend(%s)', (t['pid'],))
            ok = cur.fetchone()[0]
            print(f"terminated pid={t['pid']} ok={ok} age={t['xact_age_sec']:.0f}s excl={t['holds_exclusive']}")
            if not ok:
                failed += 1
        conn.commit()
        # Always exit 1 when we terminated so the shell wrapper can alert
        return 1 if targets else 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'mode',
        choices=('preflight', 'smoke', 'watchdog'),
    )
    parser.add_argument('--grace-sec', type=int, default=60)
    parser.add_argument('--excl-idle-sec', type=int, default=600)
    parser.add_argument('--any-idle-sec', type=int, default=1800)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)

    if args.mode == 'preflight':
        return cmd_preflight(args)
    if args.mode == 'smoke':
        return cmd_smoke(args)
    return cmd_watchdog(args)


if __name__ == '__main__':
    raise SystemExit(main())
