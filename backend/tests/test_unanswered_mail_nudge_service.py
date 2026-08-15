"""Tests for unanswered → Direct Mail nudge helpers."""
from unittest.mock import MagicMock, patch

from app.services.unanswered_mail_nudge_service import (
    unanswered_mail_nudge_owed,
    switch_to_direct_mail_from_nudge,
)


def _lead(**kwargs):
    lead = MagicMock()
    lead.unanswered_call_count = kwargs.get('unanswered_call_count', 0)
    lead.has_phone = kwargs.get('has_phone', True)
    lead.prefer_direct_mail = kwargs.get('prefer_direct_mail', False)
    lead.unanswered_mail_nudge_dismissed_count = kwargs.get(
        'unanswered_mail_nudge_dismissed_count',
    )
    return lead


def test_nudge_owed_at_threshold():
    assert unanswered_mail_nudge_owed(_lead(unanswered_call_count=3))


def test_nudge_not_owed_below_threshold():
    assert not unanswered_mail_nudge_owed(_lead(unanswered_call_count=2))


def test_nudge_suppressed_after_keep_calling():
    assert not unanswered_mail_nudge_owed(
        _lead(
            unanswered_call_count=3,
            unanswered_mail_nudge_dismissed_count=3,
        ),
    )


def test_nudge_reopens_after_another_miss():
    assert unanswered_mail_nudge_owed(
        _lead(
            unanswered_call_count=4,
            unanswered_mail_nudge_dismissed_count=3,
        ),
    )


def test_nudge_not_owed_after_switch():
    assert not unanswered_mail_nudge_owed(
        _lead(unanswered_call_count=3, prefer_direct_mail=True),
    )


def test_switch_sets_prefer_mail_without_writing_recommended_action(app):
    """One-writer: Switch only sets prefer_direct_mail; scoring owns RA/method."""
    with app.app_context():
        from app import db
        from app.models.lead import Lead

        lead = Lead(
            property_street='Nudge Switch St',
            unanswered_call_count=3,
            has_phone=True,
            recommended_action='call_ready',
            recommended_contact_method='phone',
        )
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

        with patch(
            'app.services.unanswered_mail_nudge_service.complete_tasks_superseded_by_mail',
        ) as supersede, patch(
            'app.services.unanswered_mail_nudge_service.refresh_lead_scoring',
        ) as refresh:
            supersede.return_value = (0, [])
            refresh.return_value = None
            out = switch_to_direct_mail_from_nudge(lead_id, actor='test')

        db.session.refresh(out)
        assert out.prefer_direct_mail is True
        assert out.unanswered_mail_nudge_dismissed_count == 3
        # Must not stamp RA/method before scoring (one-writer).
        assert out.recommended_action == 'call_ready'
        assert out.recommended_contact_method == 'phone'
        refresh.assert_called_once_with(lead_id)
        supersede.assert_called_once()
