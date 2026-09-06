"""Quarterly mail cadence cooldown (last mailed + 90 days)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.action_eligibility import (
    REASON_MAIL_CADENCE,
    evaluate_add_to_mail_batch,
)
from app.services.lead_scoring_engine import (
    LeadScoringEngine,
    _mail_cadence_block_outcome,
)
from app.services.mail_task_lifecycle_service import (
    MAIL_REMATCH_OFFSET_DAYS,
    heal_mail_cadence_cooldown,
    mail_cadence_eligible_date_from_last_mailed,
    mail_rematch_due_date,
    resolve_mail_eligibility_hold,
)
from app.services.queue_service import QueueService


def test_mail_cadence_eligible_date_within_window():
    sent = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    eligible = mail_cadence_eligible_date_from_last_mailed(
        sent,
        today=date(2026, 9, 5),
    )
    assert eligible == date(2026, 7, 28) + timedelta(days=MAIL_REMATCH_OFFSET_DAYS)
    assert eligible == date(2026, 10, 26)


def test_mail_cadence_eligible_date_clears_on_due_day():
    sent = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    due = date(2026, 7, 28) + timedelta(days=MAIL_REMATCH_OFFSET_DAYS)
    assert mail_cadence_eligible_date_from_last_mailed(sent, today=due) is None


def test_mail_rematch_due_matches_cadence():
    sent = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc)
    assert mail_rematch_due_date(sent, None) == mail_cadence_eligible_date_from_last_mailed(
        sent,
        today=date(2026, 8, 1),
    )


def test_resolve_mail_hold_prefers_later_date():
    lead = SimpleNamespace(
        most_recent_sale=None,
        acquisition_date=None,
        id=1,
    )
    with patch(
        'app.services.mail_task_lifecycle_service.recent_sale_mail_eligible_date',
        return_value=date(2026, 11, 1),
    ), patch(
        'app.services.mail_task_lifecycle_service.mail_cadence_eligible_date',
        return_value=date(2026, 10, 26),
    ):
        hold_date, reason = resolve_mail_eligibility_hold(lead)
    assert hold_date == date(2026, 11, 1)
    assert reason == 'recently_sold'


def test_scoring_blocks_mail_ready_during_cadence(app):
    with app.app_context():
        lead = Lead(
            property_street='90 Cadence Cool St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='90 Cadence Cool St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='test-owner',
            lead_status='mailing_no_contact_made',
            lead_category='residential',
            lead_score=90.0,
            motivation_score=20.0,
            recommended_action='mail_ready',
        )
        db.session.add(lead)
        db.session.flush()
        db.session.add(
            LeadTimelineEntry(
                lead_id=lead.id,
                event_type='mail_sent',
                occurred_at=datetime.now(timezone.utc) - timedelta(days=30),
                source='system',
                actor='test',
                summary='Mail sent',
            )
        )
        db.session.commit()

        blocked = _mail_cadence_block_outcome(lead)
        assert blocked is not None
        assert blocked[0] == 'nurture'
        assert blocked[1] == 'mail_cadence_cooldown'

        with patch(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            return_value=False,
        ), patch(
            'app.services.lead_scoring_engine._resolve_crm_flags',
            return_value=(False, False, True),
        ), patch(
            'app.services.lead_scoring_engine.is_mailable_lead',
            return_value=True,
        ), patch(
            'app.services.lead_scoring_engine._has_mailing_address',
            return_value=True,
        ), patch(
            'app.services.scoring_rubric.is_recently_sold',
            return_value=False,
        ):
            action, rule, _signals = LeadScoringEngine().evaluate_recommended_action(
                lead,
                total_score=50.0,
                data_quality_score=50.0,
                score_tier='C',
            )
        assert action == 'nurture'
        assert rule == 'mail_cadence_cooldown'


def test_mail_candidates_exclude_recently_mailed(app):
    with app.app_context():
        lead = Lead(
            property_street='91 Cadence Queue St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='91 Cadence Queue St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='test-owner',
            lead_status='mailing_no_contact_made',
            lead_category='residential',
            lead_score=95.0,
            motivation_score=20.0,
            recommended_action='mail_ready',
        )
        db.session.add(lead)
        db.session.flush()
        db.session.add(
            LeadTimelineEntry(
                lead_id=lead.id,
                event_type='mail_sent',
                occurred_at=datetime.now(timezone.utc) - timedelta(days=40),
                source='system',
                actor='test',
                summary='Mail sent',
            )
        )
        db.session.commit()

        rows, _total = QueueService(owner_user_id='test-owner').get_mail_candidates(
            'test-owner',
        )
        assert lead.id not in [r['id'] for r in rows]


def test_enqueue_rejects_mail_cadence(app):
    from app.services.mail_queue_service import MailQueueService

    with app.app_context():
        lead = Lead(
            property_street='92 Cadence Enq St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='92 Cadence Enq St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='test-user',
            lead_status='mailing_no_contact_made',
            lead_category='residential',
            lead_score=90.0,
            recommended_action='mail_ready',
        )
        db.session.add(lead)
        db.session.flush()
        db.session.add(
            LeadTimelineEntry(
                lead_id=lead.id,
                event_type='mail_sent',
                occurred_at=datetime.now(timezone.utc) - timedelta(days=20),
                source='system',
                actor='test',
                summary='Mail sent',
            )
        )
        db.session.commit()
        lead_id = lead.id

        result = MailQueueService().enqueue_leads([lead_id], 'test-user')
        assert result['added'] == 0
        assert result['results'][0]['status'] == 'mail_cadence'
        assert result['results'][0]['mail_eligible_date']


def test_heal_rescores_stale_mail_ready(app):
    with app.app_context():
        lead = Lead(
            property_street='93 Cadence Heal St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='93 Cadence Heal St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='test-owner',
            lead_status='mailing_no_contact_made',
            lead_category='residential',
            lead_score=80.0,
            recommended_action='mail_ready',
        )
        db.session.add(lead)
        db.session.flush()
        db.session.add(
            LeadTimelineEntry(
                lead_id=lead.id,
                event_type='mail_sent',
                occurred_at=datetime.now(timezone.utc) - timedelta(days=15),
                source='system',
                actor='test',
                summary='Mail sent',
            )
        )
        db.session.commit()
        lead_id = lead.id

        result = heal_mail_cadence_cooldown(commit=True)
        assert lead_id in result['affected_lead_ids']
        refreshed = Lead.query.get(lead_id)
        assert refreshed.recommended_action != 'mail_ready'


def test_evaluate_add_to_mail_batch_cadence_message():
    result = evaluate_add_to_mail_batch(
        mail_eligible=False,
        mail_ineligible_reason='mail_cadence',
        mail_eligible_date=date(2026, 10, 26),
    )
    assert result.reason_code == REASON_MAIL_CADENCE
    assert '2026-10-26' in (result.message or '')
