"""Regression tests for the f9 dedup migration gate (owner+street unique index)."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
import sqlalchemy as sa

from app import db
from app.models.lead import Lead
from app.models.user import User
from app.services.lead_merge_utils import dedup_street_key
from scripts.preflight_dedup_migration import (
    F8_REVISION,
    F9_REVISION,
    build_report,
    count_street_duplicate_clusters,
)
from scripts.merge_duplicate_leads import _find_dedup_merge_groups

MIGRATION_TEST_DB_URL = os.environ.get('MIGRATION_TEST_DB_URL')

integration = pytest.mark.skipif(
    not MIGRATION_TEST_DB_URL,
    reason='MIGRATION_TEST_DB_URL not set — dedup migration gate tests require PostgreSQL',
)


def _backend_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _migration_env(db_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env['DATABASE_URL'] = db_url
    env['FLASK_APP'] = 'run.py'
    env['FLASK_ENV'] = 'testing'
    env['FLASK_DB_COMMAND'] = '1'
    env['KIRO_MIGRATION'] = '1'
    env.setdefault('SECRET_KEY', 'ci-test-secret-key')
    env.setdefault('JWT_SECRET_KEY', 'ci-test-jwt-secret')
    env.setdefault('REDIS_URL', 'redis://localhost:6379/0')
    env.setdefault('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    return env


def _run_flask_db(db_url: str, revision: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, '-m', 'flask', 'db', 'upgrade']
    if revision:
        cmd.append(revision)
    return subprocess.run(
        cmd,
        cwd=_backend_dir(),
        env=_migration_env(db_url),
        capture_output=True,
        text=True,
        timeout=300,
    )


def _run_merge(db_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, 'scripts/merge_duplicate_leads.py', '--mode', 'dedup'],
        cwd=_backend_dir(),
        env=_migration_env(db_url),
        capture_output=True,
        text=True,
        timeout=300,
    )


def _seed_duplicate_leads(db_url: str) -> None:
    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(sa.text("""
            INSERT INTO users (
                user_id, email, email_lower, password_hash, display_name,
                is_active, is_admin, password_set
            ) VALUES (
                'test-dedup-user', 'test-dedup@example.com', 'test-dedup@example.com',
                'hash', 'Dedup Test', true, false, false
            )
            ON CONFLICT (user_id) DO NOTHING
        """))
        for street in ('107 S Grant Street', '107 S Grant St', '107 South Grant'):
            conn.execute(sa.text("""
                INSERT INTO leads (
                    property_street, normalized_street,
                    owner_first_name, owner_last_name, owner_user_id
                ) VALUES (
                    :street, :normalized_street,
                    'Jane', 'Doe', 'test-dedup-user'
                )
            """), {
                'street': street,
                'normalized_street': dedup_street_key(street),
            })
        conn.commit()
    engine.dispose()


@pytest.fixture
@integration
def dedup_gate_db():
    """Fresh PostgreSQL database upgraded to f8 with duplicate seed data."""
    db_url = MIGRATION_TEST_DB_URL
    assert db_url is not None

    result = _run_flask_db(db_url, F8_REVISION)
    assert result.returncode == 0, result.stderr or result.stdout

    _seed_duplicate_leads(db_url)
    yield db_url


class TestPreflightDedupMigration:
    def test_counts_duplicate_clusters_on_normalized_street(self, app):
        with app.app_context():
            user = User(
                user_id='preflight-user',
                email='preflight@example.com',
                email_lower='preflight@example.com',
                password_hash='hash',
                display_name='Preflight',
            )
            db.session.add(user)
            db.session.flush()
            for street in ('1915 W Schiller St', '1915 W Schiller'):
                db.session.add(Lead(
                    property_street=street,
                    normalized_street=dedup_street_key(street),
                    owner_first_name='Ronald',
                    owner_last_name='Jutkins',
                    owner_user_id=user.user_id,
                ))
            db.session.commit()

            with db.engine.connect() as conn:
                count, examples = count_street_duplicate_clusters(conn)

            assert count == 1
            assert examples[0]['cluster_size'] == 2


class TestDedupMergeGroups:
    def test_groups_exact_owner_street_key_for_entity_like_owner_names(self):
        rows = [
            {
                'id': 1,
                'owner_user_id': 'test-dedup-user',
                'owner_first_name': '107 S Grant Street',
                'owner_last_name': 'LLC',
                'property_street': '107 S Grant Street',
                'normalized_street': dedup_street_key('107 S Grant Street'),
            },
            {
                'id': 2,
                'owner_user_id': 'test-dedup-user',
                'owner_first_name': '107 S Grant Street',
                'owner_last_name': 'LLC',
                'property_street': '107 S Grant St',
                'normalized_street': dedup_street_key('107 S Grant St'),
            },
            {
                'id': 3,
                'owner_user_id': 'other-user',
                'owner_first_name': '107 S Grant Street',
                'owner_last_name': 'LLC',
                'property_street': '107 S Grant Street',
                'normalized_street': dedup_street_key('107 S Grant Street'),
            },
        ]

        groups = _find_dedup_merge_groups(rows)

        assert [[row['id'] for row in group] for group in groups] == [[1, 2]]

    def test_groups_whitespace_owner_names_that_match_migration_index(self):
        rows = [
            {
                'id': 1,
                'owner_user_id': 'test-dedup-user',
                'owner_first_name': '   ',
                'owner_last_name': 'LLC',
                'property_street': '107 S Grant Street',
                'normalized_street': dedup_street_key('107 S Grant Street'),
            },
            {
                'id': 2,
                'owner_user_id': 'test-dedup-user',
                'owner_first_name': '\t',
                'owner_last_name': 'LLC',
                'property_street': '107 S Grant St',
                'normalized_street': dedup_street_key('107 S Grant St'),
            },
        ]

        groups = _find_dedup_merge_groups(rows)

        assert [[row['id'] for row in group] for group in groups] == [[1, 2]]

    def test_skips_rows_without_stored_normalized_street(self):
        """Exact-index cleanup must not derive fallback keys for blank index values."""
        key = dedup_street_key('500 W Madison St')
        rows = [
            {
                'id': 10,
                'owner_user_id': 'u1',
                'owner_first_name': 'Ada',
                'owner_last_name': 'Lovelace',
                'property_street': '500 W Madison St',
                'normalized_street': key,
            },
            {
                'id': 11,
                'owner_user_id': 'u1',
                'owner_first_name': 'Ada',
                'owner_last_name': 'Lovelace',
                'property_street': '500 West Madison Street',
                'normalized_street': None,
            },
            {
                'id': 12,
                'owner_user_id': 'u1',
                'owner_first_name': 'Ada',
                'owner_last_name': 'Lovelace',
                'property_street': '500 W Madison',
                'normalized_street': '',
            },
        ]
        assert _find_dedup_merge_groups(rows) == []


class TestF9DedupMigrationGate:
    @integration
    def test_f9_blocked_without_merge_then_passes_after_dedup(self, dedup_gate_db):
        db_url = dedup_gate_db
        engine = sa.create_engine(db_url)

        with engine.connect() as conn:
            report = build_report(conn)
            assert report.street_duplicate_clusters >= 1
            assert report.f9_pending is True

        fail_upgrade = _run_flask_db(db_url, F9_REVISION)
        assert fail_upgrade.returncode != 0
        assert 'duplicate owner+street clusters remain' in (
            f'{fail_upgrade.stdout}\n{fail_upgrade.stderr}'.lower()
        )

        merge = _run_merge(db_url)
        assert merge.returncode == 0, merge.stderr or merge.stdout

        with engine.connect() as conn:
            report = build_report(conn)
            assert report.street_duplicate_clusters == 0

        ok_upgrade = _run_flask_db(db_url, F9_REVISION)
        assert ok_upgrade.returncode == 0, ok_upgrade.stderr or ok_upgrade.stdout

        with engine.connect() as conn:
            report = build_report(conn)
            assert report.current_revision == F9_REVISION

        engine.dispose()
