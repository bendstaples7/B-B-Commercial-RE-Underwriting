"""Tests for scripts/inject-remote-backup.py helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / "scripts" / "inject-remote-backup.py"


def _load():
    spec = importlib.util.spec_from_file_location("inject_remote_backup", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


inj = _load()


def test_build_rclone_targets_b2_only():
    assert inj.build_rclone_targets(b2_bucket="bbreanalyzer") == "b2:bbreanalyzer"


def test_build_rclone_targets_cloudflare_only():
    assert (
        inj.build_rclone_targets(cf_bucket="bb-analyzer-backups")
        == "cloudflare:bb-analyzer-backups"
    )


def test_build_rclone_targets_both():
    assert (
        inj.build_rclone_targets(
            b2_bucket="bbreanalyzer",
            cf_bucket="bb-analyzer-backups",
        )
        == "b2:bbreanalyzer cloudflare:bb-analyzer-backups"
    )


def test_build_rclone_targets_empty():
    assert inj.build_rclone_targets() == ""


def test_normalize_upload_hour_strips_leading_zeros():
    assert inj.normalize_upload_hour("08") == "8"
    assert inj.normalize_upload_hour("10") == "10"
    assert inj.normalize_upload_hour("0") == "0"
    assert inj.normalize_upload_hour("23") == "23"


def test_normalize_upload_hour_rejects_invalid():
    with pytest.raises(ValueError):
        inj.normalize_upload_hour("24")
    with pytest.raises(ValueError):
        inj.normalize_upload_hour("noon")


def test_apply_remote_settings_dual_and_defaults():
    conf = 'REMOTE_METHOD=""\nRCLONE_REMOTE="old"\n'
    updated = inj.apply_remote_settings(
        conf,
        b2_bucket="bbreanalyzer",
        cf_bucket="bb-analyzer-backups",
    )
    assert 'REMOTE_METHOD="rclone"' in updated
    assert 'RCLONE_TARGETS="b2:bbreanalyzer cloudflare:bb-analyzer-backups"' in updated
    assert 'REMOTE_RETENTION_DAYS="14"' in updated
    assert 'REMOTE_UPLOAD_HOUR_UTC="10"' in updated
    assert 'RCLONE_REMOTE="b2"' in updated
    assert 'RCLONE_BUCKET="bbreanalyzer"' in updated


def test_apply_remote_settings_normalizes_padded_hour():
    conf = 'REMOTE_METHOD=""\n'
    updated = inj.apply_remote_settings(
        conf,
        b2_bucket="bbreanalyzer",
        upload_hour="08",
    )
    assert 'REMOTE_UPLOAD_HOUR_UTC="8"' in updated


def test_apply_remote_settings_cloudflare_only_legacy_vars():
    conf = 'REMOTE_METHOD=""\n'
    updated = inj.apply_remote_settings(conf, cf_bucket="bb-analyzer-backups")
    assert 'RCLONE_TARGETS="cloudflare:bb-analyzer-backups"' in updated
    assert 'RCLONE_REMOTE="cloudflare"' in updated
    assert 'RCLONE_BUCKET="bb-analyzer-backups"' in updated
