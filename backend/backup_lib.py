"""
backup_lib.py — Pure Python helper module for the database backup system.

No external dependencies beyond the Python 3 standard library.
Placed at /home/deploy/backup_lib.py on the VPS and at backend/backup_lib.py
for local development and testing.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Callable


# ---------------------------------------------------------------------------
# 1. generate_backup_filename
# ---------------------------------------------------------------------------

def generate_backup_filename(timestamp: datetime, backup_type: str) -> str:
    """Return a backup filename for the given UTC timestamp and backup type.

    Args:
        timestamp: A UTC datetime object.
        backup_type: Either "scheduled" or "pre-deploy".

    Returns:
        "backup_YYYY-MM-DD_HH-MM-SS.dump" for type "scheduled".
        "backup_pre-deploy_YYYY-MM-DD_HH-MM-SS.dump" for type "pre-deploy".

    Raises:
        ValueError: If backup_type is not "scheduled" or "pre-deploy".
    """
    if backup_type not in ("scheduled", "pre-deploy"):
        raise ValueError(f"Unknown backup_type: {backup_type!r}. Must be 'scheduled' or 'pre-deploy'.")

    ts_str = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
    if backup_type == "scheduled":
        return f"backup_{ts_str}.dump"
    else:  # pre-deploy
        return f"backup_pre-deploy_{ts_str}.dump"


# ---------------------------------------------------------------------------
# 2. parse_backup_filename
# ---------------------------------------------------------------------------

# Patterns for the two filename formats
_SCHEDULED_RE = re.compile(
    r"^backup_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.dump$"
)
_PREDEPLOY_RE = re.compile(
    r"^backup_pre-deploy_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.dump$"
)


def parse_backup_filename(filename: str) -> tuple[datetime, str]:
    """Parse a backup filename back to (timestamp, backup_type).

    Args:
        filename: A filename produced by generate_backup_filename.

    Returns:
        A tuple of (datetime in UTC, backup_type string).

    Raises:
        ValueError: If the filename does not match either expected pattern.
    """
    m = _PREDEPLOY_RE.match(filename)
    if m:
        ts_str = m.group(1)
        backup_type = "pre-deploy"
    else:
        m = _SCHEDULED_RE.match(filename)
        if m:
            ts_str = m.group(1)
            backup_type = "scheduled"
        else:
            raise ValueError(
                f"Malformed backup filename: {filename!r}. "
                "Expected 'backup_YYYY-MM-DD_HH-MM-SS.dump' or "
                "'backup_pre-deploy_YYYY-MM-DD_HH-MM-SS.dump'."
            )

    try:
        ts = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp in filename {filename!r}: {exc}") from exc

    return ts, backup_type


# ---------------------------------------------------------------------------
# 3. serialize_manifest_entry
# ---------------------------------------------------------------------------

def serialize_manifest_entry(entry: dict) -> str:
    """Serialize a manifest entry dict to a single-line JSON string.

    The entry must contain exactly these 8 fields:
        filename, timestamp, size_bytes, sha256, integrity,
        type, remote_transferred, remote_path

    The timestamp value may be a datetime object or an ISO 8601 string;
    datetime objects are serialized to ISO 8601 UTC strings.

    Args:
        entry: A dict with the 8 manifest fields.

    Returns:
        A compact JSON string (no trailing newline).
    """
    # Make a shallow copy so we don't mutate the caller's dict
    serializable = dict(entry)

    # Convert datetime timestamp to ISO string if needed
    if isinstance(serializable.get("timestamp"), datetime):
        dt = serializable["timestamp"]
        # Ensure UTC representation
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        serializable["timestamp"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    return json.dumps(serializable, separators=(",", ":"))


# ---------------------------------------------------------------------------
# 4. parse_manifest_entry
# ---------------------------------------------------------------------------

def parse_manifest_entry(line: str) -> dict:
    """Parse a JSON manifest line back to a dict.

    Args:
        line: A JSON string produced by serialize_manifest_entry.

    Returns:
        The parsed dict.

    Raises:
        ValueError: If the line is not valid JSON.
    """
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid manifest line: {exc}") from exc


# ---------------------------------------------------------------------------
# 5. filter_by_retention
# ---------------------------------------------------------------------------

def filter_by_retention(
    files: list[dict],
    now: datetime,
    retention_days: int,
) -> list[dict]:
    """Return files whose age is strictly less than retention_days.

    Files whose age is >= retention_days are excluded (they should be deleted).

    Args:
        files: List of dicts, each with a "timestamp" field (datetime or ISO string).
        now: The current UTC datetime used as the reference point.
        retention_days: Number of days; files older than this are excluded.

    Returns:
        A list of file dicts to keep (age < retention_days).
    """
    threshold_seconds = retention_days * 86400  # days → seconds
    kept = []
    for f in files:
        ts = f["timestamp"]
        if isinstance(ts, str):
            # Accept both "Z" suffix and "+00:00" offset
            ts = _parse_iso_timestamp(ts)
        # Ensure both datetimes are offset-aware for comparison
        ts_aware = _ensure_utc(ts)
        now_aware = _ensure_utc(now)
        age_seconds = (now_aware - ts_aware).total_seconds()
        if age_seconds < threshold_seconds:
            kept.append(f)
    return kept


# ---------------------------------------------------------------------------
# 6. compare_checksums
# ---------------------------------------------------------------------------

def compare_checksums(expected: str, computed: str) -> bool:
    """Case-insensitive comparison of two SHA-256 hex strings.

    Args:
        expected: The expected SHA-256 hex digest.
        computed: The computed SHA-256 hex digest.

    Returns:
        True if the strings are identical (case-insensitive), False otherwise.
    """
    return expected.lower() == computed.lower()


# ---------------------------------------------------------------------------
# 7. lookup_manifest_entry
# ---------------------------------------------------------------------------

def lookup_manifest_entry(manifest_lines: list[str], filename: str) -> dict | None:
    """Search manifest lines for the first entry with a matching filename.

    Args:
        manifest_lines: List of JSON strings (one per manifest entry).
        filename: The filename to search for.

    Returns:
        The first matching entry dict, or None if not found.
    """
    for line in manifest_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = parse_manifest_entry(line)
        except ValueError:
            continue
        if entry.get("filename") == filename:
            return entry
    return None


# ---------------------------------------------------------------------------
# 8. generate_remote_path
# ---------------------------------------------------------------------------

def generate_remote_path(prefix: str, timestamp: datetime, filename: str) -> str:
    """Return the remote storage path for a backup file.

    Args:
        prefix: The remote path prefix (e.g. "backups").
        timestamp: A UTC datetime used to derive YYYY/MM/DD components.
        filename: The backup filename.

    Returns:
        A string of the form "<prefix>/YYYY/MM/DD/<filename>".
    """
    ts_aware = _ensure_utc(timestamp)
    year = ts_aware.strftime("%Y")
    month = ts_aware.strftime("%m")
    day = ts_aware.strftime("%d")
    return f"{prefix}/{year}/{month}/{day}/{filename}"


# ---------------------------------------------------------------------------
# 9. retry_controller
# ---------------------------------------------------------------------------

def retry_controller(
    attempt_fn: Callable[[], bool],
    max_retries: int,
) -> tuple[bool, int]:
    """Call attempt_fn() up to max_retries times, stopping on first success.

    Does NOT call time.sleep — delay between retries is the shell script's
    responsibility. This keeps the function pure and testable.

    Args:
        attempt_fn: A callable that returns True on success, False on failure.
        max_retries: Maximum number of attempts to make.

    Returns:
        A tuple (success, attempts_made) where:
            success     — True if any attempt returned True.
            attempts_made — The number of times attempt_fn was called.
    """
    for attempt in range(1, max_retries + 1):
        if attempt_fn():
            return True, attempt
    return False, max_retries


# ---------------------------------------------------------------------------
# 10. format_alert_message
# ---------------------------------------------------------------------------

def format_alert_message(
    backup_type: str,
    timestamp: datetime,
    reason: str,
    credentials: list[str],
) -> str:
    """Format an alert message for a backup event.

    Asserts that none of the credential values appear in the output.

    Args:
        backup_type: The type of backup (e.g. "scheduled", "pre-deploy").
        timestamp: The UTC datetime of the event.
        reason: A human-readable description of the failure reason.
        credentials: A list of credential strings that must NOT appear in output.

    Returns:
        A formatted alert message string.

    Raises:
        AssertionError: If any credential value appears in the output.
    """
    ts_aware = _ensure_utc(timestamp)
    ts_str = ts_aware.strftime("%Y-%m-%dT%H:%M:%SZ")
    message = (
        f"[Backup Alert]\n"
        f"Type: {backup_type}\n"
        f"Timestamp: {ts_str}\n"
        f"Reason: {reason}"
    )
    # Safety check: no credential value must appear in the message
    for cred in credentials:
        if cred and cred in message:
            raise AssertionError(
                f"Credential value found in alert message. "
                f"Credential must not be interpolated into alert output."
            )
    return message


# ---------------------------------------------------------------------------
# 11. aggregate_daily_summary
# ---------------------------------------------------------------------------

def aggregate_daily_summary(
    manifest_lines: list[str],
    window_start: datetime,
    window_end: datetime,
) -> dict:
    """Count successful and failed backups within a time window.

    Window is start-inclusive, end-exclusive: [window_start, window_end).

    Args:
        manifest_lines: List of JSON manifest line strings.
        window_start: Start of the window (inclusive), UTC datetime.
        window_end: End of the window (exclusive), UTC datetime.

    Returns:
        A dict {"successful": int, "failed": int}.
    """
    successful = 0
    failed = 0
    ws = _ensure_utc(window_start)
    we = _ensure_utc(window_end)

    for line in manifest_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = parse_manifest_entry(line)
        except ValueError:
            continue

        ts_raw = entry.get("timestamp")
        if ts_raw is None:
            continue
        if isinstance(ts_raw, str):
            try:
                ts = _parse_iso_timestamp(ts_raw)
            except ValueError:
                continue
        else:
            ts = ts_raw

        ts = _ensure_utc(ts)

        # Window is [start, end) — start inclusive, end exclusive
        if ws <= ts < we:
            integrity = entry.get("integrity", "")
            if integrity == "valid":
                successful += 1
            elif integrity == "invalid":
                failed += 1

    return {"successful": successful, "failed": failed}


# ---------------------------------------------------------------------------
# 12. is_backup_stale
# ---------------------------------------------------------------------------

def is_backup_stale(last_backup_ts: datetime, now: datetime) -> bool:
    """Return True if the backup is stale (elapsed time > 43200 seconds / 12 hours).

    The boundary (exactly 43200 seconds) is NOT stale — returns False.

    Args:
        last_backup_ts: UTC datetime of the most recent successful backup.
        now: The current UTC datetime.

    Returns:
        True if elapsed seconds > 43200, False if elapsed seconds <= 43200.
    """
    last = _ensure_utc(last_backup_ts)
    current = _ensure_utc(now)
    elapsed = (current - last).total_seconds()
    return elapsed > 43200


# ---------------------------------------------------------------------------
# 13. dispatch_transfer_method
# ---------------------------------------------------------------------------

def dispatch_transfer_method(method: str) -> str:
    """Return the canonical transfer method name for the given method string.

    Args:
        method: One of "rclone", "s3", or "rsync".

    Returns:
        The method string unchanged ("rclone", "s3", or "rsync").

    Raises:
        ValueError: For any value other than "rclone", "s3", or "rsync"
                    (including empty string and whitespace-only strings).
    """
    if method == "rclone":
        return "rclone"
    elif method == "s3":
        return "s3"
    elif method == "rsync":
        return "rsync"
    else:
        raise ValueError(
            f"Unknown transfer method: {method!r}. "
            "Must be one of 'rclone', 's3', or 'rsync'."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    If dt is naive, assume it is UTC and attach the UTC timezone.
    If dt is already aware, convert to UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string to a datetime.

    Accepts strings ending in 'Z' or '+00:00'.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    # Normalize 'Z' suffix to '+00:00' for fromisoformat compatibility
    normalized = ts_str
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Cannot parse timestamp {ts_str!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# __main__ CLI interface
# ---------------------------------------------------------------------------

def _cli_generate_filename(args: list[str]) -> None:
    """generate-filename <type>  — print filename using current UTC time."""
    if len(args) != 1:
        print("Usage: backup_lib.py generate-filename <scheduled|pre-deploy>", file=sys.stderr)
        sys.exit(1)
    backup_type = args[0]
    now = datetime.now(tz=timezone.utc)
    try:
        print(generate_backup_filename(now, backup_type))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _cli_lookup_manifest(args: list[str]) -> None:
    """lookup-manifest <manifest_file> <filename>  — print JSON entry or exit 1."""
    if len(args) != 2:
        print("Usage: backup_lib.py lookup-manifest <manifest_file> <filename>", file=sys.stderr)
        sys.exit(1)
    manifest_file, filename = args
    try:
        with open(manifest_file, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"Error reading manifest file: {exc}", file=sys.stderr)
        sys.exit(1)
    entry = lookup_manifest_entry(lines, filename)
    if entry is None:
        print(f"Entry not found for filename: {filename}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(entry))


def _cli_filter_retention(args: list[str]) -> None:
    """filter-retention <manifest_file> <now_iso> <retention_days>  — print filenames to keep."""
    if len(args) != 3:
        print(
            "Usage: backup_lib.py filter-retention <manifest_file> <now_iso> <retention_days>",
            file=sys.stderr,
        )
        sys.exit(1)
    manifest_file, now_iso, retention_days_str = args
    try:
        now = _parse_iso_timestamp(now_iso)
    except ValueError as exc:
        print(f"Error parsing now timestamp: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        retention_days = int(retention_days_str)
    except ValueError:
        print(f"Error: retention_days must be an integer, got {retention_days_str!r}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(manifest_file, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"Error reading manifest file: {exc}", file=sys.stderr)
        sys.exit(1)

    files = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = parse_manifest_entry(line)
            files.append(entry)
        except ValueError:
            continue

    kept = filter_by_retention(files, now, retention_days)
    for f in kept:
        print(f.get("filename", ""))


def _cli_generate_remote_path(args: list[str]) -> None:
    """generate-remote-path <prefix> <timestamp_iso> <filename>  — print remote path."""
    if len(args) != 3:
        print(
            "Usage: backup_lib.py generate-remote-path <prefix> <timestamp_iso> <filename>",
            file=sys.stderr,
        )
        sys.exit(1)
    prefix, timestamp_iso, filename = args
    try:
        ts = _parse_iso_timestamp(timestamp_iso)
    except ValueError as exc:
        print(f"Error parsing timestamp: {exc}", file=sys.stderr)
        sys.exit(1)
    print(generate_remote_path(prefix, ts, filename))


def _cli_is_stale(args: list[str]) -> None:
    """is-stale <last_backup_iso> <now_iso>  — exit 0 if stale, 1 if not."""
    if len(args) != 2:
        print("Usage: backup_lib.py is-stale <last_backup_iso> <now_iso>", file=sys.stderr)
        sys.exit(1)
    last_iso, now_iso = args
    try:
        last_ts = _parse_iso_timestamp(last_iso)
        now = _parse_iso_timestamp(now_iso)
    except ValueError as exc:
        print(f"Error parsing timestamp: {exc}", file=sys.stderr)
        sys.exit(1)
    stale = is_backup_stale(last_ts, now)
    sys.exit(0 if stale else 1)


def _cli_serialize_manifest(args: list[str]) -> None:
    """serialize-manifest  — read JSON from stdin, print serialized line."""
    if args:
        print("Usage: backup_lib.py serialize-manifest  (reads JSON from stdin)", file=sys.stderr)
        sys.exit(1)
    raw = sys.stdin.read()
    try:
        entry = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error parsing JSON from stdin: {exc}", file=sys.stderr)
        sys.exit(1)
    print(serialize_manifest_entry(entry))


def _cli_compare_checksums(args: list[str]) -> None:
    """compare-checksums <expected> <computed>  — exit 0 if match, 1 if not."""
    if len(args) != 2:
        print("Usage: backup_lib.py compare-checksums <expected> <computed>", file=sys.stderr)
        sys.exit(1)
    expected, computed = args
    match = compare_checksums(expected, computed)
    sys.exit(0 if match else 1)


def _cli_aggregate_summary(args: list[str]) -> None:
    """aggregate-summary <manifest_file> <window_start_iso> <window_end_iso>  — print JSON summary."""
    if len(args) != 3:
        print(
            "Usage: backup_lib.py aggregate-summary <manifest_file> <window_start_iso> <window_end_iso>",
            file=sys.stderr,
        )
        sys.exit(1)
    manifest_file, window_start_iso, window_end_iso = args
    try:
        window_start = _parse_iso_timestamp(window_start_iso)
        window_end = _parse_iso_timestamp(window_end_iso)
    except ValueError as exc:
        print(f"Error parsing timestamp: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(manifest_file, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"Error reading manifest file: {exc}", file=sys.stderr)
        sys.exit(1)
    summary = aggregate_daily_summary(lines, window_start, window_end)
    print(json.dumps(summary))


_CLI_COMMANDS: dict[str, tuple[Callable[[list[str]], None], str]] = {
    "generate-filename": (_cli_generate_filename, "generate-filename <scheduled|pre-deploy>"),
    "lookup-manifest": (_cli_lookup_manifest, "lookup-manifest <manifest_file> <filename>"),
    "filter-retention": (_cli_filter_retention, "filter-retention <manifest_file> <now_iso> <retention_days>"),
    "generate-remote-path": (_cli_generate_remote_path, "generate-remote-path <prefix> <timestamp_iso> <filename>"),
    "is-stale": (_cli_is_stale, "is-stale <last_backup_iso> <now_iso>"),
    "serialize-manifest": (_cli_serialize_manifest, "serialize-manifest  (reads JSON from stdin)"),
    "compare-checksums": (_cli_compare_checksums, "compare-checksums <expected> <computed>"),
    "aggregate-summary": (_cli_aggregate_summary, "aggregate-summary <manifest_file> <window_start_iso> <window_end_iso>"),
}


def _main() -> None:
    if len(sys.argv) < 2:
        print("Usage: backup_lib.py <command> [args...]", file=sys.stderr)
        print("Commands:", file=sys.stderr)
        for cmd, (_, usage) in _CLI_COMMANDS.items():
            print(f"  {usage}", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    remaining_args = sys.argv[2:]

    if command not in _CLI_COMMANDS:
        print(f"Unknown command: {command!r}", file=sys.stderr)
        print(f"Available commands: {', '.join(_CLI_COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    handler, _ = _CLI_COMMANDS[command]
    handler(remaining_args)


if __name__ == "__main__":
    _main()
