"""
Unit tests for CallLogService.
"""
import pytest
from datetime import date
from unittest.mock import patch

from app.services.call_log_service import CallLogService
from app.exceptions import DoNotContactViolationError, LeadTaskValidationError

# ActionEngineService is lazily imported inside service functions, so we patch
# the canonical location rather than the service module's namespace.
_AE_PATCH = 'app.services.action_engine_service.ActionEngineService.recompute_and_persist'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street, lead_status='mailing_no_contact_made', has_phone=True, unanswered_call_count=0):
    from app import db
    from app.models import Lead

    lead = Lead(
        property_street=street,
        lead_status=lead_status,
        has_phone=has_phone,
        has_email=True,
        has_property_match=True,
        analysis_complete=True,
        lead_score=50.0,
        data_completeness_score=60.0,
        unanswered_call_count=unanswered_call_count,
    )
    db.session.add(lead)
    db.session.commit()
    return lead


# ---------------------------------------------------------------------------
# answered → updates last_contact_date
# ---------------------------------------------------------------------------

def test_answered_outcome_updates_last_contact_date(app):
    """Logging an 'answered' call updates last_contact_date to today."""
    with app.app_context():
        lead = _make_lead(app, '1 Call St')
        svc = CallLogService()

        with patch(_AE_PATCH):
            svc.log_call(lead.id, outcome='answered', duration_minutes=5, notes=None)

        from app.models import Lead
        updated = Lead.query.get(lead.id)
        assert updated.last_contact_date == date.today()


# ---------------------------------------------------------------------------
# voicemail / no_answer → increments unanswered_call_count
# ---------------------------------------------------------------------------

def test_voicemail_increments_unanswered_call_count(app):
    """Logging a 'voicemail' call increments unanswered_call_count by 1."""
    with app.app_context():
        lead = _make_lead(app, '2 Call St', unanswered_call_count=3)
        svc = CallLogService()

        with patch(_AE_PATCH):
            svc.log_call(lead.id, outcome='voicemail', duration_minutes=None, notes=None)

        from app.models import Lead
        updated = Lead.query.get(lead.id)
        assert updated.unanswered_call_count == 4


def test_no_answer_increments_unanswered_call_count(app):
    """Logging a 'no_answer' call increments unanswered_call_count by 1."""
    with app.app_context():
        lead = _make_lead(app, '3 Call St', unanswered_call_count=0)
        svc = CallLogService()

        with patch(_AE_PATCH):
            svc.log_call(lead.id, outcome='no_answer', duration_minutes=None, notes=None)

        from app.models import Lead
        updated = Lead.query.get(lead.id)
        assert updated.unanswered_call_count == 1


# ---------------------------------------------------------------------------
# wrong_number → sets has_phone=False
# ---------------------------------------------------------------------------

def test_wrong_number_sets_has_phone_false(app):
    """Logging a 'wrong_number' call sets has_phone=False."""
    with app.app_context():
        lead = _make_lead(app, '4 Call St', has_phone=True)
        svc = CallLogService()

        with patch(_AE_PATCH):
            svc.log_call(lead.id, outcome='wrong_number', duration_minutes=None, notes=None)

        from app.models import Lead
        updated = Lead.query.get(lead.id)
        assert updated.has_phone is False


# ---------------------------------------------------------------------------
# DNC lead raises DoNotContactViolationError
# ---------------------------------------------------------------------------

def test_dnc_lead_raises_do_not_contact_violation(app):
    """Logging a call on a DNC lead raises DoNotContactViolationError."""
    with app.app_context():
        lead = _make_lead(app, '5 Call St', lead_status='do_not_contact')
        svc = CallLogService()

        with pytest.raises(DoNotContactViolationError):
            svc.log_call(lead.id, outcome='answered', duration_minutes=5, notes=None)


# ---------------------------------------------------------------------------
# Note body > 5,000 chars raises validation error
# ---------------------------------------------------------------------------

def test_note_body_over_5000_chars_raises_validation_error(app):
    """Logging a note with body > 5,000 chars raises LeadTaskValidationError."""
    with app.app_context():
        lead = _make_lead(app, '6 Call St')
        svc = CallLogService()

        long_body = 'x' * 5001
        with pytest.raises(LeadTaskValidationError):
            svc.log_note(lead.id, body=long_body)


def test_note_body_exactly_5000_chars_succeeds(app):
    """Logging a note with body exactly 5,000 chars succeeds."""
    with app.app_context():
        lead = _make_lead(app, '7 Call St')
        svc = CallLogService()

        body = 'x' * 5000
        with patch(_AE_PATCH):
            entry = svc.log_note(lead.id, body=body)

        assert entry is not None
        assert entry.event_type == 'note_added'


def test_note_empty_body_raises_validation_error(app):
    """Logging a note with empty body raises LeadTaskValidationError."""
    with app.app_context():
        lead = _make_lead(app, '8 Call St')
        svc = CallLogService()

        with pytest.raises(LeadTaskValidationError):
            svc.log_note(lead.id, body='')


# ---------------------------------------------------------------------------
# call_logged timeline entry is created
# ---------------------------------------------------------------------------

def test_log_call_creates_timeline_entry(app):
    """log_call creates a call_logged timeline entry."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '9 Call St')
        svc = CallLogService()

        with patch(_AE_PATCH):
            entry = svc.log_call(lead.id, outcome='answered', duration_minutes=3, notes='Good call')

        assert entry.event_type == 'call_logged'
        assert entry.event_metadata['outcome'] == 'answered'

