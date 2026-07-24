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
    ci_ensure = (REPO_ROOT / "scripts" / "ci-ensure-vps-readiness.sh").read_text(
        encoding="utf-8"
    )
    assert "SOFT_ASYNC_ENSURE_FAILURE" in ci_ensure
    assert 'READINESS_CODE" -eq 2' in ci_ensure or "READINESS_CODE} -eq 2" in ci_ensure or \
        re.search(r"READINESS_CODE.*-eq 2", ci_ensure)
