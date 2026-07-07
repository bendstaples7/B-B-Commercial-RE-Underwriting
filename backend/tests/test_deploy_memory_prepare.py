"""CI gate: deploy.sh stops Celery before memory guard and restores on EXIT."""
from pathlib import Path


def test_deploy_sh_stops_celery_before_memory_guard():
    repo_root = Path(__file__).resolve().parents[2]
    deploy_sh = (repo_root / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    stop_idx = deploy_sh.index("stop_celery_for_deploy")
    min_ram_idx = deploy_sh.index("MIN_RAM_KB=153600")
    assert stop_idx < min_ram_idx, "stop_celery_for_deploy must run before MIN_RAM_KB memory guard"
    assert "systemctl stop celery" in deploy_sh


def test_deploy_sh_restores_celery_on_exit_trap():
    repo_root = Path(__file__).resolve().parents[2]
    deploy_sh = (repo_root / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert "trap cleanup_deploy_exit EXIT" in deploy_sh
    assert "restore_celery_if_stopped_for_prep" in deploy_sh
    assert "DEPLOY_ASYNC_STACK_RESTARTED=1" in deploy_sh
