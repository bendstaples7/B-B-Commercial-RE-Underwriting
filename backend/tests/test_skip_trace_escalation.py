"""Tests for multi-source skip-trace escalation after invalid mail."""
from __future__ import annotations

from copy import deepcopy

from app.models.skip_trace_config import DEFAULT_SKIP_TRACE_SOURCES
from app.services.skip_trace_escalation_service import SkipTraceEscalationService
from app.services.skip_trace_source_registry import SkipTraceSourceRegistry


def test_registry_seeds_manual_default(app):
    with app.app_context():
        sources = SkipTraceSourceRegistry().list_sources(enabled_only=True)
        assert any(s['id'] == 'manual_default' for s in sources)


def test_one_source_ladder_exhausts_on_second_invalid(app):
    with app.app_context():
        from app import db
        from app.models import Lead
        from app.models.skip_trace_attempt import SkipTraceAttempt

        SkipTraceSourceRegistry().save_sources(deepcopy(DEFAULT_SKIP_TRACE_SOURCES))
        lead = Lead(
            property_street='1 Exhaust St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
            lead_status='mailing_no_contact_made',
            skip_trace_next_source_id='manual_default',
        )
        db.session.add(lead)
        db.session.commit()

        svc = SkipTraceEscalationService()
        svc.record_source_completed(lead.id, source_id='manual_default', commit=True)

        first = svc.escalate_from_invalid_mail(lead.id, actor='user-1', commit=True)
        assert first['action'] == 'exhausted'

        db.session.refresh(lead)
        assert lead.skip_trace_exhausted_at is not None
        assert SkipTraceAttempt.query.filter_by(
            lead_id=lead.id, outcome='failed_address',
        ).count() >= 1

        again = svc.escalate_from_invalid_mail(lead.id, actor='user-1', commit=True)
        assert again['action'] == 'noop'
        assert again['reason'] == 'already_exhausted'


def test_two_source_ladder_assigns_second_after_first_fails(app):
    with app.app_context():
        from app import db
        from app.models import Lead, LeadTask

        registry = SkipTraceSourceRegistry()
        registry.save_sources([
            {'id': 'source_a', 'label': 'Source A', 'enabled': True, 'kind': 'manual'},
            {'id': 'source_b', 'label': 'Source B', 'enabled': True, 'kind': 'manual'},
        ])
        db.session.commit()

        lead = Lead(
            property_street='2 Ladder St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
            lead_status='mailing_no_contact_made',
        )
        db.session.add(lead)
        db.session.commit()

        svc = SkipTraceEscalationService()
        svc.record_source_completed(lead.id, source_id='source_a', commit=True)

        result = svc.escalate_from_invalid_mail(lead.id, actor='user-1', commit=True)
        assert result['action'] == 'assigned_next_source'
        assert result['source_id'] == 'source_b'

        db.session.refresh(lead)
        assert lead.lead_status == 'skip_trace'
        assert lead.skip_trace_next_source_id == 'source_b'
        assert lead.skip_trace_exhausted_at is None
        task = LeadTask.query.filter_by(
            lead_id=lead.id, task_type='skip_trace_owner', status='open',
        ).first()
        assert task is not None
        assert 'Source B' in (task.title or '')

        svc.record_source_completed(lead.id, source_id='source_b', commit=True)
        exhausted = svc.escalate_from_invalid_mail(lead.id, actor='user-1', commit=True)
        assert exhausted['action'] == 'exhausted'


def test_invalid_mail_with_no_prior_complete_assigns_first_source(app):
    with app.app_context():
        from app import db
        from app.models import Lead

        SkipTraceSourceRegistry().save_sources(deepcopy(DEFAULT_SKIP_TRACE_SOURCES))
        db.session.commit()

        lead = Lead(
            property_street='3 Fresh St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
            lead_status='mailing_no_contact_made',
        )
        db.session.add(lead)
        db.session.commit()

        svc = SkipTraceEscalationService()
        result = svc.escalate_from_invalid_mail(lead.id, actor='user-1', commit=True)
        assert result['action'] == 'assigned_next_source'
        assert result['source_id'] == 'manual_default'
        db.session.refresh(lead)
        assert lead.lead_status == 'skip_trace'


def test_idempotent_when_already_escalated(app):
    with app.app_context():
        from app import db
        from app.models import Lead

        SkipTraceSourceRegistry().save_sources(deepcopy(DEFAULT_SKIP_TRACE_SOURCES))
        db.session.commit()

        lead = Lead(
            property_street='4 Idem St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
            lead_status='mailing_no_contact_made',
        )
        db.session.add(lead)
        db.session.commit()

        svc = SkipTraceEscalationService()
        first = svc.escalate_from_invalid_mail(lead.id, actor='user-1', commit=True)
        assert first['action'] == 'assigned_next_source'
        second = svc.escalate_from_invalid_mail(lead.id, actor='user-1', commit=True)
        assert second['action'] == 'noop'
        assert second['reason'] == 'already_escalated'


def test_escalation_rolls_back_when_move_fails(app):
    with app.app_context():
        from unittest.mock import patch

        from app import db
        from app.models import Lead
        from app.models.skip_trace_attempt import SkipTraceAttempt

        SkipTraceSourceRegistry().save_sources(deepcopy(DEFAULT_SKIP_TRACE_SOURCES))
        db.session.commit()

        lead = Lead(
            property_street='5 Rollback St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
            lead_status='mailing_no_contact_made',
        )
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

        with patch(
            'app.services.skip_trace_enqueue.SkipTraceEnqueue.move_to_skip_trace',
            side_effect=RuntimeError('boom'),
        ):
            result = SkipTraceEscalationService().escalate_from_invalid_mail(
                lead_id, actor='user-1', commit=True,
            )

        assert result['action'] == 'move_failed'
        db.session.expire_all()
        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.lead_status == 'mailing_no_contact_made'
        assert refreshed.skip_trace_next_source_id is None
        assert SkipTraceAttempt.query.filter_by(lead_id=lead_id).count() == 0
