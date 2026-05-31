"""
Property-based tests for backup_lib.py using Hypothesis.

Feature: database-backup-redundancy
Location: backend/tests/test_backup_properties.py

Each test corresponds to one correctness property defined in the design document.
All tests use @settings(max_examples=100).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# Ensure backup_lib is importable from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backup_lib import (
    aggregate_daily_summary,
    compare_checksums,
    dispatch_transfer_method,
    filter_by_retention,
    format_alert_message,
    generate_backup_filename,
    generate_remote_path,
    is_backup_stale,
    lookup_manifest_entry,
    parse_backup_filename,
    parse_manifest_entry,
    retry_controller,
    serialize_manifest_entry,
)


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Valid filename characters: alphanumeric, hyphen, underscore, dot
_FILENAME_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."


@st.composite
def manifest_entry_strategy(draw):
    """Composite strategy that generates a valid manifest entry dict with all 8 fields."""
    filename = draw(
        st.text(
            alphabet=_FILENAME_ALPHABET,
            min_size=1,
            max_size=100,
        )
    )
    # Timestamp as ISO 8601 UTC string (the format used in the manifest)
    dt = draw(st.datetimes(timezones=st.just(timezone.utc)))
    timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    size_bytes = draw(st.integers(min_value=0, max_value=10**12))
    sha256 = draw(st.text(alphabet="0123456789abcdef", min_size=64, max_size=64))
    integrity = draw(st.sampled_from(["valid", "invalid"]))
    backup_type = draw(st.sampled_from(["scheduled", "pre-deploy"]))
    remote_transferred = draw(st.booleans())
    remote_path = draw(st.text(min_size=0, max_size=200))
    return {
        "filename": filename,
        "timestamp": timestamp,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "integrity": integrity,
        "type": backup_type,
        "remote_transferred": remote_transferred,
        "remote_path": remote_path,
    }


@st.composite
def file_entry_strategy(draw):
    """Composite strategy that generates a file entry dict with timestamp (ISO string) and filename."""
    dt = draw(st.datetimes(timezones=st.just(timezone.utc)))
    timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    filename = draw(
        st.text(
            alphabet=_FILENAME_ALPHABET,
            min_size=1,
            max_size=100,
        )
    )
    return {
        "timestamp": timestamp,
        "filename": filename,
    }


# ---------------------------------------------------------------------------
# Property 1: Backup filename generation round-trip
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 1: Backup filename generation is correctly formatted
@given(
    timestamp=st.datetimes(timezones=st.just(timezone.utc)),
    backup_type=st.sampled_from(["scheduled", "pre-deploy"]),
)
@settings(max_examples=100)
def test_filename_generation_round_trip(timestamp, backup_type):
    """Validates: Requirements 1.2, 2.4

    For any valid UTC timestamp and backup type, generate_backup_filename produces
    a filename that parse_backup_filename can recover to the original timestamp
    (truncated to seconds) and type, and the filename ends with .dump.
    """
    filename = generate_backup_filename(timestamp, backup_type)

    # Filename must end with .dump
    assert filename.endswith(".dump"), (
        f"Expected filename to end with '.dump', got: {filename!r}"
    )

    # Round-trip: parse recovers original timestamp (truncated to seconds) and type
    parsed_ts, parsed_type = parse_backup_filename(filename)

    assert parsed_ts == timestamp.replace(microsecond=0), (
        f"Timestamp mismatch: expected {timestamp.replace(microsecond=0)!r}, "
        f"got {parsed_ts!r} from filename {filename!r}"
    )
    assert parsed_type == backup_type, (
        f"Type mismatch: expected {backup_type!r}, got {parsed_type!r} "
        f"from filename {filename!r}"
    )


# ---------------------------------------------------------------------------
# Property 2: Manifest entry round-trip fidelity
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 2: Manifest entry round-trip fidelity
@given(entry=manifest_entry_strategy())
@settings(max_examples=100)
def test_manifest_round_trip(entry):
    """Validates: Requirements 1.3, 4.3

    For any valid manifest entry dict, serializing to a JSON line and parsing
    back produces a dict equal to the original.
    """
    line = serialize_manifest_entry(entry)
    parsed = parse_manifest_entry(line)
    assert parsed == entry, (
        f"Round-trip mismatch.\nOriginal: {entry!r}\nParsed:   {parsed!r}"
    )


# ---------------------------------------------------------------------------
# Property 3: Retention filter correctness
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 3: Retention filter correctness
@given(
    files=st.lists(file_entry_strategy(), max_size=20),
    now=st.datetimes(timezones=st.just(timezone.utc)),
    retention_days=st.integers(min_value=0, max_value=365),
)
@settings(max_examples=100)
def test_retention_filter_correctness(files, now, retention_days):
    """Validates: Requirements 1.4, 6.4

    filter_by_retention returns exactly the files whose age (in seconds) is
    strictly less than retention_days * 86400. All excluded files have age >= threshold.
    """
    threshold_seconds = retention_days * 86400
    kept = filter_by_retention(files, now, retention_days)

    # Use object identity (id) to track which file dicts were kept, since
    # multiple entries may share the same filename.
    kept_ids = {id(f) for f in kept}

    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)

    for f in files:
        # Parse the ISO timestamp string back to a datetime for age computation
        ts_str = f["timestamp"]
        # Normalize 'Z' suffix
        normalized = ts_str[:-1] + "+00:00" if ts_str.endswith("Z") else ts_str
        ts = datetime.fromisoformat(normalized)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_seconds = (now_aware - ts).total_seconds()

        if age_seconds < threshold_seconds:
            assert id(f) in kept_ids, (
                f"File with age {age_seconds:.1f}s < threshold {threshold_seconds}s "
                f"should be kept but was excluded: {f['filename']!r}"
            )
        else:
            assert id(f) not in kept_ids, (
                f"File with age {age_seconds:.1f}s >= threshold {threshold_seconds}s "
                f"should be excluded but was kept: {f['filename']!r}"
            )


# ---------------------------------------------------------------------------
# Property 4: Checksum comparison is symmetric and exact
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 4: Checksum comparison is symmetric and exact
@given(
    s=st.text(alphabet="0123456789abcdefABCDEF", min_size=64, max_size=64),
)
@settings(max_examples=100)
def test_checksum_identity_and_case_insensitive(s):
    """Validates: Requirements 8.3

    compare_checksums(s, s) returns True (identity).
    compare_checksums(s, s.lower()) returns True (case-insensitive).
    compare_checksums(s, s.upper()) returns True (case-insensitive).
    """
    assert compare_checksums(s, s) is True, (
        f"Identity check failed: compare_checksums({s!r}, {s!r}) returned False"
    )
    assert compare_checksums(s, s.lower()) is True, (
        f"Lowercase check failed: compare_checksums({s!r}, {s.lower()!r}) returned False"
    )
    assert compare_checksums(s, s.upper()) is True, (
        f"Uppercase check failed: compare_checksums({s!r}, {s.upper()!r}) returned False"
    )


@given(
    s=st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
    pos=st.integers(min_value=0, max_value=63),
    replacement=st.sampled_from(list("0123456789abcdef")),
)
@settings(max_examples=100)
def test_checksum_mutation_returns_false(s, pos, replacement):
    """Validates: Requirements 8.3

    Any single-character change at any position causes compare_checksums to return False.
    """
    assume(replacement != s[pos].lower())

    mutated = s[:pos] + replacement + s[pos + 1:]
    assert compare_checksums(s, mutated) is False, (
        f"Mutation at pos {pos} ({s[pos]!r} -> {replacement!r}) should return False, "
        f"but compare_checksums({s!r}, {mutated!r}) returned True"
    )


# ---------------------------------------------------------------------------
# Property 5: Manifest lookup returns correct entry
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 5: Manifest lookup returns the correct entry
@given(
    entries=st.lists(manifest_entry_strategy(), min_size=1, max_size=10),
)
@settings(max_examples=100)
def test_manifest_lookup_present_filename(entries):
    """Validates: Requirements 8.2

    For any filename present in entries, lookup_manifest_entry returns an entry
    with that filename.
    """
    lines = [serialize_manifest_entry(e) for e in entries]

    # Pick the first entry's filename as the lookup target
    target_filename = entries[0]["filename"]
    result = lookup_manifest_entry(lines, target_filename)

    assert result is not None, (
        f"lookup_manifest_entry returned None for filename {target_filename!r} "
        f"which is present in the manifest"
    )
    assert result["filename"] == target_filename, (
        f"lookup_manifest_entry returned entry with filename {result['filename']!r}, "
        f"expected {target_filename!r}"
    )


@given(
    entries=st.lists(manifest_entry_strategy(), min_size=1, max_size=10),
    absent_filename=st.text(min_size=1, max_size=50),
)
@settings(max_examples=100)
def test_manifest_lookup_absent_filename(entries, absent_filename):
    """Validates: Requirements 8.2

    For a filename NOT in entries, lookup_manifest_entry returns None.
    """
    assume(absent_filename not in [e["filename"] for e in entries])

    lines = [serialize_manifest_entry(e) for e in entries]
    result = lookup_manifest_entry(lines, absent_filename)

    assert result is None, (
        f"lookup_manifest_entry returned {result!r} for absent filename "
        f"{absent_filename!r}, expected None"
    )


# ---------------------------------------------------------------------------
# Property 6: Remote path generation follows date-structured format
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 6: Remote path generation follows date-structured format
@given(
    prefix=st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="-_/",
        ),
    ),
    timestamp=st.datetimes(timezones=st.just(timezone.utc)),
    # Filenames must not contain '/' so path splitting works correctly
    filename=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(blacklist_characters="/"),
    ),
)
@settings(max_examples=100)
def test_remote_path_date_structured_format(prefix, timestamp, filename):
    """Validates: Requirements 3.6

    generate_remote_path produces a path of the form <prefix>/YYYY/MM/DD/<filename>
    where YYYY, MM, DD match the UTC date components of the timestamp.
    """
    path = generate_remote_path(prefix, timestamp, filename)

    expected_year = timestamp.strftime("%Y")
    expected_month = timestamp.strftime("%m")
    expected_day = timestamp.strftime("%d")
    expected_path = f"{prefix}/{expected_year}/{expected_month}/{expected_day}/{filename}"

    assert path == expected_path, (
        f"Remote path mismatch.\nExpected: {expected_path!r}\nGot:      {path!r}"
    )

    # Verify date components by splitting from the end (prefix may contain slashes)
    parts = path.split("/")
    assert parts[-1] == filename, f"Last path component should be filename, got {parts[-1]!r}"
    assert parts[-2] == expected_day, f"Day component mismatch: expected {expected_day!r}, got {parts[-2]!r}"
    assert parts[-3] == expected_month, f"Month component mismatch: expected {expected_month!r}, got {parts[-3]!r}"
    assert parts[-4] == expected_year, f"Year component mismatch: expected {expected_year!r}, got {parts[-4]!r}"


# ---------------------------------------------------------------------------
# Property 7: Retry logic exhausts exactly N attempts before alerting
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 7: Retry logic exhausts exactly N attempts before alerting
@given(
    outcomes=st.lists(st.booleans(), min_size=1, max_size=5),
    max_retries=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=100)
def test_retry_logic_attempt_count(outcomes, max_retries):
    """Validates: Requirements 3.4

    retry_controller attempts exactly as many times as needed:
    - If any outcome in outcomes[:max_retries] is True: success=True,
      attempts_made = index_of_first_true + 1
    - If no outcome in outcomes[:max_retries] is True: success=False,
      attempts_made = max_retries
    """
    call_count = [0]

    def attempt_fn():
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(outcomes):
            return outcomes[idx]
        return False

    success, attempts_made = retry_controller(attempt_fn, max_retries)

    # Determine expected outcome from the first max_retries outcomes
    relevant = outcomes[:max_retries]
    first_success_idx = next(
        (i for i, v in enumerate(relevant) if v), None
    )

    if first_success_idx is not None:
        # Should succeed at first_success_idx + 1 attempts
        assert success is True, (
            f"Expected success=True (first True at index {first_success_idx}), "
            f"got success={success}, attempts_made={attempts_made}"
        )
        assert attempts_made == first_success_idx + 1, (
            f"Expected attempts_made={first_success_idx + 1}, got {attempts_made}"
        )
    else:
        # All max_retries attempts failed
        assert success is False, (
            f"Expected success=False (no True in first {max_retries} outcomes), "
            f"got success={success}, attempts_made={attempts_made}"
        )
        assert attempts_made == max_retries, (
            f"Expected attempts_made={max_retries}, got {attempts_made}"
        )


# ---------------------------------------------------------------------------
# Property 8: Alert messages always contain required fields
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 8: Alert messages always contain required fields
@given(
    backup_type=st.sampled_from(["scheduled", "pre-deploy"]),
    timestamp=st.datetimes(timezones=st.just(timezone.utc)),
    reason=st.text(min_size=1, max_size=200),
    credentials=st.lists(st.text(min_size=8, max_size=50), max_size=5),
)
@settings(max_examples=100)
def test_alert_message_contains_required_fields(backup_type, timestamp, reason, credentials):
    """Validates: Requirements 7.1, 9.2

    format_alert_message produces a message that:
    - Contains the backup_type string
    - Contains the ISO 8601 UTC timestamp string
    - Contains the reason string
    - Does NOT contain any credential value
    """
    # Avoid false positives: skip cases where a credential appears in backup_type or reason
    assume(not any(cred in backup_type or cred in reason for cred in credentials))

    ts_iso = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    message = format_alert_message(backup_type, timestamp, reason, credentials)

    assert backup_type in message, (
        f"Alert message does not contain backup_type {backup_type!r}.\nMessage: {message!r}"
    )
    assert ts_iso in message, (
        f"Alert message does not contain ISO timestamp {ts_iso!r}.\nMessage: {message!r}"
    )
    assert reason in message, (
        f"Alert message does not contain reason {reason!r}.\nMessage: {message!r}"
    )
    for cred in credentials:
        if cred:
            assert cred not in message, (
                f"Credential value {cred!r} found in alert message.\nMessage: {message!r}"
            )


# ---------------------------------------------------------------------------
# Property 9: Daily summary aggregation is correct over any 24-hour window
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 9: Daily summary aggregation is correct over any 24-hour window
@given(
    entries=st.lists(manifest_entry_strategy(), max_size=20),
    window_start=st.datetimes(timezones=st.just(timezone.utc)),
)
@settings(max_examples=100)
def test_daily_summary_aggregation(entries, window_start):
    """Validates: Requirements 4.4, 7.3

    aggregate_daily_summary counts:
    - successful: entries with integrity="valid" and timestamp in [window_start, window_end)
    - failed: entries with integrity="invalid" and timestamp in [window_start, window_end)
    where window_end = window_start + timedelta(hours=24).
    """
    window_end = window_start + timedelta(hours=24)

    # Build manifest lines from entries using serialize_manifest_entry
    lines = [serialize_manifest_entry(e) for e in entries]

    summary = aggregate_daily_summary(lines, window_start, window_end)

    # Compute expected counts manually
    ws = window_start if window_start.tzinfo is not None else window_start.replace(tzinfo=timezone.utc)
    we = window_end if window_end.tzinfo is not None else window_end.replace(tzinfo=timezone.utc)

    expected_successful = 0
    expected_failed = 0

    for e in entries:
        ts_str = e["timestamp"]
        normalized = ts_str[:-1] + "+00:00" if ts_str.endswith("Z") else ts_str
        ts = datetime.fromisoformat(normalized)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if ws <= ts < we:
            if e["integrity"] == "valid":
                expected_successful += 1
            elif e["integrity"] == "invalid":
                expected_failed += 1

    assert summary["successful"] == expected_successful, (
        f"successful count mismatch: expected {expected_successful}, got {summary['successful']}"
    )
    assert summary["failed"] == expected_failed, (
        f"failed count mismatch: expected {expected_failed}, got {summary['failed']}"
    )


# ---------------------------------------------------------------------------
# Property 10: Stale backup detection uses correct time comparison
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 10: Stale backup detection uses correct time comparison
@given(
    last_ts=st.datetimes(timezones=st.just(timezone.utc)),
    elapsed_seconds=st.integers(min_value=0, max_value=86400),
)
@settings(max_examples=100)
def test_stale_backup_detection(last_ts, elapsed_seconds):
    """Validates: Requirements 7.4

    is_backup_stale(last_ts, now) returns True iff elapsed_seconds > 43200,
    and False iff elapsed_seconds <= 43200.
    """
    now = last_ts + timedelta(seconds=elapsed_seconds)
    result = is_backup_stale(last_ts, now)

    if elapsed_seconds > 43200:
        assert result is True, (
            f"Expected is_backup_stale=True for elapsed={elapsed_seconds}s > 43200s, "
            f"got {result}"
        )
    else:
        assert result is False, (
            f"Expected is_backup_stale=False for elapsed={elapsed_seconds}s <= 43200s, "
            f"got {result}"
        )


# ---------------------------------------------------------------------------
# Property 11: Remote transfer method dispatch is exhaustive
# ---------------------------------------------------------------------------

# Feature: database-backup-redundancy, Property 11: Remote transfer method dispatch is exhaustive
@given(method=st.text())
@settings(max_examples=100)
def test_dispatch_transfer_method_exhaustive(method):
    """Validates: Requirements 3.2

    dispatch_transfer_method routes correctly for known methods and raises
    ValueError for any unknown method.
    """
    assume(method not in {"rclone", "s3", "rsync"})

    with pytest.raises(ValueError):
        dispatch_transfer_method(method)


def test_dispatch_transfer_method_known_methods():
    """Validates: Requirements 3.2

    dispatch_transfer_method returns the correct canonical name for each
    known method: "rclone", "s3", "rsync".
    """
    assert dispatch_transfer_method("rclone") == "rclone"
    assert dispatch_transfer_method("s3") == "s3"
    assert dispatch_transfer_method("rsync") == "rsync"
