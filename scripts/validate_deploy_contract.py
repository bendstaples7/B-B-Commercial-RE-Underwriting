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

    # 5. run-vps-readiness-check sources shared module
    readiness = _read(REPO_ROOT / "scripts" / "run-vps-readiness-check.sh")
    if "source" not in readiness or "deploy-async-stack-checks.sh" not in readiness:
        errors.append("run-vps-readiness-check.sh must source deploy-async-stack-checks.sh")

    # 6. deploy.sh uses sudo -n (no bare sudo for systemctl)
    deploy_text = _read(REPO_ROOT / "scripts" / "deploy.sh")
    if re.search(r'(?<!-n )\bsudo systemctl\b', deploy_text):
        errors.append("deploy.sh contains 'sudo systemctl' without -n — use sudo -n")

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
