"""Backward-compatible re-exports — logic lives in lead_scoring_engine.py.

``ActionEngineService`` is a deprecated alias for :class:`LeadScoringEngine`.
"""
from app.services.lead_scoring_engine import (
    ActionEngineService,
    LeadScoringEngine,
    evaluate_recommended_action,
    _count_open_tasks,
    _resolve_crm_flags,
    _timeline_signals,
)
from app.services.recommended_action_metadata import (
    RECOMMENDED_ACTION_METADATA,
    TASK_TYPE_TO_RECOMMENDED_ACTION,
)

__all__ = [
    'ActionEngineService',
    'RECOMMENDED_ACTION_METADATA',
    'TASK_TYPE_TO_RECOMMENDED_ACTION',
    'evaluate_recommended_action',
    '_count_open_tasks',
]
