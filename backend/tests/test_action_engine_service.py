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
    lead_status='mailing_no_contact_made',
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


def test_priority_2_deprioritize_returns_none():
    lead = make_lead(lead_status='deprioritize')
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result is None


def test_priority_2_deal_won_returns_none():
    lead = make_lead(lead_status='deal_won')
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result is None


# ---------------------------------------------------------------------------
# Priority 2.5: skip_trace / awaiting_skip_trace → add_contact_info always
# ---------------------------------------------------------------------------

def test_priority_2_5_skip_trace_returns_add_contact_info_even_with_phone_email():
    """skip_trace status always returns add_contact_info regardless of has_phone/has_email."""
    lead = make_lead(lead_status='skip_trace', has_phone=True, has_email=True)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'add_contact_info'


def test_priority_2_5_awaiting_skip_trace_returns_add_contact_info():
    """awaiting_skip_trace status always returns add_contact_info."""
    lead = make_lead(lead_status='awaiting_skip_trace', has_phone=True, has_email=True, is_warm=True)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'add_contact_info'


def test_priority_2_5_fires_before_follow_up_overdue():
    """skip_trace status intercepts before follow_up_overdue check."""
    lead = make_lead(lead_status='skip_trace', follow_up_overdue=True, is_warm=True)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'add_contact_info'


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
# Priority 5 (old): has match but no analysis — analyze_property REMOVED
# Property analysis is optional and never a mandatory workflow step.
# A lead with contact info + property match should proceed to create_task.
# ---------------------------------------------------------------------------

def test_priority_5_has_match_no_analysis_no_longer_returns_analyze_property():
    lead = make_lead(has_property_match=True, analysis_complete=False)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    # Should now fall through to create_task (new, active with no tasks)
    assert result == 'create_task'


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
    lead = make_lead(lead_score=70.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'ready_for_outreach'


def test_priority_7_high_score_with_open_tasks_skips_ready_for_outreach():
    """When open tasks exist, priority 7 does not fire; falls through."""
    lead = make_lead(lead_score=70.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=2):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result != 'ready_for_outreach'


# ---------------------------------------------------------------------------
# Priority 8: has contact info + property match + no open tasks → create_task
# (data_completeness_score no longer gates enrich_data — removed)
# ---------------------------------------------------------------------------

def test_priority_9_low_completeness_no_longer_returns_enrich_data():
    """data_completeness_score threshold removed — low completeness does not block outreach."""
    lead = make_lead(lead_score=40.0, data_completeness_score=49.9)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    # Falls through to create_task — has contact info, property match, no open tasks
    assert result == 'create_task'


# ---------------------------------------------------------------------------
# Priority 8: any contactable matched lead with no tasks → create_task
# ---------------------------------------------------------------------------

def test_priority_10_active_no_tasks_returns_create_task():
    lead = make_lead(lead_status='mailing_no_contact_made', lead_score=40.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'create_task'


def test_priority_10_new_no_tasks_returns_create_task():
    lead = make_lead(lead_status='negotiating_remote', lead_score=40.0, data_completeness_score=60.0)
    with patch('app.services.action_engine_service._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)
    assert result == 'create_task'


# ---------------------------------------------------------------------------
# Priority 9: default → nurture (when open tasks exist)
# ---------------------------------------------------------------------------

def test_priority_11_default_returns_nurture():
    """follow_up status with open tasks → nurture."""
    lead = make_lead(
        lead_status='mailing_contacted_interested',
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
            lead_status='mailing_contacted_interested',
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
        meta = entries[0].event_metadata
        assert meta['previous_action'] is None
        assert meta['new_action'] == 'follow_up_now'
        assert meta['winning_rule'] == 'follow_up_overdue'
        assert meta['lead_score'] == 50.0
        assert meta['is_warm'] is False
        assert meta['signals'] == {
            'follow_up_overdue': True,
            'has_overdue_hs_task': False,
        }
        assert 'property_street' not in meta['signals']


def test_recompute_and_persist_no_timeline_when_ra_unchanged(app):
    """recompute_and_persist does NOT append a timeline entry when RA is unchanged."""
    from app import db
    from app.models import Lead, LeadTimelineEntry

    with app.app_context():
        lead = Lead(
            property_street='789 Pine Rd',
            lead_status='mailing_contacted_interested',
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

