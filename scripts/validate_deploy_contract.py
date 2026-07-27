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
    "/usr/local/sbin/apply-memory-guard-units",
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
    REPO_ROOT / "scripts" / "vps-setup" / "apply-memory-guard-units.sh",
    REPO_ROOT / "scripts" / "vps-setup" / "11-sudoers-deploy.sh",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_hash_comments(text: str) -> str:
    """Strip shell/Nginx comments while preserving quoted # characters."""
    stripped_lines: list[str] = []
    for line in text.splitlines():
        in_single = False
        in_double = False
        escaped = False
        keep: list[str] = []
        for char in line:
            if escaped:
                keep.append(char)
                escaped = False
                continue
            if char == "\\":
                keep.append(char)
                escaped = True
                continue
            if char == "'" and not in_double:
                in_single = not in_single
                keep.append(char)
                continue
            if char == '"' and not in_single:
                in_double = not in_double
                keep.append(char)
                continue
            if char == "#" and not in_single and not in_double:
                break
            keep.append(char)
        stripped_lines.append("".join(keep))
    return "\n".join(stripped_lines)


def _extract_heredoc(text: str, marker: str) -> str:
    match = re.search(
        rf"<<\s*{re.escape(marker)}\n(?P<body>[\s\S]*?)\n{re.escape(marker)}\s*$",
        text,
        flags=re.MULTILINE,
    )
    return match.group("body") if match else text


def _nginx_location_block(config_text: str, location: str) -> str | None:
    match = re.search(
        rf"\blocation\s+{re.escape(location)}\s*\{{",
        config_text,
    )
    if not match:
        return None

    start = match.end() - 1
    depth = 0
    for idx in range(start, len(config_text)):
        char = config_text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return config_text[start : idx + 1]
    return None


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
            "run-vps-readiness-check.sh must exit 2 when celery/beat ensure fails "
            "(soft for CI smoke, hard for Deploy)"
        )
    if "ensure_rc" not in readiness or "exit 1" not in readiness:
        errors.append(
            "run-vps-readiness-check.sh must exit 1 on redis ensure failure (return 3)"
        )
    if "return 3" not in checks_text:
        errors.append(
            "ensure_async_stack_services must return 3 when redis-server is inactive"
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
    for needle, label in (
        ("--max-tasks-per-child=50", "max-tasks-per-child"),
        ("--max-memory-per-child=400000", "max-memory-per-child"),
        ("MemoryMax=900M", "MemoryMax"),
        ("MemoryHigh=700M", "MemoryHigh"),
        ("OOMScoreAdjust=500", "OOMScoreAdjust on celery worker"),
    ):
        if needle not in unit_text:
            errors.append(
                f"09b-celery-service.sh must include {label} ({needle}) "
                "to prevent Celery OOM thrash"
            )
    gunicorn_unit = _read(REPO_ROOT / "scripts" / "vps-setup" / "09-gunicorn-service.sh")
    if "OOMScoreAdjust=-500" not in gunicorn_unit:
        errors.append(
            "09-gunicorn-service.sh must set OOMScoreAdjust=-500 "
            "(prefer API over Celery under host OOM)"
        )
    nginx_text = _read(REPO_ROOT / "scripts" / "vps-setup" / "11-nginx-config.sh")
    nginx_config = _strip_hash_comments(_extract_heredoc(nginx_text, "NGINX_CONF"))
    assets_block = _nginx_location_block(nginx_config, "/assets/")
    if not assets_block or not all(
        token in assets_block
        for token in ("Cache-Control", "max-age=31536000", "immutable")
    ):
        errors.append(
            "11-nginx-config.sh must long-cache hashed /assets/ "
            "(Cache-Control max-age=31536000, immutable)"
        )
    spa_block = _nginx_location_block(nginx_config, "/")
    if not (spa_block and "Cache-Control" in spa_block and "no-cache" in spa_block):
        errors.append(
            "11-nginx-config.sh must set Cache-Control no-cache on location / (SPA index.html)"
        )
    spa_boot = REPO_ROOT / "scripts" / "spa-boot-check.mjs"
    if not spa_boot.exists():
        errors.append("Missing expected script: scripts/spa-boot-check.mjs")
    asset_assert = REPO_ROOT / "scripts" / "assert_frontend_dist_assets.py"
    if not asset_assert.exists():
        errors.append("Missing expected script: scripts/assert_frontend_dist_assets.py")
    else:
        asset_assert_text = _read(asset_assert)
        if "check_spa_html_contract" not in asset_assert_text:
            errors.append(
                "assert_frontend_dist_assets.py must call check_spa_html_contract "
                "(React must not ship as standalone react-*.js)"
            )
    live_spa = REPO_ROOT / "scripts" / "assert_live_spa_contract.py"
    if not live_spa.exists():
        errors.append("Missing expected script: scripts/assert_live_spa_contract.py")
    drift = REPO_ROOT / "scripts" / "check_main_prod_drift.py"
    if not drift.exists():
        errors.append("Missing expected script: scripts/check_main_prod_drift.py")
    spa_contract_mod = REPO_ROOT / "scripts" / "spa_html_contract.py"
    if not spa_contract_mod.exists():
        errors.append("Missing expected script: scripts/spa_html_contract.py")
    index_html_path = REPO_ROOT / "frontend" / "index.html"
    if not index_html_path.exists():
        errors.append("Missing expected file: frontend/index.html")
    else:
        index_html = _read(index_html_path)
        if "spa-boot-failure" not in index_html:
            errors.append(
                "frontend/index.html must include spa-boot-failure watchdog"
            )
    vite_cfg_path = REPO_ROOT / "frontend" / "vite.config.ts"
    if not vite_cfg_path.exists():
        errors.append("Missing expected file: frontend/vite.config.ts")
    else:
        vite_cfg = _read(vite_cfg_path)
        react_chunk = None
        for branch in re.finditer(
            r"if\s*\(\s*(?P<condition>[\s\S]{0,700}?)\s*\)\s*\{\s*"
            r"return\s+['\"](?P<chunk>[\w-]+)['\"]",
            vite_cfg,
        ):
            condition = branch.group("condition")
            if all(
                token in condition
                for token in (
                    "node_modules/react-dom",
                    "node_modules/react/",
                    "node_modules/react-router",
                    "node_modules/scheduler",
                )
            ):
                react_chunk = branch.group("chunk")
                break
        if react_chunk != "vendor":
            errors.append(
                "vite.config.ts must route react/react-dom/scheduler/react-router into 'vendor' "
                "(causes createContext on undefined React)"
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
        if "maybe_soft_restart_for_memory" not in liveness_text:
            errors.append(
                "celery-liveness-check.sh must soft-restart Celery on RSS / "
                "MemAvailable pressure (maybe_soft_restart_for_memory)"
            )
        if "CELERY_SOFT_RSS_MIB" not in liveness_text:
            errors.append(
                "celery-liveness-check.sh must define CELERY_SOFT_RSS_MIB threshold"
            )
        if "HOST_MIN_AVAILABLE_MIB" not in liveness_text:
            errors.append(
                "celery-liveness-check.sh must define HOST_MIN_AVAILABLE_MIB threshold"
            )
        if "maybe_soft_alert" not in liveness_text or "SOFT_ALERT_STATE" not in liveness_text:
            errors.append(
                "celery-liveness-check.sh must use a separate soft-restart alert "
                "cooldown (maybe_soft_alert / SOFT_ALERT_STATE) from hard-down alerts"
            )
    if "apply-memory-guard-units" not in deploy_text:
        errors.append(
            "deploy.sh must call apply-memory-guard-units so MemoryMax cannot drift"
        )
    apply_script = REPO_ROOT / "scripts" / "vps-setup" / "apply-memory-guard-units.sh"
    if not apply_script.exists():
        errors.append("Missing expected script: scripts/vps-setup/apply-memory-guard-units.sh")
    else:
        apply_text = _read(apply_script)
        if "MemoryMax=900M" not in apply_text:
            errors.append(
                "apply-memory-guard-units.sh must inline MemoryMax=900M "
                "(must not shell out to checkout 09b)"
            )
        if "MemoryHigh=700M" not in apply_text:
            errors.append(
                "apply-memory-guard-units.sh must inline MemoryHigh=700M"
            )
        if re.search(r"(?:bash|source)\s+[^\n]*09b-celery-service\.sh", apply_text):
            errors.append(
                "apply-memory-guard-units.sh must not execute checkout "
                "09b-celery-service.sh as root (inline unit rewrite only)"
            )
    ops_alert = REPO_ROOT / "scripts" / "ops-alert.sh"
    if not ops_alert.exists():
        errors.append("Missing expected script: scripts/ops-alert.sh")
    else:
        ops_text = _read(ops_alert)
        if "json.dumps" not in ops_text:
            errors.append("ops-alert.sh must JSON-encode webhook payloads")
        if "--subject" in ops_text and re.search(r"msmtp[^\n]*--subject", ops_text):
            errors.append(
                "ops-alert.sh must not pass unsupported msmtp --subject; "
                "use an RFC Subject header on stdin"
            )
        if "Subject:" not in ops_text:
            errors.append("ops-alert.sh must send email with a Subject: header on stdin")
        if "--fail" not in ops_text:
            errors.append(
                "ops-alert.sh webhook curl must use --fail so HTTP errors are logged"
            )
    install_cron = _read(REPO_ROOT / "scripts" / "install-backup-cron.sh")
    if "celery-liveness-check.sh" not in install_cron:
        errors.append(
            "install-backup-cron.sh must install celery-liveness-check.sh cron"
        )

    # 6c. Ops health soft-fails only async ensure (exit 2), not hard infra failures
    ops_health_yml = _read(REPO_ROOT / ".github" / "workflows" / "ops-health.yml")
    if "SOFT_ASYNC_ENSURE_FAILURE" not in ops_health_yml:
        errors.append(
            "ops-health.yml must set SOFT_ASYNC_ENSURE_FAILURE=1 "
            "(async ensure exit 2 must not fail ops hard for celery alone)"
        )
    if "assert_live_spa_contract.py" not in ops_health_yml:
        errors.append(
            "ops-health.yml canary must run scripts/assert_live_spa_contract.py "
            "(live HTML SPA contract)"
        )
    if "check_main_prod_drift.py" not in ops_health_yml:
        errors.append(
            "ops-health.yml canary must run scripts/check_main_prod_drift.py "
            "(main↔prod SHA drift alarm)"
        )
    ci_yml = _read(REPO_ROOT / ".github" / "workflows" / "ci.yml")
    if "vps-smoke-test" in ci_yml:
        errors.append(
            "ci.yml (App CI) must not include vps-smoke-test — ops checks belong in ops-health.yml"
        )
    if not ci_yml.lstrip().startswith("name: App CI"):
        errors.append('ci.yml workflow name must be "App CI" (Deploy listens by name)')
    ci_ensure = _read(REPO_ROOT / "scripts" / "ci-ensure-vps-readiness.sh")
    if "SOFT_ASYNC_ENSURE_FAILURE" not in ci_ensure or "READINESS_CODE" not in ci_ensure:
        errors.append(
            "ci-ensure-vps-readiness.sh must soft-handle readiness exit 2 when "
            "SOFT_ASYNC_ENSURE_FAILURE=1"
        )
    deploy_yml = _read(REPO_ROOT / ".github" / "workflows" / "deploy.yml")
    if 'workflows: ["App CI"]' not in deploy_yml:
        errors.append(
            'deploy.yml must listen to workflow_run workflows: ["App CI"] '
            "(ops-health must never gate Deploy)"
        )
    if "assert_live_spa_contract.py" not in deploy_yml:
        errors.append(
            "deploy.yml must run scripts/assert_live_spa_contract.py after post-deploy health"
        )
    else:
        spa_call_idx = deploy_yml.find("assert_live_spa_contract.py")
        post_health_idx = deploy_yml.find("Post-deploy health check")
        if post_health_idx == -1 or spa_call_idx < post_health_idx:
            errors.append(
                "deploy.yml must run scripts/assert_live_spa_contract.py after the "
                "post-deploy health check step"
            )
        if "SPA HTML contract failure" not in deploy_yml:
            errors.append(
                "deploy.yml must roll back on SPA HTML contract failure"
            )
    if "post-deploy-rollback.sh" not in deploy_yml:
        errors.append(
            "deploy.yml must invoke post-deploy-rollback.sh on post-deploy health failure"
        )
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
