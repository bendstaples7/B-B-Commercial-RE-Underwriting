"""Celery task implementations for lead duplicate sentinel."""
from __future__ import annotations

import logging

from app.services.lead_dedup_service import run_duplicate_sentinel

logger = logging.getLogger(__name__)


def run_lead_duplicate_sentinel(
    dry_run: bool = False,
    max_merges: int = 100,
) -> dict:
    """Scan for duplicate leads and merge or flag them."""
    stats = run_duplicate_sentinel(dry_run=dry_run, max_merges=max_merges)
    logger.info("lead duplicate sentinel finished: %s", stats)
    return stats
