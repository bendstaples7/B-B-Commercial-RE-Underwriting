"""Tests for scripts/backup_health_check.py"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HC_PATH = _ROOT / "scripts" / "backup_health_check.py"


def _load_health_check():
    spec = importlib.util.spec_from_file_location("backup_health_check", _HC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


hc = _load_health_check()


def test_parse_backup_conf_reads_quoted_values(tmp_path: Path):
    conf = tmp_path / "backup.conf"
    conf.write_text(
        'REMOTE_METHOD="rclone"\nBACKUP_DIR="/home/deploy/backups"\n',
        encoding="utf-8",
    )
    parsed = hc.parse_backup_conf(conf)
    assert parsed["REMOTE_METHOD"] == "rclone"
    assert parsed["BACKUP_DIR"] == "/home/deploy/backups"


def test_last_valid_manifest_entry_returns_latest_valid(tmp_path: Path):
    manifest = tmp_path / "backup_manifest.log"
    entries = [
        {"filename": "a.dump", "integrity": "invalid", "timestamp": "2026-06-01T00:00:00Z"},
        {"filename": "b.dump", "integrity": "valid", "timestamp": "2026-06-02T00:00:00Z"},
        {"filename": "c.dump", "integrity": "valid", "timestamp": "2026-06-03T00:00:00Z"},
    ]
    manifest.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    last = hc.last_valid_manifest_entry(manifest)
    assert last is not None
    assert last["filename"] == "c.dump"


def test_cron_missing_entries_detects_gaps():
    crontab = "0 2 * * * /home/deploy/backup.sh"
    missing = hc.cron_missing_entries(crontab)
    assert "weekly pg-basebackup.sh" in missing
    assert "daily-summary.sh" in missing
    assert "celery-liveness-check.sh" not in missing


def test_cron_missing_liveness_warn_only():
    assert hc.cron_missing_liveness("0 2 * * * /home/deploy/backup.sh") is True
    assert (
        hc.cron_missing_liveness("*/5 * * * * /home/deploy/celery-liveness-check.sh")
        is False
    )


def test_cron_missing_entries_ok_when_core_present():
    crontab = "\n".join(
        [
            "0 2 * * * /home/deploy/backup.sh",
            "0 1 * * 0 /home/deploy/pg-basebackup.sh",
            "30 0 * * * /home/deploy/daily-summary.sh",
        ]
    )
    assert hc.cron_missing_entries(crontab) == []


def test_estimate_remote_steady_state_under_free_tier():
    steady = hc.estimate_remote_steady_state_gb(57.0)
    assert steady < 10
    # Alias kept for older call sites
    assert hc.estimate_b2_steady_state_gb(57.0) == steady


def test_run_checks_skips_remote_when_not_configured(tmp_path: Path, monkeypatch):
    conf = tmp_path / "backup.conf"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    conf.write_text(
        f'BACKUP_DIR="{backup_dir.as_posix()}"\nREMOTE_METHOD=""\n',
        encoding="utf-8",
    )
    manifest = backup_dir / "backup_manifest.log"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest.write_text(
        json.dumps(
            {
                "filename": "backup_test.dump",
                "timestamp": now,
                "integrity": "valid",
                "remote_transferred": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        hc,
        "read_crontab",
        lambda: (
            "/home/deploy/backup.sh\n"
            "/home/deploy/pg-basebackup.sh\n"
            "/home/deploy/daily-summary.sh\n"
            "/home/deploy/celery-liveness-check.sh"
        ),
    )
    errors = hc.run_checks(conf)
    assert errors == []


def test_recent_cloud_transfer_ok_accepts_python_true(tmp_path: Path):
    manifest = tmp_path / "backup_manifest.log"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest.write_text(
        json.dumps(
            {
                "filename": "cloud.dump",
                "timestamp": now,
                "integrity": "valid",
                "remote_transferred": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert hc.recent_cloud_transfer_ok(manifest) is True


def test_last_valid_manifest_entry_skips_invalid_timestamp(tmp_path: Path):
    manifest = tmp_path / "backup_manifest.log"
    entries = [
        {"filename": "bad.dump", "integrity": "valid", "timestamp": "not-a-date"},
        {"filename": "good.dump", "integrity": "valid", "timestamp": "2026-06-03T00:00:00Z"},
    ]
    manifest.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    last = hc.last_valid_manifest_entry(manifest)
    assert last is not None
    assert last["filename"] == "good.dump"
