#!/usr/bin/env python3
"""Validate deploy/sudoers contract — run in CI on every PR.

Ensures deploy.sh, deploy-async-stack-checks.sh, migrate-async-stack.sh, and
11-sudoers-deploy.sh stay in sync so deploy does not fail on missing sudo rules.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Canonical passwordless-sudo commands the deploy user must have.
REQUIRED_SUDO_COMMANDS = [
    "/bin/systemctl reload gunicorn",
    "/bin/systemctl stop celery",
    "/bin/systemctl stop celery-beat",
    "/bin/systemctl restart celery",
    "/bin/systemctl restart celery-beat",
    "/bin/systemctl is-active --quiet redis-server",
    "/bin/systemctl is-active --quiet celery",
    "/bin/systemctl is-active --quiet celery-beat",
    "/usr/local/sbin/bootstrap-async-stack",
]

SHELL_SCRIPTS = [
    REPO_ROOT / "scripts" / "deploy.sh",
    REPO_ROOT / "scripts" / "deploy-async-stack-checks.sh",
    REPO_ROOT / "scripts" / "run-vps-readiness-check.sh",
    REPO_ROOT / "scripts" / "ci-ensure-vps-readiness.sh",
    REPO_ROOT / "scripts" / "celery-liveness-check.sh",
    REPO_ROOT / "scripts" / "ops-alert.sh",
    REPO_ROOT / "scripts" / "vps-setup" / "migrate-async-stack.sh",
    REPO_ROOT / "scripts" / "vps-setup" / "bootstrap-async-stack.sh",
    REPO_ROOT / "scripts" / "vps-setup" / "11-sudoers-deploy.sh",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _script_references_command(text: str, cmd: str) -> bool:
    """Match cmd as a whole token (celery-beat must not satisfy celery)."""
    return re.search(re.escape(cmd) + r"(?!\w)", text) is not None


def parse_sudoers_commands() -> set[str]:
    text = _read(REPO_ROOT / "scripts" / "vps-setup" / "11-sudoers-deploy.sh")
    match = re.search(r'SUDOERS_RULE="([^"]+)"', text)
    if not match:
        raise AssertionError("Could not find SUDOERS_RULE in 11-sudoers-deploy.sh")
    rule = match.group(1)
    # After NOPASSWD: comma-separated absolute paths/commands
    _, commands_part = rule.split("NOPASSWD:", 1)
    return {cmd.strip() for cmd in commands_part.split(",") if cmd.strip()}


def _bash_syntax_check_available() -> bool:
    if sys.platform == "win32" or not shutil.which("bash"):
        return False
    probe = subprocess.run(
        ["bash", "-c", "exit 0"],
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


def main() -> int:
    errors: list[str] = []

    # 1. bash -n syntax check (Linux/macOS CI; skip broken Windows/WSL shims)
    if _bash_syntax_check_available():
        for script in SHELL_SCRIPTS:
            if not script.exists():
                errors.append(f"Missing expected script: {script.relative_to(REPO_ROOT)}")
                continue
            result = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                errors.append(
                    f"bash -n failed for {script.relative_to(REPO_ROOT)}: {result.stderr.strip()}"
                )
    else:
        for script in SHELL_SCRIPTS:
            if not script.exists():
                errors.append(f"Missing expected script: {script.relative_to(REPO_ROOT)}")

    # 2. Sudoers contains all required commands
    sudoers_cmds = parse_sudoers_commands()
    for cmd in REQUIRED_SUDO_COMMANDS:
        if cmd not in sudoers_cmds:
            errors.append(f"SUDOERS_RULE missing required command: {cmd}")

    # 3. migrate-async-stack.sh references all required sudo commands
    migrate_text = _read(REPO_ROOT / "scripts" / "vps-setup" / "migrate-async-stack.sh")
    for cmd in REQUIRED_SUDO_COMMANDS:
        if not _script_references_command(migrate_text, cmd):
            errors.append(f"migrate-async-stack.sh missing reference to sudo command: {cmd}")

    # 4. deploy-async-stack-checks covers async commands (gunicorn separate)
    checks_path = REPO_ROOT / "scripts" / "deploy-async-stack-checks.sh"
    checks_text = _read(checks_path)
    for cmd in REQUIRED_SUDO_COMMANDS:
        if not _script_references_command(checks_text, cmd):
            errors.append(f"deploy-async-stack-checks.sh does not reference: {cmd}")

    # 5. run-vps-readiness-check sources shared module and self-heals celery
    readiness = _read(REPO_ROOT / "scripts" / "run-vps-readiness-check.sh")
    if "source" not in readiness or "deploy-async-stack-checks.sh" not in readiness:
        errors.append("run-vps-readiness-check.sh must source deploy-async-stack-checks.sh")
    if "ensure_async_stack_services" not in readiness:
        errors.append(
            "run-vps-readiness-check.sh must call ensure_async_stack_services "
            "(restart inactive celery before failing the gate)"
        )
    if "exit 2" not in readiness:
        errors.append(
            "run-vps-readiness-check.sh must exit 2 when async ensure fails "
            "(soft for CI smoke, hard for Deploy)"
        )
    if "ensure_async_stack_services" not in checks_text:
        errors.append(
            "deploy-async-stack-checks.sh must define ensure_async_stack_services"
        )
    if "celery_deploy_marker_is_fresh" not in checks_text:
        errors.append(
            "deploy-async-stack-checks.sh must define celery_deploy_marker_is_fresh"
        )
    if "celery_deploy_marker_is_fresh" not in checks_text or \
            "skip restart" not in checks_text:
        errors.append(
            "ensure_async_stack_services must skip celery restart while "
            "deploy stop marker is fresh"
        )
    unit_text = _read(REPO_ROOT / "scripts" / "vps-setup" / "09b-celery-service.sh")
    if "Restart=always" not in unit_text:
        errors.append(
            "09b-celery-service.sh must set Restart=always on celery units"
        )
    if "StartLimitBurst=5" not in unit_text:
        errors.append(
            "09b-celery-service.sh must set StartLimitBurst to avoid restart thrash"
        )

    # 6. deploy.sh uses sudo -n (no bare sudo for systemctl) and always restores celery
    deploy_text = _read(REPO_ROOT / "scripts" / "deploy.sh")
    if re.search(r'(?<!-n )\bsudo systemctl\b', deploy_text):
        errors.append("deploy.sh contains 'sudo systemctl' without -n — use sudo -n")
    if "trap cleanup_deploy_exit EXIT" not in deploy_text:
        errors.append("deploy.sh must trap cleanup_deploy_exit on EXIT")
    if "CELERY_DEPLOY_MARKER" not in deploy_text:
        errors.append(
            "deploy.sh must write CELERY_DEPLOY_MARKER so liveness can detect "
            "interrupted deploys that left celery stopped"
        )
    # EXIT trap is enough; avoid redundant signal traps that obscure exit codes.
    if re.search(r"trap 'cleanup_deploy_exit; exit \d+' TERM", deploy_text):
        errors.append(
            "deploy.sh should restore celery via EXIT only (remove TERM/INT/HUP traps)"
        )

    # 6b. Celery liveness cron + shared ops-alert + installer
    liveness = REPO_ROOT / "scripts" / "celery-liveness-check.sh"
    if not liveness.exists():
        errors.append("Missing expected script: scripts/celery-liveness-check.sh")
    else:
        liveness_text = _read(liveness)
        if "ensure_async_stack_services" not in liveness_text:
            errors.append(
                "celery-liveness-check.sh must call ensure_async_stack_services"
            )
        if "celery_deploy_marker_is_fresh" not in liveness_text:
            errors.append(
                "celery-liveness-check.sh must honor deploy marker via "
                "celery_deploy_marker_is_fresh"
            )
        if "ops-alert.sh" not in liveness_text:
            errors.append("celery-liveness-check.sh must source ops-alert.sh")
    ops_alert = REPO_ROOT / "scripts" / "ops-alert.sh"
    if not ops_alert.exists():
        errors.append("Missing expected script: scripts/ops-alert.sh")
    else:
        ops_text = _read(ops_alert)
        if "json.dumps" not in ops_text:
            errors.append("ops-alert.sh must JSON-encode webhook payloads")
    install_cron = _read(REPO_ROOT / "scripts" / "install-backup-cron.sh")
    if "celery-liveness-check.sh" not in install_cron:
        errors.append(
            "install-backup-cron.sh must install celery-liveness-check.sh cron"
        )

    # 6c. CI smoke soft-fails only async ensure (exit 2), not hard infra failures
    ci_yml = _read(REPO_ROOT / ".github" / "workflows" / "ci.yml")
    if "SOFT_ASYNC_ENSURE_FAILURE" not in ci_yml:
        errors.append(
            "ci.yml vps-smoke must set SOFT_ASYNC_ENSURE_FAILURE=1 "
            "(async ensure exit 2 must not block Deploy)"
        )
    ci_ensure = _read(REPO_ROOT / "scripts" / "ci-ensure-vps-readiness.sh")
    if "SOFT_ASYNC_ENSURE_FAILURE" not in ci_ensure or "READINESS_CODE" not in ci_ensure:
        errors.append(
            "ci-ensure-vps-readiness.sh must soft-handle readiness exit 2 when "
            "SOFT_ASYNC_ENSURE_FAILURE=1"
        )
    deploy_yml = _read(REPO_ROOT / ".github" / "workflows" / "deploy.yml")
    if "celery-liveness-check.sh" not in deploy_yml:
        errors.append(
            "deploy.yml must copy celery-liveness-check.sh to the VPS"
        )
    if "ops-alert.sh" not in deploy_yml:
        errors.append("deploy.yml must copy ops-alert.sh to the VPS")

    # 7. post_deploy_sync dispatches async (must not block SSH on sync runner)
    post_deploy_path = REPO_ROOT / "backend" / "scripts" / "post_deploy_sync.py"
    if post_deploy_path.exists():
        post_deploy_text = _read(post_deploy_path)
        if "run_post_import_pipeline_sync" in post_deploy_text:
            errors.append(
                "post_deploy_sync.py must not call run_post_import_pipeline_sync "
                "(blocks deploy SSH — use dispatch_tiered_post_deploy_sync)"
            )
        if "dispatch_tiered_post_deploy_sync" not in post_deploy_text:
            errors.append(
                "post_deploy_sync.py must dispatch async via hubspot_pipeline_runner "
                "(dispatch_tiered_post_deploy_sync)"
            )
    else:
        errors.append(
            "Missing expected script: backend/scripts/post_deploy_sync.py"
        )
    if "Post-deploy HubSpot sync dispatched" not in deploy_text:
        errors.append(
            "deploy.sh step 8 must log non-blocking dispatch "
            "(Post-deploy HubSpot sync dispatched)"
        )
    if "backfill_mail_queued_task_cleanup.py" not in deploy_text:
        errors.append(
            "deploy.sh must run backfill_mail_queued_task_cleanup.py after migrations"
        )

    if errors:
        print("Deploy contract validation FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Deploy contract validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
