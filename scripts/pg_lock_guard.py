#!/usr/bin/env python3
"""Postgres lock / idle-in-transaction probes for Deploy + cron watchdog.

Modes:
  preflight  — fail if dangerous blockers exist (Deploy Track 4; no kill)
  smoke      — cheap contacts/leads reads + assert no exclusive locks / stale idle-xact
  watchdog   — terminate dangerous idle-in-transaction sessions (Track 3)

Exit codes:
  0 = ok (or watchdog found nothing / dry-run)
  1 = blockers found / smoke failed / sessions terminated (watchdog alert path)
  2 = usage / connection / runtime error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Cheap readability checks for post-migrate smoke.
SMOKE_TABLES = ('contacts', 'leads')


def _normalize_url(url: str) -> str:
    if url.startswith('postgresql+psycopg2://'):
        return 'postgresql://' + url[len('postgresql+psycopg2://'):]
    return url


def _connect():
    import psycopg2
    from psycopg2 import OperationalError

    url = os.environ.get('DATABASE_URL')
    if not url:
        print('DATABASE_URL is required', file=sys.stderr)
        sys.exit(2)
    try:
        return psycopg2.connect(_normalize_url(url))
    except OperationalError as exc:
        print(f'DATABASE_URL connection failed: {exc}', file=sys.stderr)
        sys.exit(2)


def _fetch_blockers(cur, grace_sec: int) -> list[dict[str, Any]]:
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

    # Any granted AccessExclusiveLock on a user relation in this database
    # (not limited to a four-name allowlist — Deploy must not start Alembic
    # while *any* exclusive migration-class lock is held).
    cur.execute(
        """
        SELECT a.pid,
               a.usename,
               a.state,
               l.mode,
               n.nspname || '.' || c.relname AS relname,
               EXTRACT(EPOCH FROM (now() - a.xact_start)) AS xact_age_sec,
               left(a.query, 200) AS query
        FROM pg_locks l
        JOIN pg_class c ON c.oid = l.relation
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.granted
          AND l.mode = 'AccessExclusiveLock'
          AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
          AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
          AND a.datname = current_database()
          AND a.pid <> pg_backend_pid()
        ORDER BY a.pid
        """
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
        blockers = _fetch_blockers(cur, grace)
        if blockers:
            print('PREFLIGHT FAIL: migration blockers present', file=sys.stderr)
            print(json.dumps(blockers, indent=2, default=str), file=sys.stderr)
            return 1
        print(
            'PREFLIGHT OK: no idle-in-xact (>%ss) or AccessExclusiveLock on user tables'
            % grace
        )
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
        for table in SMOKE_TABLES:
            cur.execute(f'SELECT 1 FROM {table} LIMIT 1')
            cur.fetchone()
        blockers = _fetch_blockers(cur, grace)
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


def _still_dangerous(cur, pid: int, excl_sec: int, any_sec: int) -> bool:
    """Re-check immediately before terminate so we do not kill a recycled PID."""
    cur.execute(
        """
        SELECT EXTRACT(EPOCH FROM (now() - a.xact_start)) AS xact_age_sec,
               EXISTS (
                   SELECT 1
                   FROM pg_locks l
                   WHERE l.pid = a.pid
                     AND l.granted
                     AND l.mode = 'AccessExclusiveLock'
               ) AS holds_exclusive
        FROM pg_stat_activity a
        WHERE a.pid = %s
          AND a.datname = current_database()
          AND a.state = 'idle in transaction'
          AND a.xact_start IS NOT NULL
        """,
        (pid,),
    )
    row = cur.fetchone()
    if not row:
        return False
    age = float(row[0] or 0)
    holds_exclusive = bool(row[1])
    if holds_exclusive and age >= excl_sec:
        return True
    if age >= any_sec:
        return True
    return False


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
        terminated = 0
        skipped = 0
        failed = 0
        for t in targets:
            if not _still_dangerous(cur, t['pid'], excl_sec, any_sec):
                print(f"skip pid={t['pid']} (no longer dangerous idle-in-xact)")
                skipped += 1
                continue
            cur.execute('SELECT pg_terminate_backend(%s)', (t['pid'],))
            ok = cur.fetchone()[0]
            print(
                f"terminated pid={t['pid']} ok={ok} age={t['xact_age_sec']:.0f}s "
                f"excl={t['holds_exclusive']}"
            )
            if ok:
                terminated += 1
            else:
                failed += 1
        conn.commit()
        if terminated:
            return 1
        if failed:
            print(f'WATCHDOG: {failed} terminate call(s) returned false', file=sys.stderr)
            return 2
        print(f'WATCHDOG: nothing terminated (skipped={skipped})')
        return 0
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
    try:
        args = parser.parse_args(argv)
        if args.mode == 'preflight':
            return cmd_preflight(args)
        if args.mode == 'smoke':
            return cmd_smoke(args)
        return cmd_watchdog(args)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 2
    except Exception as exc:
        print(f'pg_lock_guard error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
