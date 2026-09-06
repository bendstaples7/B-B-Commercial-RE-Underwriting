"""Quarterly mail cadence cooldown (last mailed + 90 days)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry, Task
from app.services.action_eligibility import (
    REASON_MAIL_CADENCE,
    evaluate_add_to_mail_batch,
)
from app.services.lead_scoring_engine import (
    LeadScoringEngine,
    _apply_owner_mail_gate,
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
            action, rule, signals = LeadScoringEngine().evaluate_recommended_action(
                lead,
                total_score=50.0,
                data_quality_score=50.0,
                score_tier='C',
            )
        assert action == 'nurture'
        assert rule == 'mail_cadence_cooldown'
        refined, method = LeadScoringEngine()._apply_outreach_method(
            lead,
            action,
            signals,
            winning_rule=rule,
        )
        assert refined == 'nurture'
        assert method is None


def test_tier_a_non_mailable_cadence_keeps_phone_fallback():
    lead = SimpleNamespace(
        id=9001,
        lead_status='mailing_no_contact_made',
        lead_category='residential',
        do_not_contact=False,
        follow_up_overdue=False,
        is_warm=False,
        property_street='9001 Callable Cooldown St',
        motivation_score=20.0,
        acquisition_date=None,
        most_recent_sale=None,
    )

    with patch(
        'app.services.scoring_rubric.is_recently_sold',
        return_value=False,
    ), patch(
        'app.services.scoring_rubric.contacts_need_post_hold_verification',
        return_value=False,
    ), patch(
        'app.services.lead_scoring_engine._resolve_crm_flags',
        return_value=(True, False, True),
    ), patch(
        'app.services.lead_scoring_engine._mail_work_in_flight',
        return_value=False,
    ), patch(
        'app.services.lead_scoring_engine._count_open_tasks',
        return_value=0,
    ), patch(
        'app.services.lead_scoring_engine._has_overdue_lead_task',
        return_value=False,
    ), patch(
        'app.services.lead_scoring_engine.is_mailable_lead',
        return_value=False,
    ), patch(
        'app.services.lead_scoring_engine._mail_cadence_block_outcome',
        return_value=('nurture', 'mail_cadence_cooldown', {}),
    ):
        action, rule, signals = LeadScoringEngine.evaluate_recommended_action(
            lead,
            total_score=90.0,
            data_quality_score=80.0,
            score_tier='A',
        )
        assert action == 'mail_ready'

        refined, method = LeadScoringEngine()._apply_outreach_method(
            lead,
            action,
            signals,
            winning_rule=rule,
        )
        refined, method, rule, _signals = _apply_owner_mail_gate(
            lead,
            refined,
            method,
            rule,
            signals,
        )

    assert refined == 'call_ready'
    assert method == 'phone'
    assert rule == 'incomplete_owner_mail_phone_fallback'


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
        old_send = LeadTimelineEntry(
            lead_id=lead.id,
            event_type='mail_sent',
            occurred_at=datetime.now(timezone.utc) - timedelta(days=120),
            source='system',
            actor='test',
            summary='Mail sent',
        )
        db.session.add(old_send)
        db.session.commit()

        rows, _total = QueueService(owner_user_id='test-owner').get_mail_candidates(
            'test-owner',
        )
        assert lead.id in [r['id'] for r in rows]

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


def test_enqueue_batches_mail_cadence_lookup_for_authorized_leads(app):
    from app.services.mail_queue_service import MailQueueService

    with app.app_context():
        owned = Lead(
            property_street='92 Cadence Batch Owned St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='92 Cadence Batch Owned St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='test-user',
            lead_status='mailing_no_contact_made',
            lead_category='residential',
            lead_score=90.0,
            recommended_action='mail_ready',
        )
        other = Lead(
            property_street='92 Cadence Batch Other St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='92 Cadence Batch Other St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='other-user',
            lead_status='mailing_no_contact_made',
            lead_category='residential',
            lead_score=90.0,
            recommended_action='mail_ready',
        )
        db.session.add_all([owned, other])
        db.session.commit()

        with patch(
            'app.services.mail_queue_service.get_last_mailed_at_by_lead_ids',
            return_value={},
        ) as last_mailed, patch(
            'app.services.mail_queue_service.refresh_leads_after_mail_task_changes',
        ), patch(
            'app.services.mail_queue_service._refresh_rejected_leads',
        ):
            result = MailQueueService().enqueue_leads(
                [owned.id, other.id],
                'test-user',
            )

        assert result['added'] == 1
        assert result['skipped'] == 1
        last_mailed.assert_called_once_with([owned.id])


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


def test_heal_aligns_canonical_rematch_with_old_title_mirror(app):
    with app.app_context():
        sent_at = datetime.now(timezone.utc) - timedelta(days=120)
        expected = sent_at.date() + timedelta(days=MAIL_REMATCH_OFFSET_DAYS)
        lead = Lead(
            property_street='94 Cadence Rematch St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='94 Cadence Rematch St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='test-owner',
            lead_status='mailing_no_contact_made',
            lead_category='residential',
            lead_score=80.0,
            recommended_action='nurture',
        )
        db.session.add(lead)
        db.session.flush()
        rematch = LeadTask(
            lead_id=lead.id,
            task_type='add_to_mail_batch',
            title='Owner edited display title',
            status='open',
            due_date=None,
            created_by='test',
        )
        mirror = Task(
            lead_id=lead.id,
            task_type='add_to_mail_batch',
            title='Owner edited display title',
            status='open',
            due_date=None,
        )
        db.session.add_all([
            rematch,
            mirror,
            LeadTimelineEntry(
                lead_id=lead.id,
                event_type='mail_sent',
                occurred_at=sent_at,
                source='system',
                actor='test',
                summary='Mail sent',
            ),
        ])
        db.session.commit()

        result = heal_mail_cadence_cooldown(commit=True)

        assert lead.id in result['affected_lead_ids']
        assert result['rematch_dues_fixed'] == 1
        assert rematch.due_date == expected
        assert rematch.task_type == 'add_to_mail_batch'
        assert 'Add to next mailer' in rematch.title
        assert mirror.due_date is not None
        assert mirror.due_date.date() == expected
        assert mirror.title == rematch.title


def test_heal_commit_false_keeps_rescore_uncommitted(app):
    with app.app_context():
        lead = Lead(
            property_street='95 Cadence No Commit St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='95 Cadence No Commit St',
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
                occurred_at=datetime.now(timezone.utc) - timedelta(days=10),
                source='system',
                actor='test',
                summary='Mail sent',
            )
        )
        db.session.commit()

        with patch(
            'app.services.lead_scoring_engine.LeadScoringEngine.score_and_persist',
            return_value=None,
        ) as score:
            result = heal_mail_cadence_cooldown(commit=False)

        assert result['rescored'] == 1
        score.assert_called_once_with(lead.id, commit=False)
        db.session.rollback()


def test_evaluate_add_to_mail_batch_cadence_message():
    result = evaluate_add_to_mail_batch(
        mail_eligible=False,
        mail_ineligible_reason='mail_cadence',
        mail_eligible_date=date(2026, 10, 26),
    )
    assert result.reason_code == REASON_MAIL_CADENCE
    assert '2026-10-26' in (result.message or '')
