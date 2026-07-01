"""Classify post-deploy HubSpot sync work from changed file paths."""
from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

DeploySyncMode = Literal['skip', 'rescore_only', 'full_pipeline']

# Deploy glue — pipeline runner / post-deploy dispatch changes do not need a
# full HubSpot data refresh when a pipeline completed recently.
_PIPELINE_GLUE_SEGMENTS = (
    'hubspot_pipeline_runner.py',
    'deploy_sync_policy.py',
    'post_deploy_sync.py',
    'run_pipeline_once.py',
)

# Path globs that require a full HubSpot pipeline (checked first).
_FULL_PIPELINE_PATTERNS = (
    'backend/app/services/hubspot_*',
    'backend/app/tasks/hubspot_*',
    'backend/app/controllers/hubspot_*',
    'backend/app/models/hubspot_*',
    'backend/scripts/*hubspot*',
    'backend/scripts/hubspot_*',
    'backend/**/webhook*',
    'backend/**/hubspot_webhook*',
)

# Path globs that require rescoring only (no HubSpot fetch/enrich).
_RESCORE_ONLY_PATTERNS = (
    'backend/app/services/lead_scoring_engine*',
    'backend/app/services/outreach_method*',
    'backend/app/services/action_engine*',
    'backend/app/services/queue_service*',
    'backend/app/controllers/property_controller*',
    'backend/celery_worker.py',
    'backend/migrations/versions/*score*',
    'backend/migrations/versions/*scoring*',
    'backend/migrations/versions/*outreach*',
    'backend/migrations/versions/*recommended_contact*',
)

DEPLOY_PIPELINE_COOLDOWN_HOURS = int(
    os.environ.get('DEPLOY_PIPELINE_COOLDOWN_HOURS', '4'),
)


def _normalize_path(path: str) -> str:
    return path.replace('\\', '/').lstrip('./')


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob with ``**`` into a regex (portable across OSes)."""
    normalized = _normalize_path(pattern)
    parts = normalized.split('**')
    regex_parts = []
    for index, part in enumerate(parts):
        if index > 0:
            regex_parts.append('(?:.*/)?')
        regex_parts.append(
            re.escape(part).replace(r'\*', '[^/]*').replace(r'\?', '[^/]'),
        )
    return re.compile('^' + ''.join(regex_parts) + '$')


def _match_path_pattern(path: str, pattern: str) -> bool:
    normalized = _normalize_path(path)
    if '**' in pattern:
        return _glob_to_regex(pattern).match(normalized) is not None
    return fnmatch.fnmatchcase(normalized, pattern)


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = _normalize_path(path)
    return any(_match_path_pattern(normalized, pattern) for pattern in patterns)


def _is_pipeline_glue_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(segment in normalized for segment in _PIPELINE_GLUE_SEGMENTS)


def _path_has_hubspot_or_webhook_component(path: str) -> bool:
    """Match nested backend paths like ``backend/app/foo/hubspot_bar.py``."""
    normalized = _normalize_path(path)
    if not normalized.startswith('backend/'):
        return False
    for part in normalized.split('/'):
        if part.startswith('hubspot_') or 'hubspot_' in part:
            return True
        if 'webhook' in part.lower():
            return True
    return False


def paths_require_full_pipeline(changed_paths: list[str]) -> bool:
    return any(
        _matches_any(p, _FULL_PIPELINE_PATTERNS) or _path_has_hubspot_or_webhook_component(p)
        for p in changed_paths
    )


def paths_require_rescore(changed_paths: list[str]) -> bool:
    return any(_matches_any(p, _RESCORE_ONLY_PATTERNS) for p in changed_paths)


def paths_require_hubspot_data_pipeline(changed_paths: list[str]) -> bool:
    """True when changed paths affect HubSpot data (not deploy glue only)."""
    return any(
        not _is_pipeline_glue_path(path)
        and (
            _matches_any(path, _FULL_PIPELINE_PATTERNS)
            or _matches_any(path, _RESCORE_ONLY_PATTERNS)
        )
        for path in changed_paths
    )


def classify_deploy_sync_mode(changed_paths: list[str]) -> DeploySyncMode:
    """Return post-deploy sync mode from a list of changed repo paths."""
    if not changed_paths:
        return 'skip'

    if paths_require_full_pipeline(changed_paths):
        return 'full_pipeline'
    if paths_require_rescore(changed_paths):
        return 'rescore_only'
    return 'skip'


def load_changed_paths_from_file(path: Optional[str]) -> list[str]:
    """Read newline-separated changed paths from the deploy manifest file."""
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as handle:
        return [
            line.strip()
            for line in handle
            if line.strip() and not line.startswith('#')
        ]


def load_changed_paths_for_deploy(
    path: Optional[str],
) -> tuple[list[str], bool]:
    """Load changed paths; return ``(paths, unknown_delta)``.

    *unknown_delta* is True when the manifest is missing or empty — callers
    should run a full pipeline as a safe fallback.
    """
    if not path or not os.path.isfile(path):
        return [], True
    paths = load_changed_paths_from_file(path)
    if not paths:
        return [], True
    return paths, False


def _redis_client():
    try:
        import redis as redis_lib

        redis_url = os.environ.get('REDIS_URL') or os.environ.get('CELERY_BROKER_URL', '')
        if not redis_url:
            return None
        return redis_lib.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    except Exception:
        return None


def get_redis_value(key: str) -> Optional[str]:
    client = _redis_client()
    if client is None:
        return None
    try:
        value = client.get(key)
        return value.decode('utf-8') if isinstance(value, bytes) else value
    except Exception:
        return None


def set_redis_value(key: str, value: str) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.set(key, value)
    except Exception:
        pass


def pipeline_completed_within_cooldown() -> bool:
    """Return True when a pipeline completed within the cooldown window."""
    last_completed = get_redis_value('deploy:last_pipeline_completed_at')
    if not last_completed:
        return False

    try:
        completed_at = datetime.fromisoformat(last_completed.replace('Z', '+00:00'))
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEPLOY_PIPELINE_COOLDOWN_HOURS)
    return completed_at >= cutoff


def apply_pipeline_cooldown(
    mode: DeploySyncMode,
    changed_paths: list[str],
) -> DeploySyncMode:
    """Downgrade redundant full pipeline runs within the cooldown window."""
    if mode != 'full_pipeline':
        return mode
    if not pipeline_completed_within_cooldown():
        return mode
    if paths_require_hubspot_data_pipeline(changed_paths):
        return mode
    logger_msg = (
        'full_pipeline downgraded to skip — pipeline completed within '
        f'{DEPLOY_PIPELINE_COOLDOWN_HOURS}h and only deploy-glue paths changed'
    )
    # Lazy import to avoid circular logging at module import
    import logging
    logging.getLogger(__name__).info(logger_msg)
    return 'skip'


def should_upgrade_dangling_to_full_pipeline() -> bool:
    """Whether dangling matches should trigger a full pipeline on this deploy."""
    if not pipeline_completed_within_cooldown():
        return True
    import logging
    logging.getLogger(__name__).info(
        'Skipping dangling-match full pipeline upgrade — pipeline completed '
        'within %dh (nightly/beat catch-up)',
        DEPLOY_PIPELINE_COOLDOWN_HOURS,
    )
    return False


def resolve_deploy_sync_mode(changed_paths: list[str]) -> DeploySyncMode:
    """Classify mode and apply cooldown downgrade for post-deploy dispatch."""
    mode = classify_deploy_sync_mode(changed_paths)
    return apply_pipeline_cooldown(mode, changed_paths)


def resolve_deploy_sync_from_manifest(path: Optional[str]) -> DeploySyncMode:
    """Resolve sync mode from the VPS changed-paths manifest file."""
    changed_paths, unknown_delta = load_changed_paths_for_deploy(path)
    if unknown_delta:
        import logging
        logging.getLogger(__name__).warning(
            'Changed-path manifest missing or empty — defaulting to full_pipeline',
        )
        return 'full_pipeline'
    return resolve_deploy_sync_mode(changed_paths)


def record_pipeline_completed(rescore_count: int = 0) -> None:
    """Persist deploy pipeline metrics in Redis."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    set_redis_value('deploy:last_pipeline_completed_at', now)
    set_redis_value('deploy:last_rescore_count', str(rescore_count))


def scoring_code_file_hash() -> str:
    """SHA-256 of lead_scoring_engine.py for deploy rescore fallback."""
    import hashlib
    from pathlib import Path

    engine_path = Path(__file__).resolve().parent / 'lead_scoring_engine.py'
    return hashlib.sha256(engine_path.read_bytes()).hexdigest()


def scoring_code_changed_since_last_run() -> bool:
    """True when scoring engine source differs from the last recorded deploy hash."""
    current = scoring_code_file_hash()
    previous = get_redis_value('deploy:scoring_code_hash')
    return previous is not None and previous != current


def record_scoring_code_hash() -> None:
    set_redis_value('deploy:scoring_code_hash', scoring_code_file_hash())
