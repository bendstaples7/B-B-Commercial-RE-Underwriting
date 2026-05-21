"""
Unit tests for ActionEngineService.compute_recommended_action and recompute_and_persist.
"""
import pytest
from unittest.mock import MagicMock, patch, call

from app.services.action_engine_service import ActionEngineService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_lead(
    lead_status='active',
    has_phone=True,
    has_email=True,
    has_property_match=True,
    analysis_complete=True,
    follow_up_overdue=False,
    is_warm=False,
    lead_score=50.0,
    data_completeness_score=60.0,
    property_street='123 Main St',
    recommended_action=None,
):
    lead = MagicMock()
    lead.id = 1
    lead.lead_status = lead_status
    lead.has_phone = has_phone
    lead.has_email = has_email
    lead.has_property_match = has_property_match
    lead.analysis_complete = analysis_complete
    lead.follow_up_overdue = follow_up_overdue
    lead.is_warm = is_warm
    lead.lead_score = lead_score
    lead.data_completeness_score = data_completeness_score
    lead.property_street = property_street
    lead.recommended_action = recommended_action
    return lead


# ---------------------------------------------------------------------------
# Priority 1: do_not_contact → None
# ---------------------------------------------------------------------------

def test_priority_1_do_not_contact_returns_none():
    lead = make_lead(lead_status='do_not_contact')
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result is None


# ---------------------------------------------------------------------------
# Priority 2: suppressed → None
# ---------------------------------------------------------------------------

def test_priority_2_suppressed_returns_none():
    lead = make_lead(lead_status='suppressed')
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result is None


def test_priority_2_nurture_returns_none():
    lead = make_lead(lead_status='nurture')
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result is None


# ---------------------------------------------------------------------------
# Priority 3: no phone AND no email → add_contact_info
# ---------------------------------------------------------------------------

def test_priority_3_no_phone_no_email_returns_add_contact_info():
    lead = make_lead(has_phone=False, has_email=False)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'add_contact_info'


def test_priority_3_fires_before_priority_4():
    """Priority 3 (no contact info) fires before Priority 4 (no property match)."""
    lead = make_lead(has_phone=False, has_email=False, has_property_match=False)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'add_contact_info'


# ---------------------------------------------------------------------------
# Priority 4: no property match — split on address
# ---------------------------------------------------------------------------

def test_priority_4_no_match_with_address_returns_resolve_match():
    lead = make_lead(has_property_match=False, property_street='123 Main St')
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'resolve_match'


def test_priority_4_no_match_no_address_returns_enrich_data():
    lead = make_lead(has_property_match=False, property_street=None)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'enrich_data'


# ---------------------------------------------------------------------------
# Priority 5: has match but no analysis → analyze_property
# ---------------------------------------------------------------------------

def test_priority_5_has_match_no_analysis_returns_analyze_property():
    lead = make_lead(has_property_match=True, analysis_complete=False)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'analyze_property'


# ---------------------------------------------------------------------------
# Priority 6: follow_up_overdue → follow_up_now
# ---------------------------------------------------------------------------

def test_priority_6_follow_up_overdue_returns_follow_up_now():
    lead = make_lead(follow_up_overdue=True)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'follow_up_now'


# ---------------------------------------------------------------------------
# Priority 7: is_warm → follow_up_now
# ---------------------------------------------------------------------------

def test_priority_7_is_warm_returns_follow_up_now():
    lead = make_lead(is_warm=True)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'follow_up_now'


# ---------------------------------------------------------------------------
# Priority 8: high score + analysis complete + no open tasks → ready_for_outreach
# ---------------------------------------------------------------------------

def test_priority_8_high_score_no_tasks_returns_ready_for_outreach():
    lead = make_lead(analysis_complete=True, lead_score=70.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'ready_for_outreach'


def test_priority_8_high_score_with_open_tasks_skips_ready_for_outreach():
    """When open tasks exist, priority 8 does not fire; falls through to priority 9/10/11."""
    lead = make_lead(analysis_complete=True, lead_score=70.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=2):
        result = ActionEngineService.compute_recommended_action(lead)
    # Should not be ready_for_outreach since open tasks exist
    assert result != 'ready_for_outreach'


# ---------------------------------------------------------------------------
# Priority 9: low data completeness → enrich_data
# ---------------------------------------------------------------------------

def test_priority_9_low_completeness_returns_enrich_data():
    lead = make_lead(lead_score=40.0, data_completeness_score=49.9)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'enrich_data'


# ---------------------------------------------------------------------------
# Priority 10: active/new with no open tasks → create_task
# ---------------------------------------------------------------------------

def test_priority_10_active_no_tasks_returns_create_task():
    lead = make_lead(lead_status='active', lead_score=40.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'create_task'


def test_priority_10_new_no_tasks_returns_create_task():
    lead = make_lead(lead_status='new', lead_score=40.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'create_task'


# ---------------------------------------------------------------------------
# Priority 11: default → nurture
# ---------------------------------------------------------------------------

def test_priority_11_default_returns_nurture():
    """follow_up status with no other triggers → nurture."""
    lead = make_lead(
        lead_status='follow_up',
        lead_score=40.0,
        data_completeness_score=60.0,
        follow_up_overdue=False,
        is_warm=False,
    )
    with patch('app.services.action_engine_service._count_open_tasks', return_value=1):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'nurture'


# ---------------------------------------------------------------------------
# recompute_and_persist: timeline entry only appended when RA changes
# ---------------------------------------------------------------------------

def test_recompute_and_persist_appends_timeline_when_ra_changes(app):
    """recompute_and_persist appends a timeline entry only when RA changes."""
    from app import db
    from app.models import Lead, LeadTimelineEntry

    with app.app_context():
        lead = Lead(
            property_street='456 Oak Ave',
            lead_status='active',
            has_phone=True,
            has_email=True,
            has_property_match=True,
            analysis_complete=True,
            follow_up_overdue=True,
            is_warm=False,
            lead_score=50.0,
            data_completeness_score=60.0,
            recommended_action=None,  # will change to follow_up_now
        )
        db.session.add(lead)
        db.session.commit()

        ActionEngineService.recompute_and_persist(lead.id)

        entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id,
            event_type='recommended_action_changed',
        ).all()
        assert len(entries) == 1
        assert entries[0].event_metadata['new_action'] == 'follow_up_now'


def test_recompute_and_persist_no_timeline_when_ra_unchanged(app):
    """recompute_and_persist does NOT append a timeline entry when RA is unchanged."""
    from app import db
    from app.models import Lead, LeadTimelineEntry

    with app.app_context():
        lead = Lead(
            property_street='789 Pine Rd',
            lead_status='active',
            has_phone=True,
            has_email=True,
            has_property_match=True,
            analysis_complete=True,
            follow_up_overdue=True,
            is_warm=False,
            lead_score=50.0,
            data_completeness_score=60.0,
            recommended_action='follow_up_now',  # already correct
        )
        db.session.add(lead)
        db.session.commit()

        ActionEngineService.recompute_and_persist(lead.id)

        entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id,
            event_type='recommended_action_changed',
        ).all()
        assert len(entries) == 0
