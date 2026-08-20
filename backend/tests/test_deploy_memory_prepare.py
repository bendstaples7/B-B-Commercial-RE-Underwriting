"""CI gate: deploy.sh stops Celery before memory guard and restores on EXIT."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_deploy_sh_stops_celery_before_memory_guard():
    deploy_sh = (REPO_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    stop_idx = deploy_sh.rindex("stop_celery_for_deploy")
    min_ram_idx = deploy_sh.index("MIN_RAM_KB=153600")
    assert stop_idx < min_ram_idx, "stop_celery_for_deploy must run before MIN_RAM_KB memory guard"
    assert deploy_sh.count("stop_celery_for_deploy") >= 2, (
        "stop_celery_for_deploy must be both defined and invoked"
    )
    assert re.search(r"systemctl stop celery([^-]|$)", deploy_sh), (
        "deploy.sh must stop the celery worker unit (not only celery-beat)"
    )


def test_deploy_sh_restores_celery_on_exit_trap():
    deploy_sh = (REPO_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert "trap cleanup_deploy_exit EXIT" in deploy_sh
    assert "restore_celery_if_stopped_for_prep" in deploy_sh
    assert "DEPLOY_ASYNC_STACK_RESTARTED=1" in deploy_sh
    assert "CELERY_DEPLOY_MARKER" in deploy_sh
    assert "_clear_celery_deploy_marker" in deploy_sh
    # EXIT is the single restore path (no redundant TERM/INT/HUP traps).
    assert not re.search(r"trap 'cleanup_deploy_exit; exit \d+' TERM", deploy_sh)


def test_ensure_skips_restart_when_deploy_marker_fresh():
    checks = (REPO_ROOT / "scripts" / "deploy-async-stack-checks.sh").read_text(
        encoding="utf-8"
    )
    assert "celery_deploy_marker_is_fresh" in checks
    assert "stat -c %Y" in checks
    # Marker gate must wrap ensure before _ensure_unit_active celery.
    marker_idx = checks.index("celery_deploy_marker_is_fresh")
    ensure_fn = checks.index("ensure_async_stack_services()")
    celery_restart = checks.index("_ensure_unit_active celery", ensure_fn)
    skip_idx = checks.index("skip restart", ensure_fn)
    assert marker_idx < ensure_fn or "celery_deploy_marker_is_fresh" in checks[ensure_fn:celery_restart]
    assert skip_idx < celery_restart


def test_liveness_uses_shared_marker_helper_and_ops_alert():
    liveness = (REPO_ROOT / "scripts" / "celery-liveness-check.sh").read_text(
        encoding="utf-8"
    )
    assert "celery_deploy_marker_is_fresh" in liveness
    assert "ops-alert.sh" in liveness
    assert "CELERY_DEPLOY_MARKER_MAX_AGE_SECS" in liveness or "celery_deploy_marker_is_fresh" in liveness


def test_readiness_exits_2_on_ensure_failure():
    readiness = (REPO_ROOT / "scripts" / "run-vps-readiness-check.sh").read_text(
        encoding="utf-8"
    )
    assert "exit 2" in readiness
    assert "ensure_rc" in readiness
    assert re.search(r"ensure_rc.*-eq 3", readiness) or 'ensure_rc}" -eq 3' in readiness
    ci_ensure = (REPO_ROOT / "scripts" / "ci-ensure-vps-readiness.sh").read_text(
        encoding="utf-8"
    )
    assert "SOFT_ASYNC_ENSURE_FAILURE" in ci_ensure
    assert re.search(r"READINESS_CODE.*-eq 2", ci_ensure)


def test_ensure_redis_failure_returns_3():
    checks = (REPO_ROOT / "scripts" / "deploy-async-stack-checks.sh").read_text(
        encoding="utf-8"
    )
    assert "return 3" in checks
    assert "redis-server not active" in checks


def test_ops_alert_msmtp_rfc_and_curl_fail():
    ops = (REPO_ROOT / "scripts" / "ops-alert.sh").read_text(encoding="utf-8")
    assert "Subject:" in ops
    assert not re.search(r"msmtp[^\n]*--subject", ops)
    assert "--fail" in ops
    assert "json.dumps" in ops


def test_pg_idle_xact_watchdog_wrapper_is_bounded_and_alerts_failures():
    watchdog = (REPO_ROOT / "scripts" / "pg-idle-xact-watchdog.sh").read_text(
        encoding="utf-8"
    )
    assert "source \"${APP_DIR}/backend/.env\"" not in watchdog
    assert "DATABASE_URL_LINE=\"$(" in watchdog
    assert "grep -E '^[[:space:]]*DATABASE_URL=' \"$ENV_FILE\" | head -1 || true" in watchdog
    assert "unknown argument" in watchdog
    assert "flock -n 9" in watchdog
    assert "timeout --signal=TERM" in watchdog
    assert "source /home/deploy/backup.conf" in watchdog
    assert "OPS_ALERT_DELIVERY_FAILED" in watchdog
    assert "watchdog failed with exit $RC" in watchdog
    assert "Postgres idle-xact watchdog failed" in watchdog


def test_deploy_lock_gate_runs_before_dedup_and_rolls_back():
    deploy_sh = (REPO_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    lock_idx = deploy_sh.index("Pre-migration lock gate")
    dedup_idx = deploy_sh.index("Pre-migration dedup cleanup")
    assert lock_idx < dedup_idx
    lock_section = deploy_sh[lock_idx:dedup_idx]
    assert "rollback 1" in lock_section
    assert "exit 1" not in lock_section
    dedup_section = deploy_sh[dedup_idx:deploy_sh.index("flask db upgrade head")]
    assert "timeout --signal=TERM" in dedup_section
    assert "DEDUP_VERIFY_RC" in dedup_section
    assert "DEDUP_VERIFY_RC\" -gt 1" in dedup_section
    assert "Duplicate clusters detected" in dedup_section


def test_deploy_preserves_checkout_after_partial_migration_apply():
    deploy_sh = (REPO_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert "fail_after_partial_migration_apply" in deploy_sh
    assert "migration_revision_is_committed" in deploy_sh
    assert "SELECT version_num FROM alembic_version" in deploy_sh
    assert "BB_MIGRATE_VERIFY_TIMEOUT_SEC" in deploy_sh
    assert "connect_timeout=5" in deploy_sh
    assert "SET statement_timeout = '5s'" in deploy_sh
    assert "return 2" in deploy_sh
    assert "could not verify whether marker revision committed" in deploy_sh
    assert "Not rolling back checkout because Alembic may have committed a revision" in deploy_sh
    timeout_section = deploy_sh[
        deploy_sh.index("if [ \"$UPGRADE_RC\" -eq 124 ]"):
        deploy_sh.index("echo \"    Migrations applied\"")
    ]
    assert "fail_after_partial_migration_apply" in timeout_section
    assert "maybe_preserve_after_migration_marker" in timeout_section
    assert "rollback 1" in timeout_section


def test_one_shot_heal_scripts_force_production_env():
    for rel in (
        "backend/scripts/heal_working_deprioritize.py",
        "backend/scripts/heal_same_person_owners.py",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "os.environ['FLASK_ENV'] = 'production'" in text
        assert "create_app('production')" in text
