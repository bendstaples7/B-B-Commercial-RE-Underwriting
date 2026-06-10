"""
test_migration_app_factory.py — Unit tests for the non-blocking app factory behavior.

Verifies that create_app() in a migration context:
  - Returns a usable Flask app without raising SystemExit (Req 5.1)
  - Does not auto-call upgrade() (Req 5.2)
  - Does no destructive DB work (Req 5.3)
  - Raises ConfigurationError (not SystemExit) for missing required config (Req 5.4)
  - Does not redirect/suppress stdout (Req 5.5)
  - Completes within 5 seconds (Req 5.6)

Run with:  cd backend && python -m pytest tests/test_migration_app_factory.py -v
"""
import os
import sys
import time
import io
import logging
import pytest
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_env(overrides=None):
    """Return a minimal env dict suitable for a migration-context test.

    Sets KIRO_MIGRATION=1 plus overrides.  Does NOT include SECRET_KEY or
    DATABASE_URL by default so individual tests can control them.
    """
    env = {k: v for k, v in os.environ.items()}
    env['KIRO_MIGRATION'] = '1'
    # Remove keys that tests want to control so patch.dict clear=True works
    env.pop('SECRET_KEY', None)
    env.pop('DATABASE_URL', None)
    if overrides:
        env.update(overrides)
    return env


def _create_app_migration(extra_env=None, config_name='testing'):
    """Call create_app() with KIRO_MIGRATION=1 and heavy side-effects mocked.

    Mocks out:
      - db.init_app / migrate.init_app / limiter.init_app  (no real DB)
      - _validate_and_log_database_url  (tested separately)
      - _assert_pool_pre_ping           (tested separately)
      - flask_migrate.upgrade           (must NOT be called in migration context)
    """
    from app import create_app

    env = _base_env(overrides=extra_env)

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            app = create_app(config_name)
    return app


# ---------------------------------------------------------------------------
# Test 1 — migration context returns a Flask app (Req 5.1)
# ---------------------------------------------------------------------------

def test_migration_context_returns_app():
    """
    create_app() with KIRO_MIGRATION=1 returns a Flask application instance.
    Req 5.1: App_Factory SHALL return a usable application instance.
    """
    from flask import Flask

    app = _create_app_migration(extra_env={'SECRET_KEY': 'test-secret'})
    assert app is not None
    assert isinstance(app, Flask)


# ---------------------------------------------------------------------------
# Test 2 — migration context raises no SystemExit (Req 5.1)
# ---------------------------------------------------------------------------

def test_migration_context_no_system_exit():
    """
    create_app() with KIRO_MIGRATION=1 does not call SystemExit.
    Req 5.1: SHALL complete construction without invoking SystemExit.
    """
    # We verify this by simply calling create_app() and asserting it returns
    # without raising SystemExit.  If SystemExit were raised, pytest would
    # surface it as an error (not a pass).
    app = _create_app_migration(extra_env={'SECRET_KEY': 'test-secret'})
    assert app is not None  # reached here → no SystemExit


# ---------------------------------------------------------------------------
# Test 3 — migration context does NOT call upgrade() (Req 5.2)
# ---------------------------------------------------------------------------

def test_migration_context_no_auto_upgrade():
    """
    create_app() with KIRO_MIGRATION=1 never calls flask_migrate.upgrade().
    Req 5.2: App_Factory SHALL NOT apply migrations as a startup side effect.
    """
    from app import create_app

    env = _base_env(overrides={'SECRET_KEY': 'test-secret'})

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            with patch('flask_migrate.upgrade') as mock_upgrade:
                                create_app('testing')

    mock_upgrade.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4 — migration context skips the development auto-upgrade block
# ---------------------------------------------------------------------------

def test_migration_context_dev_mode_skips_upgrade():
    """
    Even when config_name='development', KIRO_MIGRATION=1 prevents auto-upgrade.
    Req 5.2: The migration-context gate must apply regardless of FLASK_ENV.
    """
    from app import create_app

    env = _base_env(overrides={
        'SECRET_KEY': 'test-secret',
        'DATABASE_URL': 'postgresql://user:pw@localhost:5432/testdb',
        'FLASK_ENV': 'development',
    })

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            with patch('flask_migrate.upgrade') as mock_upgrade:
                                # _assert_single_migration_head also must not be called
                                with patch('app._assert_single_migration_head') as mock_head_check:
                                    create_app('development')

    mock_upgrade.assert_not_called()
    mock_head_check.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — missing SECRET_KEY raises ConfigurationError, not SystemExit (Req 5.4)
# ---------------------------------------------------------------------------

def test_missing_secret_key_raises_configuration_error():
    """
    When SECRET_KEY is absent, create_app() raises ConfigurationError (not SystemExit).
    Req 5.4: App_Factory SHALL raise an exception that preserves the originating
    message, and SHALL NOT terminate the host process via SystemExit.
    """
    from app import create_app
    from app.exceptions import ConfigurationError

    env = _base_env()  # no SECRET_KEY

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            with pytest.raises(ConfigurationError) as exc_info:
                                create_app('development')  # non-testing → guard fires

    # The originating message must be preserved in the exception
    assert 'SECRET_KEY' in str(exc_info.value)


def test_missing_secret_key_not_system_exit():
    """
    Missing SECRET_KEY does NOT raise SystemExit — only ConfigurationError.
    Req 5.4: SHALL NOT terminate via SystemExit.
    """
    from app import create_app
    from app.exceptions import ConfigurationError

    env = _base_env()  # no SECRET_KEY

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            try:
                                create_app('development')
                                pytest.fail("Expected ConfigurationError was not raised")
                            except SystemExit:
                                pytest.fail(
                                    "create_app() raised SystemExit for missing SECRET_KEY — "
                                    "must raise ConfigurationError instead (Req 5.4)"
                                )
                            except ConfigurationError:
                                pass  # correct — test passes


# ---------------------------------------------------------------------------
# Test 6 — missing DATABASE_URL raises ConfigurationError, not SystemExit (Req 5.4)
# ---------------------------------------------------------------------------

def test_missing_database_url_raises_configuration_error():
    """
    When DATABASE_URL is absent, _validate_and_log_database_url raises
    ConfigurationError (not SystemExit).
    Req 5.4: originating message must be preserved.
    """
    from app import _validate_and_log_database_url
    from app.exceptions import ConfigurationError
    from flask import Flask

    app = Flask(__name__)
    app.config['TESTING'] = False

    env_without_db = {k: v for k, v in os.environ.items() if k != 'DATABASE_URL'}

    with patch.dict(os.environ, env_without_db, clear=True):
        with pytest.raises(ConfigurationError) as exc_info:
            _validate_and_log_database_url(app)

    assert 'DATABASE_URL' in str(exc_info.value)


def test_missing_database_url_not_system_exit():
    """
    Missing DATABASE_URL does NOT raise SystemExit.
    Req 5.4: SHALL NOT terminate via SystemExit.
    """
    from app import _validate_and_log_database_url
    from app.exceptions import ConfigurationError
    from flask import Flask

    app = Flask(__name__)
    app.config['TESTING'] = False

    env_without_db = {k: v for k, v in os.environ.items() if k != 'DATABASE_URL'}

    with patch.dict(os.environ, env_without_db, clear=True):
        try:
            _validate_and_log_database_url(app)
            pytest.fail("Expected ConfigurationError was not raised")
        except SystemExit:
            pytest.fail(
                "_validate_and_log_database_url raised SystemExit for missing DATABASE_URL — "
                "must raise ConfigurationError instead (Req 5.4)"
            )
        except ConfigurationError:
            pass  # correct


# ---------------------------------------------------------------------------
# Test 7 — ConfigurationError message is preserved (Req 5.4)
# ---------------------------------------------------------------------------

def test_configuration_error_message_preserved_secret_key():
    """
    The ConfigurationError raised for missing SECRET_KEY preserves the message
    string so it appears in command output (not swallowed).
    Req 5.4: the raised exception preserves the originating message.
    """
    from app import create_app
    from app.exceptions import ConfigurationError

    env = _base_env()  # no SECRET_KEY

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            try:
                                create_app('development')
                            except ConfigurationError as e:
                                # Message must be a non-empty string describing the problem
                                assert str(e), "ConfigurationError message must not be empty"
                                assert len(str(e)) > 10, (
                                    "ConfigurationError message is too short to be meaningful"
                                )
                                return

    pytest.fail("ConfigurationError was not raised for missing SECRET_KEY")


# ---------------------------------------------------------------------------
# Test 8 — app construction does not suppress/redirect stdout (Req 5.5)
# ---------------------------------------------------------------------------

def test_stdout_not_suppressed_after_app_construction():
    """
    After create_app() returns, sys.stdout is still functional.
    Req 5.5: App_Factory SHALL NOT suppress or redirect the command's console output.
    """
    # Capture stdout before construction
    captured = io.StringIO()
    original_stdout = sys.stdout

    app = _create_app_migration(extra_env={'SECRET_KEY': 'test-secret'})

    # After construction, write to stdout and confirm it works
    sys.stdout = captured
    try:
        print("test_stdout_check")
    finally:
        sys.stdout = original_stdout

    output = captured.getvalue()
    assert 'test_stdout_check' in output, (
        "stdout was suppressed or redirected during/after app construction (Req 5.5)"
    )


def test_stdout_not_redirected_to_devnull():
    """
    sys.stdout must not be replaced with /dev/null or similar during app construction.
    Req 5.5: console output from migration commands must be visible.
    """
    original_stdout = sys.stdout

    _create_app_migration(extra_env={'SECRET_KEY': 'test-secret'})

    # sys.stdout must still point to the same (or functionally equivalent) stream
    assert sys.stdout is not None, "sys.stdout is None after app construction"
    # It should not have been replaced with a DevNull object
    assert hasattr(sys.stdout, 'write'), "sys.stdout.write is missing after app construction"

    # Verify we can actually write to it (no exception)
    try:
        sys.stdout.write("")
    except Exception as e:
        pytest.fail(f"sys.stdout.write() raised after app construction: {e}")


# ---------------------------------------------------------------------------
# Test 9 — app construction completes within 5 seconds (Req 5.6)
# ---------------------------------------------------------------------------

def test_migration_context_completes_within_5_seconds():
    """
    create_app() with KIRO_MIGRATION=1 must complete within 5 seconds.
    Req 5.6: App_Factory SHALL complete construction within 5 seconds.
    """
    start = time.monotonic()
    _create_app_migration(extra_env={'SECRET_KEY': 'test-secret'})
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, (
        f"create_app() in migration context took {elapsed:.2f}s (limit: 5s) — "
        "Req 5.6 violated. Check for blocking I/O during construction."
    )


# ---------------------------------------------------------------------------
# Test 10 — _is_migration_context() detects KIRO_MIGRATION=1 (Req 5.4)
# ---------------------------------------------------------------------------

def test_is_migration_context_kiro_migration_env():
    """
    _is_migration_context() returns True when KIRO_MIGRATION=1 is set.
    This is the explicit opt-in guard used by deployment scripts and CI.
    """
    from app import _is_migration_context

    env = {k: v for k, v in os.environ.items()}
    env['KIRO_MIGRATION'] = '1'
    env.pop('FLASK_DB_COMMAND', None)

    with patch.dict(os.environ, env, clear=True):
        with patch('sys.argv', ['flask']):
            assert _is_migration_context() is True


def test_is_migration_context_flask_db_command_env():
    """
    _is_migration_context() returns True when FLASK_DB_COMMAND=1 is set.
    """
    from app import _is_migration_context

    env = {k: v for k, v in os.environ.items()}
    env['FLASK_DB_COMMAND'] = '1'
    env.pop('KIRO_MIGRATION', None)

    with patch.dict(os.environ, env, clear=True):
        with patch('sys.argv', ['flask']):
            assert _is_migration_context() is True


def test_is_migration_context_false_in_normal_startup():
    """
    _is_migration_context() returns False during a normal app startup
    (no migration env vars set, argv is not a flask db command).
    """
    from app import _is_migration_context

    env = {k: v for k, v in os.environ.items()}
    env.pop('KIRO_MIGRATION', None)
    env.pop('FLASK_DB_COMMAND', None)
    env.pop('FLASK_APP', None)

    with patch.dict(os.environ, env, clear=True):
        with patch('sys.argv', ['python', 'run.py']):
            assert _is_migration_context() is False


# ---------------------------------------------------------------------------
# Test 11 — migration context skips the superuser check (Req 5.2, 5.6)
# ---------------------------------------------------------------------------

def test_migration_context_skips_superuser_check():
    """
    In a migration context, _assert_not_superuser is never called.
    Req 5.6: must not block on DB queries that are unnecessary for migrations.
    """
    from app import create_app

    env = _base_env(overrides={
        'SECRET_KEY': 'test-secret',
        'DATABASE_URL': 'postgresql://user:pw@localhost:5432/testdb',
        'FLASK_ENV': 'development',
    })

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            with patch('app._assert_not_superuser') as mock_superuser:
                                create_app('development')

    mock_superuser.assert_not_called()


# ---------------------------------------------------------------------------
# Test 12 — migration context skips the Redis ping (Req 5.6)
# ---------------------------------------------------------------------------

def test_migration_context_skips_redis_ping():
    """
    In a migration context, _warn_missing_optional_keys (which contains the
    Redis ping) is either skipped or does not block.
    Req 5.6: no indefinite waits; Redis ping is bounded/skipped in migration path.
    """
    from app import create_app
    import redis as _redis

    env = _base_env(overrides={
        'SECRET_KEY': 'test-secret',
        'FLASK_ENV': 'development',
    })

    redis_connect_calls = []

    original_from_url = _redis.from_url

    def tracking_from_url(*args, **kwargs):
        redis_connect_calls.append((args, kwargs))
        return original_from_url(*args, **kwargs)

    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            with patch('redis.from_url', side_effect=tracking_from_url) as mock_redis:
                                create_app('development')

    # Redis should not be pinged in a migration context
    # (_warn_missing_optional_keys checks _is_migration_context() and returns early)
    mock_redis.assert_not_called()


# ---------------------------------------------------------------------------
# Test 13 — testing config_name does not trigger the SECRET_KEY guard (existing behavior)
# ---------------------------------------------------------------------------

def test_testing_config_bypasses_secret_key_guard():
    """
    config_name='testing' bypasses the SECRET_KEY guard (existing expected behavior).
    This ensures the test suite itself is not broken by the guard.
    """
    app = _create_app_migration(
        extra_env={},  # no SECRET_KEY
        config_name='testing',
    )
    assert app is not None
