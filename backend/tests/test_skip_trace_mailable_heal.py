"""Tests for SkipTraceMailableHealService."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app import db
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.services.skip_trace_mailable_heal_service import SkipTraceMailableHealService


def _mailable_skip_lead(**kwargs) -> Lead:
    defaults = dict(
        property_street='4301 N Saint Louis',
        property_city='Chicago',
        property_state='IL',
        property_zip='60618',
        mailing_address='6434 N Oakley Ave',
        mailing_city='Chicago',
        mailing_state='IL',
        mailing_zip='60645',
        owner_user_id='user-heal',
        lead_status='skip_trace',
        needs_skip_trace=True,
        lead_category='residential',
        most_recent_sale='1/7/2000',
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.flush()
    return lead


def test_heal_promotes_mailable_skip_trace_and_completes_handoff(app):
    with app.app_context():
        lead = _mailable_skip_lead()
        task = LeadTask(
            lead_id=lead.id,
            task_type='skip_trace_owner',
            title='Awaiting skip trace',
            status='open',
            due_date=None,
            workflow_key='awaiting_skip_trace_handoff',
            created_by='unif_st_20260723',
        )
        db.session.add(task)
        db.session.commit()

        with patch(
            'app.services.skip_trace_mailable_heal_service.complete_native_task_mirror',
        ) as mirror:
            result = SkipTraceMailableHealService().heal_lead(
                lead, commit=True, rescore=False,
            )
            mirror.assert_called_once()

        assert result['healed'] is True
        assert result['promoted'] is True
        assert result['needs_cleared'] is True

        db.session.refresh(lead)
        db.session.refresh(task)
        assert lead.lead_status == 'mailing_no_contact_made'
        assert lead.needs_skip_trace is False
        assert task.status == 'completed'


def test_heal_skips_recently_sold(app):
    with app.app_context():
        recent = (date.today() - timedelta(days=30)).isoformat()
        lead = _mailable_skip_lead(most_recent_sale=recent)
        db.session.commit()

        assert SkipTraceMailableHealService().is_heal_candidate(lead) is False
        result = SkipTraceMailableHealService().heal_lead(lead, commit=True, rescore=False)
        assert result['healed'] is False
        assert result['reason'] == 'not_eligible'


def test_heal_skips_incomplete_mailing(app):
    with app.app_context():
        lead = _mailable_skip_lead(
            mailing_address='6434 N Oakley Ave',
            mailing_city=None,
            mailing_state='IL',
            mailing_zip='60645',
        )
        db.session.commit()

        assert SkipTraceMailableHealService().is_heal_candidate(lead) is False


def test_heal_skips_manual_research_task_unless_include_manual(app):
    with app.app_context():
        lead = _mailable_skip_lead()
        task = LeadTask(
            lead_id=lead.id,
            task_type='skip_trace_owner',
            title='Research phones',
            status='open',
            workflow_key='manual_skip_research',
            created_by='user',
        )
        db.session.add(task)
        db.session.commit()

        svc = SkipTraceMailableHealService()
        assert svc.is_heal_candidate(lead) is False
        assert svc.is_heal_candidate(lead, include_manual=True) is True

        result = svc.heal_lead(lead, commit=True, rescore=False, include_manual=True)
        assert result['healed'] is True
        db.session.refresh(task)
        assert task.status == 'completed'


def test_heal_all_dry_run_does_not_write(app):
    with app.app_context():
        lead = _mailable_skip_lead(property_street='Unique Heal Dry Run St')
        task = LeadTask(
            lead_id=lead.id,
            task_type='skip_trace_owner',
            title='Awaiting skip trace',
            status='open',
            workflow_key='awaiting_skip_trace_handoff',
            created_by='test',
        )
        db.session.add(task)
        db.session.commit()

        summary = SkipTraceMailableHealService().heal_all(commit=False)
        assert summary['mode'] == 'dry-run'
        assert summary['healed_count'] == 0
        assert any(r['lead_id'] == lead.id for r in summary['results'])

        db.session.refresh(lead)
        db.session.refresh(task)
        assert lead.lead_status == 'skip_trace'
        assert lead.needs_skip_trace is True
        assert task.status == 'open'
