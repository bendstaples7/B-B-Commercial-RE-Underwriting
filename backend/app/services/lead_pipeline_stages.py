"""Canonical lead pipeline stages for Kanban + score bonuses.

``pipeline_stage_configs.stage_name`` must match ``leads.lead_status``.
Weights are added to ``lead_score`` via ``LeadScoringEngine._pipeline_stage_bonus``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class LeadPipelineStage(TypedDict):
    stage_name: str
    label: str
    order: int
    weight: float


# Farther-along stages score higher; terminal / parked stages are penalized.
LEAD_PIPELINE_STAGES: tuple[LeadPipelineStage, ...] = (
    {"stage_name": "awaiting_skip_trace", "label": "Awaiting Skip Trace", "order": 0, "weight": -10.0},
    {"stage_name": "skip_trace", "label": "Skip Trace", "order": 1, "weight": -5.0},
    {"stage_name": "mailing_no_contact_made", "label": "Mailing, No Contact Made", "order": 2, "weight": 0.0},
    {
        "stage_name": "mailing_contacted_no_interest",
        "label": "Mailing, Contacted, No Interest",
        "order": 3,
        "weight": -15.0,
    },
    {
        "stage_name": "mailing_contacted_interested",
        "label": "Mailing, Contacted, Interested",
        "order": 4,
        "weight": 20.0,
    },
    {"stage_name": "negotiating_remote", "label": "Negotiating Remote", "order": 5, "weight": 35.0},
    {"stage_name": "in_person_appointment", "label": "In Person Appointment", "order": 6, "weight": 45.0},
    {"stage_name": "offer_delivered", "label": "Offer Delivered", "order": 7, "weight": 55.0},
    {"stage_name": "deprioritize", "label": "Deprioritize", "order": 8, "weight": -25.0},
    {"stage_name": "deal_won", "label": "Deal Won", "order": 9, "weight": 0.0},
    {"stage_name": "deal_lost", "label": "Deal Lost", "order": 10, "weight": -30.0},
    {"stage_name": "suppressed", "label": "Suppressed", "order": 11, "weight": -40.0},
    {"stage_name": "do_not_contact", "label": "Do Not Contact", "order": 12, "weight": -40.0},
)

DEFAULT_STAGE_WEIGHTS: dict[str, Decimal] = {
    s["stage_name"]: Decimal(str(s["weight"])) for s in LEAD_PIPELINE_STAGES
}

STAGE_LABELS: dict[str, str] = {s["stage_name"]: s["label"] for s in LEAD_PIPELINE_STAGES}

# Retired multifamily CRM labels only — seed/migration must not delete custom stages.
LEGACY_PIPELINE_STAGE_NAMES: frozenset[str] = frozenset({
    'Draft',
    'Lead',
    'Qualification',
    'Proposal',
    'Negotiation',
    'Closed Won',
    'Closed Lost',
})
