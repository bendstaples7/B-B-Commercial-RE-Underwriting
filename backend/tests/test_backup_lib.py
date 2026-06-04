"""
test_backup_lib.py — Example-based unit tests for backup_lib.py

Tests specific, concrete examples to verify exact behaviour of each helper
function. Complements the property-based tests in test_backup_properties.py.

Requirements: 1.2, 1.3, 1.4, 3.2, 3.4, 3.6, 4.3, 7.1, 7.4, 8.2, 8.3, 9.2
"""

import os
import sys

# Ensure backup_lib is importable from the backend directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone

from backup_lib import (
    generate_backup_filename,
    parse_backup_filename,
    filter_by_retention,
    compare_checksums,
    lookup_manifest_entry,
    generate_remote_path,
    retry_controller,
    format_alert_message,
    aggregate_daily_summary,
    is_backup_stale,
    dispatch_transfer_method,
    serialize_manifest_entry,
)


# ---------------------------------------------------------------------------
# 1. generate_backup_filename — fixed timestamp
# ---------------------------------------------------------------------------

class TestGenerateBackupFilename:
    """Requirement 1.2 — filename format is deterministic given a fixed timestamp."""

    FIXED_TS = datetime(2025, 7, 15, 2, 0, 1, tzinfo=timezone.utc)

    def test_scheduled_type(self):
        result = generate_backup_filename(self.FIXED_TS, "scheduled")
        assert result == "backup_2025-07-15_02-00-01.dump"

    def test_predeploy_type(self):
        result = generate_backup_filename(self.FIXED_TS, "pre-deploy")
        assert result == "backup_pre-deploy_2025-07-15_02-00-01.dump"


# ---------------------------------------------------------------------------
# 2. parse_backup_filename — malformed filenames raise ValueError
# ---------------------------------------------------------------------------

class TestParseBackupFilenameErrors:
    """Requirement 1.2 — parser rejects malformed filenames."""

    @pytest.mark.parametrize("bad_filename", [
        "2025-07-15_02-00-01.dump",           # missing "backup_" prefix
        "backup_2025:07:15_02:00:01.dump",    # wrong separator (colon instead of dash)
        "backup_YYYY-MM-DD_HH-MM-SS.dump",    # non-numeric date parts
        "backup_2025-07-15_02-00-01",         # missing .dump extension
        "",                                    # empty string
    ])
    def test_raises_value_error(self, bad_filename):
        with pytest.raises(ValueError):
            parse_backup_filename(bad_filename)


# ---------------------------------------------------------------------------
# 3. filter_by_retention — edge cases
# ---------------------------------------------------------------------------

class TestFilterByRetention:
    """Requirement 1.4 — retention filter handles edge cases correctly."""

    NOW = datetime(2025, 7, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_empty_file_list_returns_empty(self):
        result = filter_by_retention([], self.NOW, retention_days=30)
        assert result == []

    def test_retention_days_zero_returns_empty(self):
        # With retention_days=0, threshold is 0 seconds.
        # All files have age >= 0, so none are kept.
        files = [
            {"filename": "backup_2025-07-15_11-00-00.dump",
             "timestamp": datetime(2025, 7, 15, 11, 0, 0, tzinfo=timezone.utc)},
            {"filename": "backup_2025-07-14_12-00-00.dump",
             "timestamp": datetime(2025, 7, 14, 12, 0, 0, tzinfo=timezone.utc)},
        ]
        result = filter_by_retention(files, self.NOW, retention_days=0)
        assert result == []


# ---------------------------------------------------------------------------
# 4. compare_checksums — single-character difference
# ---------------------------------------------------------------------------

class TestCompareChecksums:
    """Requirement 8.3 — checksums differing by one character return False."""

    def test_single_char_difference_returns_false(self):
        checksum_a = "a" * 63 + "b"
        checksum_b = "a" * 63 + "c"
        assert compare_checksums(checksum_a, checksum_b) is False

    def test_identical_checksums_return_true(self):
        checksum = "a" * 64
        assert compare_checksums(checksum, checksum) is True


# ---------------------------------------------------------------------------
# 5. lookup_manifest_entry — duplicate filenames and empty manifest
# ---------------------------------------------------------------------------

class TestLookupManifestEntry:
    """Requirement 8.2 — lookup returns first match; empty manifest returns None."""

    def _make_line(self, filename: str, sha256: str) -> str:
        entry = {
            "filename": filename,
            "timestamp": "2025-07-15T02:00:01Z",
            "size_bytes": 1024,
            "sha256": sha256,
            "integrity": "valid",
            "type": "scheduled",
            "remote_transferred": True,
            "remote_path": "backups/2025/07/15/" + filename,
        }
        return serialize_manifest_entry(entry)

    def test_duplicate_filenames_returns_first_match(self):
        filename = "backup_2025-07-15_02-00-01.dump"
        line1 = self._make_line(filename, "aaa" + "0" * 61)
        line2 = self._make_line(filename, "bbb" + "0" * 61)
        result = lookup_manifest_entry([line1, line2], filename)
        assert result is not None
        assert result["sha256"] == "aaa" + "0" * 61  # first entry's sha256

    def test_empty_manifest_returns_none(self):
        result = lookup_manifest_entry([], "backup_2025-07-15_02-00-01.dump")
        assert result is None


# ---------------------------------------------------------------------------
# 6. generate_remote_path — midnight UTC timestamp
# ---------------------------------------------------------------------------

class TestGenerateRemotePath:
    """Requirement 3.6 — remote path follows YYYY/MM/DD structure."""

    def test_midnight_utc_timestamp(self):
        ts = datetime(2025, 7, 15, 0, 0, 0, tzinfo=timezone.utc)
        filename = "backup_2025-07-15_00-00-00.dump"
        result = generate_remote_path("backups", ts, filename)
        assert result == "backups/2025/07/15/backup_2025-07-15_00-00-00.dump"


# ---------------------------------------------------------------------------
# 7. retry_controller — all-failing and immediate-success cases
# ---------------------------------------------------------------------------

class TestRetryController:
    """Requirement 3.4 — retry controller exhausts attempts or stops on success."""

    def test_all_failing_returns_false_with_max_retries(self):
        success, attempts = retry_controller(lambda: False, max_retries=3)
        assert success is False
        assert attempts == 3

    def test_success_on_first_attempt(self):
        success, attempts = retry_controller(lambda: True, max_retries=3)
        assert success is True
        assert attempts == 1


# ---------------------------------------------------------------------------
# 8. format_alert_message — credential safety
# ---------------------------------------------------------------------------

class TestFormatAlertMessage:
    """Requirement 9.2 — credential values must not appear in alert output."""

    def test_credential_not_in_output(self):
        ts = datetime(2025, 7, 15, 2, 0, 1, tzinfo=timezone.utc)
        credential = "supersecretkey123"
        message = format_alert_message(
            backup_type="scheduled",
            timestamp=ts,
            reason="pg_dump exited with code 1",
            credentials=[credential],
        )
        assert credential not in message

    def test_message_contains_required_fields(self):
        ts = datetime(2025, 7, 15, 2, 0, 1, tzinfo=timezone.utc)
        message = format_alert_message(
            backup_type="scheduled",
            timestamp=ts,
            reason="disk full",
            credentials=[],
        )
        assert "scheduled" in message
        assert "2025-07-15T02:00:01Z" in message
        assert "disk full" in message


# ---------------------------------------------------------------------------
# 9. aggregate_daily_summary — boundary behaviour
# ---------------------------------------------------------------------------

class TestAggregateDailySummary:
    """Requirement 4.3 — window is start-inclusive, end-exclusive."""

    WINDOW_START = datetime(2025, 7, 15, 0, 0, 0, tzinfo=timezone.utc)
    WINDOW_END = datetime(2025, 7, 16, 0, 0, 0, tzinfo=timezone.utc)

    def _make_line(self, ts: datetime, integrity: str) -> str:
        entry = {
            "filename": f"backup_{ts.strftime('%Y-%m-%d_%H-%M-%S')}.dump",
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "size_bytes": 512,
            "sha256": "a" * 64,
            "integrity": integrity,
            "type": "scheduled",
            "remote_transferred": True,
            "remote_path": "backups/2025/07/15/backup.dump",
        }
        return serialize_manifest_entry(entry)

    def test_entry_exactly_at_window_start_is_counted(self):
        # Exactly at window_start → inclusive → should be counted
        line = self._make_line(self.WINDOW_START, "valid")
        result = aggregate_daily_summary([line], self.WINDOW_START, self.WINDOW_END)
        assert result["successful"] == 1
        assert result["failed"] == 0

    def test_entry_exactly_at_window_end_is_not_counted(self):
        # Exactly at window_end → exclusive → should NOT be counted
        line = self._make_line(self.WINDOW_END, "valid")
        result = aggregate_daily_summary([line], self.WINDOW_START, self.WINDOW_END)
        assert result["successful"] == 0
        assert result["failed"] == 0


# ---------------------------------------------------------------------------
# 10. is_backup_stale — boundary at exactly 12 hours
# ---------------------------------------------------------------------------

class TestIsBackupStale:
    """Requirement 7.4 — boundary at 43200 seconds is NOT stale."""

    BASE_TS = datetime(2025, 7, 15, 0, 0, 0, tzinfo=timezone.utc)

    def test_exactly_12_hours_is_not_stale(self):
        # 43200 seconds elapsed — boundary, should return False
        from datetime import timedelta
        now = self.BASE_TS + timedelta(seconds=43200)
        assert is_backup_stale(self.BASE_TS, now) is False

    def test_43201_seconds_is_stale(self):
        from datetime import timedelta
        now = self.BASE_TS + timedelta(seconds=43201)
        assert is_backup_stale(self.BASE_TS, now) is True


# ---------------------------------------------------------------------------
# 11. dispatch_transfer_method — invalid inputs raise ValueError
# ---------------------------------------------------------------------------

class TestDispatchTransferMethod:
    """Requirement 3.2 — empty and whitespace-only inputs raise ValueError."""

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            dispatch_transfer_method("")

    def test_whitespace_only_raises_value_error(self):
        with pytest.raises(ValueError):
            dispatch_transfer_method("   ")

    def test_valid_methods_do_not_raise(self):
        assert dispatch_transfer_method("rclone") == "rclone"
        assert dispatch_transfer_method("s3") == "s3"
        assert dispatch_transfer_method("rsync") == "rsync"


# ---------------------------------------------------------------------------
# 12. parse_manifest_entry — non-object JSON raises ValueError
# ---------------------------------------------------------------------------

class TestParseManifestEntry:
    """Regression tests for parse_manifest_entry validation."""

    def test_non_object_json_string_raises_value_error(self):
        from backup_lib import parse_manifest_entry
        with pytest.raises(ValueError):
            parse_manifest_entry('"just a string"')

    def test_non_object_json_array_raises_value_error(self):
        from backup_lib import parse_manifest_entry
        with pytest.raises(ValueError):
            parse_manifest_entry('[1, 2, 3]')

    def test_non_object_json_number_raises_value_error(self):
        from backup_lib import parse_manifest_entry
        with pytest.raises(ValueError):
            parse_manifest_entry('42')


# ---------------------------------------------------------------------------
# 13. filter_by_retention — negative retention_days raises ValueError
# ---------------------------------------------------------------------------

class TestFilterByRetentionValidation:
    """Regression tests for filter_by_retention input validation."""

    NOW = datetime(2025, 7, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_negative_retention_days_raises_value_error(self):
        with pytest.raises(ValueError, match="non-negative"):
            filter_by_retention([], self.NOW, retention_days=-1)

    def test_negative_retention_days_minus_100_raises_value_error(self):
        with pytest.raises(ValueError):
            filter_by_retention([], self.NOW, retention_days=-100)
