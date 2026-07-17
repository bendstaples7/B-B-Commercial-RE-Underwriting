"""Tests for next-action invariant after last open LeadTask is cleared."""
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app import db
from app.models import Lead, LeadTask
from app.services.lead_task_service import LeadTaskService
from app.services.next_action_invariant import (
    PARKED_LEAD_STATUSES,
    ensure_next_action_after_task_change,
)


def _make_lead(app, street: str, **kwargs) -> Lead:
    with app.app_context():
        lead = Lead(
            property_street=street,
            property_city='Chicago',
            property_state='IL',
            lead_status=kwargs.pop('lead_status', 'mailing_no_contact_made'),
            recommended_action=kwargs.pop('recommended_action', 'nurture'),
            owner_user_id='test-user',
            **kwargs,
        )
        db.session.add(lead)
        db.session.commit()
        db.session.refresh(lead)
        return lead


def _make_open_task(lead_id: int, title: str = 'Follow up') -> LeadTask:
    task = LeadTask(
        lead_id=lead_id,
        task_type='custom',
        title=title,
        status='open',
        due_date=date.today(),
        created_by='test',
    )
    db.session.add(task)
    db.session.commit()
    db.session.refresh(task)
    return task


class TestNextActionInvariant:
    def test_refresh_when_active_lead_has_no_open_tasks(self, app):
        with app.app_context():
            lead = _make_lead(app, '1 Invariant St')
            with patch(
                'app.services.lead_refresh.refresh_lead_scoring',
            ) as mock_refresh:
                ensure_next_action_after_task_change(lead.id)
                mock_refresh.assert_called_once_with(lead.id)

    def test_skips_when_open_task_remains(self, app):
        with app.app_context():
            lead = _make_lead(app, '2 Invariant St')
            _make_open_task(lead.id)
            with patch(
                'app.services.lead_refresh.refresh_lead_scoring',
            ) as mock_refresh:
                ensure_next_action_after_task_change(lead.id)
                mock_refresh.assert_not_called()

    @pytest.mark.parametrize('status', sorted(PARKED_LEAD_STATUSES))
    def test_skips_parked_statuses(self, app, status):
        with app.app_context():
            lead = _make_lead(app, f'3 {status} St', lead_status=status)
            with patch(
                'app.services.lead_refresh.refresh_lead_scoring',
            ) as mock_refresh:
                ensure_next_action_after_task_change(lead.id)
                mock_refresh.assert_not_called()

    def test_complete_last_task_skips_invariant_when_action_engine_succeeds(self, app):
        with app.app_context():
            lead = _make_lead(app, '4 Complete St')
            task = _make_open_task(lead.id)
            with patch(
                'app.services.next_action_invariant.ensure_next_action_after_task_change',
            ) as mock_ensure:
                with patch(
                    'app.services.action_engine_service.ActionEngineService.recompute_and_persist',
                ):
                    LeadTaskService().complete(task.id, lead.id, actor='tester')
                mock_ensure.assert_not_called()

    def test_complete_last_task_invokes_invariant_when_action_engine_fails(self, app):
        with app.app_context():
            lead = _make_lead(app, '5 Complete St')
            task = _make_open_task(lead.id)
            with patch(
                'app.services.next_action_invariant.ensure_next_action_after_task_change',
            ) as mock_ensure:
                with patch(
                    'app.services.action_engine_service.ActionEngineService.recompute_and_persist',
                    side_effect=RuntimeError('scoring failed'),
                ):
                    LeadTaskService().complete(task.id, lead.id, actor='tester')
                mock_ensure.assert_called_once_with(lead.id)
