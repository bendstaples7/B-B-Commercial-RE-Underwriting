"""Tests for scripts/pg_lock_guard.py (no live DB required)."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'pg_lock_guard.py'


def _load():
    spec = importlib.util.spec_from_file_location('pg_lock_guard', _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_normalize_url():
    mod = _load()
    assert mod._normalize_url('postgresql+psycopg2://u:p@h/db') == 'postgresql://u:p@h/db'
    assert mod._normalize_url('postgresql://u:p@h/db') == 'postgresql://u:p@h/db'


def test_connect_failure_exits_2(monkeypatch):
    mod = _load()
    psycopg2 = SimpleNamespace(connect=MagicMock(side_effect=RuntimeError('bad dsn')))
    monkeypatch.setitem(sys.modules, 'psycopg2', psycopg2)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://bad')

    with pytest.raises(SystemExit) as exc:
        mod._connect()

    assert exc.value.code == 2


def test_fetch_blockers_checks_current_schema_relations_not_allowlist():
    mod = _load()
    cur = MagicMock()
    cur.fetchall.side_effect = [[], []]

    mod._fetch_blockers(cur, 60)

    exclusive_sql = cur.execute.call_args_list[1].args[0]
    assert "n.nspname NOT IN ('pg_catalog'" in exclusive_sql
    assert "n.nspname !~ '^pg_(toast_)?temp_[0-9]+$'" in exclusive_sql
    assert 'c.relname = ANY' not in exclusive_sql


def test_watchdog_dry_run_no_terminate():
    mod = _load()
    cur = MagicMock()
    cur.fetchall.return_value = [
        (
            42, 'app_user', 'idle in transaction',
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            700.0, 'SELECT 1', True,
        ),
    ]
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch.object(mod, '_connect', return_value=conn):
        rc = mod.main(['watchdog', '--dry-run'])
    assert rc == 0
    # dry-run must not call terminate
    assert all('pg_terminate_backend' not in str(c) for c in cur.execute.call_args_list)


def test_smoke_fails_on_blockers():
    mod = _load()
    cur = MagicMock()
    # SELECT 1 contacts, SELECT 1 leads, then idle blockers, then exclusive empty
    cur.fetchone.return_value = (1,)
    cur.fetchall.side_effect = [
        [(99, 'app_user', 'idle in transaction', None, None, 120.0, 120.0, 'SELECT')],
        [],
    ]
    conn = MagicMock()
    conn.cursor.return_value = cur
    with patch.object(mod, '_connect', return_value=conn):
        rc = mod.main(['smoke', '--grace-sec', '60'])
    assert rc == 1


def test_smoke_ok_when_clean():
    mod = _load()
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    cur.fetchall.side_effect = [[], []]
    conn = MagicMock()
    conn.cursor.return_value = cur
    with patch.object(mod, '_connect', return_value=conn):
        rc = mod.main(['smoke', '--grace-sec', '60'])
    assert rc == 0


def test_exclusive_lock_sql_not_table_allowlist():
    """Preflight must scan any user-schema AccessExclusiveLock, not 4 names."""
    src = _SCRIPT.read_text(encoding='utf-8')
    assert 'AccessExclusiveLock' in src
    assert "n.nspname NOT IN ('pg_catalog'" in src
    assert "n.nspname !~ '^pg_(toast_)?temp_[0-9]+$'" in src
    assert "IN ('contacts'" not in src
    assert "IN ('leads'" not in src


def test_watchdog_revalidates_before_terminate():
    mod = _load()
    cur = MagicMock()
    backend_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # First fetchall: targets; then fetchone for _still_dangerous False
    cur.fetchall.return_value = [
        (42, 'app_user', 'idle in transaction', backend_start, 700.0, 'SELECT 1', True),
    ]
    cur.fetchone.return_value = None  # PID no longer dangerous
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch.object(mod, '_connect', return_value=conn):
        rc = mod.main(['watchdog'])
    assert rc == 0
    assert all('pg_terminate_backend' not in str(c) for c in cur.execute.call_args_list)
    assert any(c.args[1] == (42, backend_start) for c in cur.execute.call_args_list)


def test_watchdog_terminate_returns_1():
    mod = _load()
    cur = MagicMock()
    backend_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cur.fetchall.return_value = [
        (42, 'app_user', 'idle in transaction', backend_start, 700.0, 'SELECT 1', True),
    ]
    # _still_dangerous then pg_terminate_backend
    cur.fetchone.side_effect = [(900.0, True), (True,)]
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch.object(mod, '_connect', return_value=conn):
        rc = mod.main(['watchdog'])
    assert rc == 1
    assert any('pg_terminate_backend' in str(c) for c in cur.execute.call_args_list)
