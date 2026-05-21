"""Backward-compatibility stub for lead_controller.

All logic has moved to property_controller.py.
This module re-exports the blueprints so existing imports continue to work
during the transition period.
"""
# Re-export everything from the new module
from app.controllers.property_controller import (  # noqa: F401
    properties_bp as lead_bp,
    leads_legacy_bp,
    properties_bp,
    handle_errors,
    _serialize_property_summary as _serialize_lead_summary,
    _serialize_property_detail as _serialize_lead_detail,
    _serialize_scoring_weights,
)
