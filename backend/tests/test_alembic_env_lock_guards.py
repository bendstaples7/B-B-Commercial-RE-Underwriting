"""Unit tests for Alembic env.py migration lock guards (timeouts + revision id)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_ENV_PATH = Path(__file__).resolve().parents[1] / 'alembic_migrations' / 'env.py'


def _load_helpers():
    """Load timeout/revision helpers without executing env.py module body."""
    # env.py runs Flask/migrate at import — extract functions via exec of subset.
    src = _ENV_PATH.read_text(encoding='utf-8')
    # Pull only the helper defs we need (between markers).
    start = src.index('def _is_postgres_connection')
    end = src.index('def run_migrations_online')
    chunk = src[start:end]
    ns: dict = {'os': __import__('os'), 'logger': MagicMock()}
    exec(chunk, ns)  # noqa: S102 — test-only load of helpers
    return ns


def test_is_postgres_connection():
    ns = _load_helpers()
    pg = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
    sqlite = SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))
    assert ns['_is_postgres_connection'](pg) is True
    assert ns['_is_postgres_connection'](sqlite) is False


def test_apply_postgres_migration_timeouts_issues_set_local():
    ns = _load_helpers()
    conn = MagicMock()
    ns['_apply_postgres_migration_timeouts'](conn)
    assert conn.execute.call_count == 2
    sqls = [str(c.args[0]) for c in conn.execute.call_args_list]
    assert any('idle_in_transaction_session_timeout' in s for s in sqls)
    assert any('lock_timeout' in s for s in sqls)


def test_revision_id_from_step():
    ns = _load_helpers()
    step = SimpleNamespace(up_revision_id='heal_own_20260819')
    assert ns['_revision_id_from_step'](step) == 'heal_own_20260819'


def test_transaction_per_migration_flag_in_env_source():
    src = _ENV_PATH.read_text(encoding='utf-8')
    assert "conf_args['transaction_per_migration'] = True" in src
    assert '_install_postgres_timeout_begin_hook' in src


def test_begin_hook_registers_listener_and_applies_timeouts():
    """Core guarantee: each connection.begin() re-applies SET LOCAL timeouts."""
    from unittest.mock import patch

    import sqlalchemy

    ns = _load_helpers()
    conn = MagicMock()
    conn.dialect = SimpleNamespace(name='postgresql')
    listeners: list = []

    def fake_listens_for(target, identifier):
        def deco(fn):
            listeners.append((target, identifier, fn))
            return fn

        return deco

    with patch.object(sqlalchemy.event, 'listens_for', fake_listens_for):
        ns['_install_postgres_timeout_begin_hook'](conn)

    assert len(listeners) == 1
    target, identifier, on_begin = listeners[0]
    assert target is conn
    assert identifier == 'begin'

    sync_conn = MagicMock()
    on_begin(sync_conn)
    assert sync_conn.execute.call_count == 2
    sqls = [str(c.args[0]) for c in sync_conn.execute.call_args_list]
    assert any('idle_in_transaction_session_timeout' in s for s in sqls)
    assert any('lock_timeout' in s for s in sqls)
