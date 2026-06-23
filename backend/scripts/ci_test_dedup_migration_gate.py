"""CI regression: f9 dedup migration fails without merge, succeeds after dedup.

Run from backend/ against a fresh PostgreSQL database:
    DATABASE_URL=postgresql://... python scripts/ci_test_dedup_migration_gate.py
"""
from __future__ import annotations

import os
import subprocess
import sys

import sqlalchemy as sa

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.lead_merge_utils import dedup_street_key  # noqa: E402
from scripts.preflight_dedup_migration import (  # noqa: E402
    F8_REVISION,
    F9_REVISION,
    build_report,
)

TEST_USER_ID = 'ci-dedup-gate-user'
TEST_EMAIL = 'ci-dedup-gate@example.com'


def _database_url() -> str:
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is not set')
    return url.replace('postgresql+psycopg2://', 'postgresql://')


def _migration_env() -> dict[str, str]:
    env = os.environ.copy()
    env['FLASK_APP'] = 'run.py'
    env['FLASK_ENV'] = 'testing'
    env['FLASK_DB_COMMAND'] = '1'
    env['KIRO_MIGRATION'] = '1'
    env.setdefault('SECRET_KEY', 'ci-test-secret-key')
    env.setdefault('JWT_SECRET_KEY', 'ci-test-jwt-secret')
    env.setdefault('REDIS_URL', 'redis://localhost:6379/0')
    env.setdefault('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    return env


def _run_flask_db(revision: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, '-m', 'flask', 'db', 'upgrade']
    if revision:
        cmd.append(revision)
    return subprocess.run(
        cmd,
        cwd=_BACKEND_DIR,
        env=_migration_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )


def _run_preflight(*args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, 'scripts/preflight_dedup_migration.py', *args]
    return subprocess.run(
        cmd,
        cwd=_BACKEND_DIR,
        env=_migration_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_merge() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, 'scripts/merge_duplicate_leads.py', '--mode', 'dedup'],
        cwd=_BACKEND_DIR,
        env=_migration_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )


def _seed_duplicate_leads(conn: sa.Connection) -> None:
    conn.execute(sa.text("""
        INSERT INTO users (
            user_id, email, email_lower, password_hash, display_name,
            is_active, is_admin, password_set
        ) VALUES (
            :user_id, :email, :email_lower, 'hash', 'CI Dedup Gate',
            true, false, false
        )
        ON CONFLICT (user_id) DO NOTHING
    """), {
        'user_id': TEST_USER_ID,
        'email': TEST_EMAIL,
        'email_lower': TEST_EMAIL.lower(),
    })

    streets = [
        '107 S Grant Street',
        '107 S Grant St',
        '107 South Grant',
    ]
    for street in streets:
        street_key = dedup_street_key(street)
        conn.execute(sa.text("""
            INSERT INTO leads (
                property_street, normalized_street,
                owner_first_name, owner_last_name, owner_user_id
            ) VALUES (
                :street, :normalized_street,
                '107 S Grant Street', 'LLC', :owner_user_id
            )
        """), {
            'street': street,
            'normalized_street': street_key,
            'owner_user_id': TEST_USER_ID,
        })
    conn.commit()


def main() -> None:
    db_url = _database_url()
    engine = sa.create_engine(db_url)

    print('=== Dedup migration gate: upgrade to f8 ===')
    result = _run_flask_db(F8_REVISION)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f'flask db upgrade {F8_REVISION} failed')

    with engine.connect() as conn:
        _seed_duplicate_leads(conn)

    print('=== Dedup migration gate: preflight should fail ===')
    preflight = _run_preflight('--verify')
    if preflight.returncode == 0:
        print(preflight.stdout)
        print(preflight.stderr, file=sys.stderr)
        raise SystemExit('Expected preflight --verify to fail with duplicate seed data')

    print('=== Dedup migration gate: f9 upgrade should fail without merge ===')
    fail_upgrade = _run_flask_db(F9_REVISION)
    if fail_upgrade.returncode == 0:
        print(fail_upgrade.stdout)
        print(fail_upgrade.stderr, file=sys.stderr)
        raise SystemExit('Expected flask db upgrade f9 to fail with duplicate seed data')
    combined = f'{fail_upgrade.stdout}\n{fail_upgrade.stderr}'
    if 'duplicate owner+street clusters remain' not in combined.lower():
        print(combined, file=sys.stderr)
        raise SystemExit('f9 failure did not mention duplicate owner+street clusters')

    print('=== Dedup migration gate: merge duplicates ===')
    merge = _run_merge()
    if merge.returncode != 0:
        print(merge.stdout)
        print(merge.stderr, file=sys.stderr)
        raise SystemExit('merge_duplicate_leads --mode dedup failed')
    print(merge.stdout.strip() or 'merge complete')

    print('=== Dedup migration gate: preflight should pass ===')
    preflight_ok = _run_preflight('--verify')
    if preflight_ok.returncode != 0:
        print(preflight_ok.stdout)
        print(preflight_ok.stderr, file=sys.stderr)
        raise SystemExit('preflight --verify failed after dedup merge')

    print('=== Dedup migration gate: f9 upgrade should succeed ===')
    ok_upgrade = _run_flask_db(F9_REVISION)
    if ok_upgrade.returncode != 0:
        print(ok_upgrade.stdout)
        print(ok_upgrade.stderr, file=sys.stderr)
        raise SystemExit('flask db upgrade f9 failed after dedup merge')

    with engine.connect() as conn:
        report = build_report(conn)
        if report.current_revision != F9_REVISION:
            raise SystemExit(
                f'Expected revision {F9_REVISION}, got {report.current_revision}'
            )
        if report.street_duplicate_clusters:
            raise SystemExit('Duplicate clusters remain after successful f9 upgrade')

    print('=== Dedup migration gate regression passed ===')


if __name__ == '__main__':
    main()
