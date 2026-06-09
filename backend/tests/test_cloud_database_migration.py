"""
test_cloud_database_migration.py — Property-based and example-based tests for the
cloud database migration startup guards and configuration.

Feature: cloud-database-migration
Requirements: 2.1, 2.2, 2.5, 2.6, 2.7, 4.2, 4.5, 6.5, 7.1, 7.2, 7.4, 7.5,
              7.7, 7.8, 8.1, 8.2, 8.3, 8.4, 8.5

Run with:  cd backend && pytest tests/test_cloud_database_migration.py -v
"""
import os
import logging
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_with_url(db_url, config_name='testing'):
    """
    Create a Flask app with a specific DATABASE_URL, bypassing the
    _validate_and_log_database_url guard so tests can control it independently.
    """
    from app import create_app
    with patch.dict(os.environ, {'DATABASE_URL': db_url}, clear=False):
        with patch('app._validate_and_log_database_url'):
            app = create_app(config_name)
    return app


def _make_minimal_flask_app(db_url='sqlite:///:memory:'):
    """
    Create a minimal Flask app for testing guard functions directly,
    without running the full create_app() pipeline.
    """
    from flask import Flask
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['TESTING'] = True
    return app


# ===========================================================================
# Property 1: DATABASE_URL Passthrough
# Feature: cloud-database-migration, Property 1: DATABASE_URL Passthrough
# Validates: Requirements 2.1, 2.2
# ===========================================================================

from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st

# Strategy: generate valid PostgreSQL URL strings
_pg_hosts = st.one_of(
    st.just('db.example.com'),
    st.just('myhost.neon.tech'),
    st.just('localhost'),
    st.just('127.0.0.1'),
)
_pg_ports = st.one_of(st.just(5432), st.just(5433), st.just(6543))
_pg_dbnames = st.from_regex(r'[a-z][a-z0-9_]{0,15}', fullmatch=True)
_pg_users = st.from_regex(r'[a-z][a-z0-9_]{0,10}', fullmatch=True)
_pg_passwords = st.from_regex(r'[A-Za-z0-9!@#%^&*]{4,16}', fullmatch=True)
_pg_schemes = st.sampled_from(['postgresql', 'postgres'])
_ssl_suffix = st.one_of(st.just(''), st.just('?sslmode=require'), st.just('?sslmode=prefer'))


@st.composite
def valid_pg_urls(draw):
    scheme = draw(_pg_schemes)
    user = draw(_pg_users)
    password = draw(_pg_passwords)
    host = draw(_pg_hosts)
    port = draw(_pg_ports)
    dbname = draw(_pg_dbnames)
    ssl = draw(_ssl_suffix)
    return f"{scheme}://{user}:{password}@{host}:{port}/{dbname}{ssl}"


@given(db_url=valid_pg_urls())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_property1_database_url_passthrough(db_url):
    """
    # Feature: cloud-database-migration, Property 1: DATABASE_URL Passthrough
    For any valid PostgreSQL URL set as DATABASE_URL, SQLALCHEMY_DATABASE_URI
    must equal that URL exactly.
    """
    from app import create_app
    with patch.dict(os.environ, {'DATABASE_URL': db_url}, clear=False):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            app = create_app('testing')
    assert app.config['SQLALCHEMY_DATABASE_URI'] == db_url


# ===========================================================================
# Property 2: DATABASE_URL Fallback
# Feature: cloud-database-migration, Property 2: DATABASE_URL Fallback
# Validates: Requirements 2.7
# ===========================================================================

def test_property2_database_url_fallback():
    """
    # Feature: cloud-database-migration, Property 2: DATABASE_URL Fallback
    When DATABASE_URL is not set, SQLALCHEMY_DATABASE_URI must fall back to
    'postgresql://localhost/real_estate_analysis'.
    """
    from app import create_app
    env = {k: v for k, v in os.environ.items() if k != 'DATABASE_URL'}
    with patch.dict(os.environ, env, clear=True):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app.db.init_app'):
                    with patch('app.migrate.init_app'):
                        with patch('app.limiter.init_app'):
                            app = create_app('testing')
    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'postgresql://localhost/real_estate_analysis'


# ===========================================================================
# Property 3: Connection Pool Settings Invariant
# Feature: cloud-database-migration, Property 3: Connection Pool Settings Invariant
# Validates: Requirements 2.5, 8.4, 8.5
# ===========================================================================

_non_testing_config_names = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='_-'),
    min_size=1, max_size=20,
).filter(lambda s: s != 'testing' and s.strip() != '')


@given(config_name=_non_testing_config_names)
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_property3_connection_pool_settings_invariant(config_name):
    """
    # Feature: cloud-database-migration, Property 3: Connection Pool Settings Invariant
    For any non-testing config name, SQLALCHEMY_ENGINE_OPTIONS must contain
    pool_size=3, max_overflow=0, pool_pre_ping=True, pool_timeout=30.
    """
    from app import create_app
    with patch.dict(os.environ, {
        'DATABASE_URL': 'postgresql://user:pw@host:5432/db',
        'SECRET_KEY': 'test-secret-key-for-pool-test',
    }, clear=False):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app._assert_single_migration_head'):
                    with patch('app.db.init_app'):
                        with patch('app.migrate.init_app'):
                            with patch('app.limiter.init_app'):
                                app = create_app(config_name)
    opts = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
    assert opts.get('pool_size') == 3
    assert opts.get('max_overflow') == 0
    assert opts.get('pool_pre_ping') is True
    assert opts.get('pool_timeout') == 30


# ===========================================================================
# Property 4: Superuser Startup Rejection
# Feature: cloud-database-migration, Property 4: Superuser Startup Rejection
# Validates: Requirements 7.4, 7.5
# ===========================================================================

@given(
    host=st.one_of(
        st.just('db.example.com'),
        st.just('myhost.neon.tech'),
    ),
    user=_pg_users,
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
def test_property4_superuser_startup_rejection(host, user):
    """
    # Feature: cloud-database-migration, Property 4: Superuser Startup Rejection
    For any database connection where the connected user has usesuper=True,
    _assert_not_superuser must raise ConfigurationError (not SystemExit).
    Requirements: 5.1, 5.4
    """
    from app import _assert_not_superuser
    from app.exceptions import ConfigurationError
    db_url = f'postgresql://{user}:pw@{host}:5432/mydb'
    app = _make_minimal_flask_app(db_url)
    app.config['TESTING'] = False

    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, i: True  # result[0] == True
    mock_row.__bool__ = lambda self: True

    # Make fetchone() return a row where index 0 is True (usesuper=True)
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (True,)

    with patch('app.db.session.execute', return_value=mock_result):
        with app.app_context():
            with pytest.raises(ConfigurationError):
                _assert_not_superuser(app)


# ===========================================================================
# Property 5: Invalid DATABASE_URL Causes Startup Abort
# Feature: cloud-database-migration, Property 5: Invalid DATABASE_URL Causes Startup Abort
# Validates: Requirements 7.8, 8.2
# ===========================================================================

_invalid_db_urls = st.one_of(
    st.just(''),
    st.just('   '),
    st.just('mysql://user:pw@host/db'),
    st.just('sqlite:///local.db'),
    st.just('http://example.com'),
    st.just('ftp://files.example.com'),
    st.just('not-a-url-at-all'),
    st.just('redis://localhost:6379/0'),
    st.from_regex(r'[a-z]{2,6}://[a-z]{3,10}/[a-z]{3,10}', fullmatch=True).filter(
        lambda s: not s.startswith('postgresql') and not s.startswith('postgres')
    ),
)


@given(bad_url=_invalid_db_urls)
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_property5_invalid_database_url_causes_startup_abort(bad_url, caplog):
    """
    # Feature: cloud-database-migration, Property 5: Invalid DATABASE_URL Causes Startup Abort
    For any absent, empty, or non-PostgreSQL DATABASE_URL, _validate_and_log_database_url
    must raise ConfigurationError (not SystemExit) and log an error containing 'DATABASE_URL'.
    Requirements: 5.1, 5.4
    """
    from app import _validate_and_log_database_url
    from app.exceptions import ConfigurationError
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False  # guard only runs in non-testing mode

    env_patch = {'DATABASE_URL': bad_url} if bad_url.strip() else {}
    env_without = {k: v for k, v in os.environ.items() if k != 'DATABASE_URL'}

    with caplog.at_level(logging.ERROR, logger=app.logger.name):
        if bad_url.strip() == '':
            with patch.dict(os.environ, env_without, clear=True):
                with pytest.raises(ConfigurationError):
                    _validate_and_log_database_url(app)
        else:
            with patch.dict(os.environ, {'DATABASE_URL': bad_url}, clear=False):
                with pytest.raises(ConfigurationError):
                    _validate_and_log_database_url(app)

    log_text = caplog.text
    assert 'DATABASE_URL' in log_text, (
        f"Expected 'DATABASE_URL' in log output for bad_url={bad_url!r}, got: {log_text!r}"
    )


# ===========================================================================
# Property 6: Startup Log Redacts Credentials
# Feature: cloud-database-migration, Property 6: Startup Log Redacts Credentials
# Validates: Requirements 8.1
# ===========================================================================

_passwords = st.from_regex(r'[A-Za-z0-9]{4,20}', fullmatch=True)


@given(password=_passwords)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_property6_startup_log_redacts_credentials(password, caplog):
    """
    # Feature: cloud-database-migration, Property 6: Startup Log Redacts Credentials
    For any PostgreSQL URL with a password, the startup log must contain the
    hostname but must NOT contain the password string.
    """
    from app import _validate_and_log_database_url
    hostname = 'db.myhost.example.com'
    db_url = f'postgresql://appuser:{password}@{hostname}:5432/mydb'
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False  # guard only runs in non-testing mode

    with caplog.at_level(logging.INFO, logger=app.logger.name):
        with patch.dict(os.environ, {'DATABASE_URL': db_url}, clear=False):
            _validate_and_log_database_url(app)

    log_text = caplog.text
    assert hostname in log_text, (
        f"Expected hostname '{hostname}' in log output, got: {log_text!r}"
    )
    assert password not in log_text, (
        f"Password '{password}' must NOT appear in log output, got: {log_text!r}"
    )


# ===========================================================================
# Property 7: Multiple Alembic Heads Error Contains Revision IDs
# Feature: cloud-database-migration, Property 7: Multiple Alembic Heads Error Contains Revision IDs
# Validates: Requirements 4.5
# ===========================================================================

_hex_rev_id = st.from_regex(r'[0-9a-f]{12}', fullmatch=True)
_rev_id_sets = st.lists(_hex_rev_id, min_size=2, max_size=5, unique=True)


@given(head_ids=_rev_id_sets)
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
def test_property7_multiple_alembic_heads_error_contains_revision_ids(head_ids):
    """
    # Feature: cloud-database-migration, Property 7: Multiple Alembic Heads Error Contains Revision IDs
    For any set of 2+ Alembic head revision IDs, the RuntimeError message raised by
    _assert_single_migration_head must contain every revision ID in the set.

    The underlying validator (assert_single_head_and_root) does NOT call
    SystemExit — _assert_single_migration_head wraps it and raises RuntimeError.
    """
    from app import _assert_single_migration_head
    app = _make_minimal_flask_app()

    # Patch assert_single_head_and_root at the app package level.
    # _assert_single_migration_head resolves the name from the module namespace,
    # so patching the name in the ``app`` module object is sufficient.
    mock_result = {
        "head_count": len(head_ids),
        "head_revisions": list(head_ids),
        "root_count": 1,
        "root_revisions": ["000000000000"],
    }
    import app as app_module
    with patch.object(app_module, 'assert_single_head_and_root', return_value=mock_result):
        with pytest.raises(RuntimeError) as exc_info:
            _assert_single_migration_head(app)

    error_message = str(exc_info.value)
    for rev_id in head_ids:
        assert rev_id in error_message, (
            f"Expected revision ID '{rev_id}' in error message: {error_message!r}"
        )


# ===========================================================================
# Property 8: Migration Idempotency
# Feature: cloud-database-migration, Property 8: Migration Idempotency
# Validates: Requirements 4.2
# ===========================================================================

def test_property8_migration_idempotency():
    """
    # Feature: cloud-database-migration, Property 8: Migration Idempotency
    Verifies that the migration idempotency convention is documented and that
    the Alembic migration chain has a single head (prerequisite for idempotent
    upgrades). The convention requires all new migrations to use IF NOT EXISTS
    or op.execute() with raw SQL.

    Note: Existing migrations pre-date the idempotency convention and are not
    rewritten (per migrations.md: "Do NOT rewrite existing migration files").
    Full execution-based idempotency is verified in integration tests against
    a real PostgreSQL instance. This test verifies:
    1. The convention document exists and contains IF NOT EXISTS guidance
    2. The migration chain has exactly one head (required for idempotent upgrades)
    """
    import os as _os
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

    # 1. Verify the convention document exists and contains IF NOT EXISTS guidance
    # migrations.md lives in .kiro/steering/ at the workspace root (one level up from backend/)
    workspace_dir = _os.path.dirname(backend_dir)
    migrations_md = _os.path.join(workspace_dir, '.kiro', 'steering', 'migrations.md')

    assert _os.path.exists(migrations_md), (
        f"migrations.md must exist at {migrations_md} and document the idempotency convention"
    )
    with open(migrations_md) as f:
        content = f.read()
    assert 'IF NOT EXISTS' in content, (
        "migrations.md must document the IF NOT EXISTS idempotency convention"
    )
    assert 'idempotent' in content.lower(), (
        "migrations.md must mention idempotency"
    )

    # 2. Verify the migration chain has exactly one head
    alembic_cfg = Config()
    alembic_cfg.set_main_option(
        'script_location', _os.path.join(backend_dir, 'alembic_migrations')
    )
    script = ScriptDirectory.from_config(alembic_cfg)
    heads = script.get_heads()

    assert len(heads) == 1, (
        f"Migration chain has {len(heads)} heads: {heads}\n"
        "Multiple heads prevent idempotent upgrades. "
        "Fix: create a merge migration with `flask db merge -m 'merge' <rev1> <rev2>`."
    )


# ===========================================================================
# Property 9: Connection Pool Budget
# Feature: cloud-database-migration, Property 9: Connection Pool Budget
# Validates: Requirements 6.5
# ===========================================================================

_flask_worker_counts = st.integers(min_value=1, max_value=10)
_celery_thread_counts = st.integers(min_value=1, max_value=8)
_beat_process_counts = st.integers(min_value=0, max_value=1)

MAX_CONNECTIONS = 100  # conservative default for all major managed providers
MAX_OVERFLOW = 0


@given(
    flask_workers=_flask_worker_counts,
    celery_threads=_celery_thread_counts,
    beat_processes=_beat_process_counts,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_property9_connection_pool_budget(flask_workers, celery_threads, beat_processes):
    """
    # Feature: cloud-database-migration, Property 9: Connection Pool Budget
    For any combination within the deployment envelope (1-10 Flask workers,
    1-8 Celery threads, 0-1 Beat processes), total connections must be <=
    max_connections (100). pool_size is read from the application config.
    """
    from app import create_app
    with patch.dict(os.environ, {
        'DATABASE_URL': 'postgresql://user:pw@host:5432/db',
        'SECRET_KEY': 'test-secret-key-for-pool-budget',
    }, clear=False):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app._assert_single_migration_head'):
                    with patch('app.db.init_app'):
                        with patch('app.migrate.init_app'):
                            with patch('app.limiter.init_app'):
                                _app = create_app('development')
    pool_size = _app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_size']

    total = (
        pool_size * flask_workers +
        pool_size * celery_threads +
        pool_size * beat_processes
    )
    assert total <= MAX_CONNECTIONS, (
        f"Connection pool budget exceeded: {flask_workers} Flask workers + "
        f"{celery_threads} Celery threads + {beat_processes} Beat processes "
        f"× pool_size={pool_size} = {total} connections > {MAX_CONNECTIONS} max_connections.\n"
        f"Reduce pool_size or process counts."
    )


def test_property9_connection_pool_budget_boundary():
    """
    # Feature: cloud-database-migration, Property 9: Connection Pool Budget (boundary)
    Explicitly verify the worst-case deployment (10 Flask + 8 Celery + 1 Beat)
    stays within MAX_CONNECTIONS, and verify that exceeding the envelope
    (34 Flask + 34 Celery) would exceed MAX_CONNECTIONS — confirming the
    assertion is not vacuous.
    """
    from app import create_app
    with patch.dict(os.environ, {
        'DATABASE_URL': 'postgresql://user:pw@host:5432/db',
        'SECRET_KEY': 'test-secret-key-for-pool-boundary',
    }, clear=False):
        with patch('app._validate_and_log_database_url'):
            with patch('app._assert_pool_pre_ping'):
                with patch('app._assert_single_migration_head'):
                    with patch('app.db.init_app'):
                        with patch('app.migrate.init_app'):
                            with patch('app.limiter.init_app'):
                                _app = create_app('development')
    pool_size = _app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_size']

    # Worst-case within deployment envelope: must pass
    worst_case = pool_size * 10 + pool_size * 8 + pool_size * 1
    assert worst_case <= MAX_CONNECTIONS, (
        f"Worst-case deployment ({worst_case} connections) exceeds MAX_CONNECTIONS={MAX_CONNECTIONS}"
    )

    # Verify the assertion is non-vacuous: exceeding the envelope does exceed the budget
    over_budget = pool_size * 34 + pool_size * 34
    assert over_budget > MAX_CONNECTIONS, (
        f"Expected over-budget scenario ({over_budget}) to exceed MAX_CONNECTIONS={MAX_CONNECTIONS} "
        f"— if this fails, pool_size has changed and the test ranges need updating"
    )


# ===========================================================================
# Example-based: .env.example and .gitignore correctness
# Task 9.1 — Requirements: 2.6, 7.1, 7.2, 7.7
# ===========================================================================




def test_env_example_no_real_credentials_in_uncommented_database_url():
    """
    backend/.env.example must not contain real credentials in uncommented DATABASE_URL lines.
    Uncommented DATABASE_URL lines must not contain '@' (which indicates real host/credentials).
    """
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_example_path = os.path.join(backend_dir, '.env.example')
    with open(env_example_path) as f:
        lines = f.readlines()

    for line in lines:
        stripped = line.strip()
        # Skip comments and blank lines
        if stripped.startswith('#') or not stripped:
            continue
        if stripped.startswith('DATABASE_URL='):
            value = stripped[len('DATABASE_URL='):]
            # The localhost fallback is acceptable; real cloud hosts are not
            assert '@' not in value or 'localhost' in value or '127.0.0.1' in value, (
                f"Uncommented DATABASE_URL in .env.example contains real credentials: {stripped!r}"
            )


def test_gitignore_includes_backend_env():
    """The .gitignore must include backend/.env to prevent credential commits."""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Check root .gitignore or backend/.gitignore
    found = False
    for gitignore_path in [
        os.path.join(project_root, '.gitignore'),
        os.path.join(backend_dir, '.gitignore'),
    ]:
        if os.path.exists(gitignore_path):
            with open(gitignore_path) as f:
                content = f.read()
            if 'backend/.env' in content or '.env' in content:
                found = True
                break

    assert found, (
        "Neither root .gitignore nor backend/.gitignore includes 'backend/.env' or '.env'. "
        "Add 'backend/.env' to .gitignore to prevent credential commits."
    )


# ===========================================================================
# Example-based: Guard 1 edge cases
# Task 9.2 — Requirements: 7.8, 8.1, 8.2
# ===========================================================================

def test_guard1_valid_postgresql_url_logs_hostname_no_password(caplog):
    """Guard 1: valid postgresql:// URL → INFO log contains hostname, no password."""
    from app import _validate_and_log_database_url
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False  # guard only runs in non-testing mode
    db_url = 'postgresql://appuser:s3cr3tPss@db.myhost.example.com:5432/mydb'

    with caplog.at_level(logging.INFO, logger=app.logger.name):
        with patch.dict(os.environ, {'DATABASE_URL': db_url}, clear=False):
            _validate_and_log_database_url(app)

    assert 'db.myhost.example.com' in caplog.text
    assert 's3cr3tPss' not in caplog.text


def test_guard1_postgres_scheme_accepted(caplog):
    """Guard 1: postgres:// scheme (without 'ql') is also accepted."""
    from app import _validate_and_log_database_url
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False  # guard only runs in non-testing mode
    db_url = 'postgres://appuser:pw@db.example.com:5432/mydb'

    with caplog.at_level(logging.INFO, logger=app.logger.name):
        with patch.dict(os.environ, {'DATABASE_URL': db_url}, clear=False):
            _validate_and_log_database_url(app)  # must not raise

    assert 'db.example.com' in caplog.text


def test_guard1_missing_database_url_raises_system_exit(caplog):
    """Guard 1: DATABASE_URL absent → ConfigurationError raised, log contains 'DATABASE_URL'."""
    from app import _validate_and_log_database_url
    from app.exceptions import ConfigurationError
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False  # guard only runs in non-testing mode
    env_without = {k: v for k, v in os.environ.items() if k != 'DATABASE_URL'}

    with caplog.at_level(logging.ERROR, logger=app.logger.name):
        with patch.dict(os.environ, env_without, clear=True):
            with pytest.raises(ConfigurationError):
                _validate_and_log_database_url(app)

    assert 'DATABASE_URL' in caplog.text


def test_guard1_mysql_scheme_raises_system_exit(caplog):
    """Guard 1: mysql:// scheme → ConfigurationError raised, log contains 'DATABASE_URL'."""
    from app import _validate_and_log_database_url
    from app.exceptions import ConfigurationError
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False  # guard only runs in non-testing mode

    with caplog.at_level(logging.ERROR, logger=app.logger.name):
        with patch.dict(os.environ, {'DATABASE_URL': 'mysql://user:pw@host/db'}, clear=False):
            with pytest.raises(ConfigurationError):
                _validate_and_log_database_url(app)

    assert 'DATABASE_URL' in caplog.text


# ===========================================================================
# Example-based: Guard 2 edge cases
# Task 9.3 — Requirements: 8.4, 8.5
# ===========================================================================

def test_guard2_testing_config_skips_pool_pre_ping_check():
    """Guard 2: config_name='testing' with pool_pre_ping absent → no RuntimeError."""
    from app import _assert_pool_pre_ping
    from sqlalchemy.pool import NullPool
    app = _make_minimal_flask_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': NullPool}  # no pool_pre_ping

    _assert_pool_pre_ping(app)  # must not raise


def test_guard2_development_config_with_pool_pre_ping_passes():
    """Guard 2: non-testing config with pool_pre_ping=True → no RuntimeError."""
    from app import _assert_pool_pre_ping
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 3,
        'max_overflow': 0,
        'pool_pre_ping': True,
        'pool_timeout': 30,
    }

    _assert_pool_pre_ping(app)  # must not raise


def test_guard2_development_config_without_pool_pre_ping_raises():
    """Guard 2: non-testing config with pool_pre_ping absent → RuntimeError raised."""
    from app import _assert_pool_pre_ping
    app = _make_minimal_flask_app()
    app.config['TESTING'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 3,
        'max_overflow': 0,
        # pool_pre_ping intentionally absent
        'pool_timeout': 30,
    }

    with pytest.raises(RuntimeError, match='pool_pre_ping'):
        _assert_pool_pre_ping(app)


# ===========================================================================
# Example-based: Guard 4 (provider dashboard warning)
# Task 9.4 — Requirements: 8.3
# ===========================================================================

def test_guard4_provider_dashboard_url_set_logs_warning_with_url(caplog):
    """Guard 4: PROVIDER_DASHBOARD_URL set → WARNING log contains the URL."""
    from app import _warn_provider_dashboard
    app = _make_minimal_flask_app()
    dashboard_url = 'https://console.neon.tech/app/projects/my-project-id'

    with caplog.at_level(logging.WARNING, logger=app.logger.name):
        with patch.dict(os.environ, {'PROVIDER_DASHBOARD_URL': dashboard_url}, clear=False):
            _warn_provider_dashboard(app)

    assert dashboard_url in caplog.text


def test_guard4_provider_dashboard_url_absent_logs_warning_with_key_name(caplog):
    """Guard 4: PROVIDER_DASHBOARD_URL absent → WARNING log contains 'PROVIDER_DASHBOARD_URL'."""
    from app import _warn_provider_dashboard
    app = _make_minimal_flask_app()
    env_without = {k: v for k, v in os.environ.items() if k != 'PROVIDER_DASHBOARD_URL'}

    with caplog.at_level(logging.WARNING, logger=app.logger.name):
        with patch.dict(os.environ, env_without, clear=True):
            _warn_provider_dashboard(app)

    assert 'PROVIDER_DASHBOARD_URL' in caplog.text
