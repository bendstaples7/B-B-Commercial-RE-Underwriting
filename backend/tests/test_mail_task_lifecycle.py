"""Tests for direct-mail task lifecycle (enqueue complete, send follow-up, queue exclusion)."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.models.mail_campaign import MailCampaign
from app.models.mail_queue_item import MailQueueItem
from app.models.open_letter_config import OpenLetterConfig
from app.services.mail_campaign_service import MailCampaignService
from app.services.mail_queue_service import MailQueueService
from app.services.mail_task_lifecycle_service import (
    MAIL_FOLLOW_UP_OFFSET_DAYS,
    complete_mail_prep_tasks,
    resolve_mail_queue_status,
    schedule_mail_follow_up_task,
)
from app.services.queue_service import QueueService

USER_ID = 'test-user'


@pytest.fixture
def fernet_key():
    return Fernet.generate_key().decode()


def _make_lead(app, street, **kwargs):
    from app import db

    defaults = dict(
        lead_status='mailing_no_contact_made',
        has_phone=True,
        has_email=True,
        has_property_match=True,
        analysis_complete=True,
        follow_up_overdue=False,
        is_warm=False,
        lead_score=50.0,
        data_completeness_score=60.0,
        recommended_action='mail_ready',
        review_required=False,
        unanswered_call_count=0,
        owner_user_id=USER_ID,
        property_city='Chicago',
        property_state='IL',
        property_zip='60601',
        mailing_address='123 Main St',
        mailing_city='Chicago',
        mailing_state='IL',
        mailing_zip='60601',
    )
    defaults.update(kwargs)
    lead = Lead(property_street=street, **defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _make_task(app, lead_id, **kwargs):
    from app import db

    defaults = dict(
        task_type='add_to_mail_batch',
        title='Direct Mail 123 Main St',
        status='open',
        due_date=date.today(),
        created_by='test',
    )
    defaults.update(kwargs)
    task = LeadTask(lead_id=lead_id, **defaults)
    db.session.add(task)
    db.session.commit()
    return task


class TestCompleteMailPrepTasks:
    def test_completes_open_add_to_mail_batch_tasks(self, app):
        with app.app_context():
            lead = _make_lead(app, '1 Mail Prep St')
            task = _make_task(app, lead.id)

            count = complete_mail_prep_tasks(lead.id, actor=USER_ID, commit=True)

            assert count == 1
            db_task = LeadTask.query.get(task.id)
            assert db_task.status == 'completed'
            assert db_task.completed_at is not None


class TestEnqueueCompletesMailPrepTasks:
    def test_enqueue_completes_add_to_mail_batch_task(self, app):
        with app.app_context():
            lead = _make_lead(app, '2 Enqueue Complete St')
            task = _make_task(app, lead.id)

            with patch('app.services.mail_queue_service.refresh_leads_after_mail_task_changes'):
                result = MailQueueService().enqueue_leads([lead.id], USER_ID)

            assert result['added'] == 1
            db_task = LeadTask.query.get(task.id)
            assert db_task.status == 'completed'
            assert Lead.query.get(lead.id).up_next_to_mail is True


class TestTodaysActionMailAwaitingExclusion:
    def test_excludes_lead_with_open_task_when_up_next_to_mail(self, app):
        with app.app_context():
            lead = _make_lead(app, '3 Awaiting Mail St', up_next_to_mail=True)
            _make_task(app, lead.id)

            svc = QueueService()
            rows, _total = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_includes_lead_with_open_task_when_not_awaiting_mail(self, app):
        with app.app_context():
            lead = _make_lead(app, '4 Actionable St', up_next_to_mail=False)
            _make_task(app, lead.id, task_type='custom', title='Call owner')

            svc = QueueService()
            rows, _total = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id in ids


class TestScheduleMailFollowUpTask:
    def test_creates_follow_up_due_seven_days_after_send(self, app):
        with app.app_context():
            from app import db

            lead = _make_lead(app, '5 Follow Up St')
            sent_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

            task = schedule_mail_follow_up_task(
                lead=lead,
                sent_at=sent_at,
                actor=USER_ID,
                campaign_id=99,
            )
            db.session.commit()

            assert task is not None
            assert task.task_type == 'call_owner_today'
            assert task.due_date == sent_at.date() + timedelta(days=MAIL_FOLLOW_UP_OFFSET_DAYS)
            assert 'Follow up after mailer' in task.title

    def test_skips_duplicate_follow_up(self, app):
        with app.app_context():
            lead = _make_lead(app, '6 Dup Follow Up St')
            sent_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            due = sent_at.date() + timedelta(days=MAIL_FOLLOW_UP_OFFSET_DAYS)

            existing = LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up after mailer — 6 Dup Follow Up St',
                status='open',
                due_date=due,
                created_by='test',
            )
            from app import db
            db.session.add(existing)
            db.session.commit()

            task = schedule_mail_follow_up_task(
                lead=lead,
                sent_at=sent_at,
                actor=USER_ID,
            )
            assert task is None


class TestResolveMailQueueStatus:
    def test_returns_queued_when_item_queued(self, app):
        from app import db

        with app.app_context():
            lead = _make_lead(app, '7 Queued St')
            db.session.add(MailQueueItem(lead_id=lead.id, user_id=USER_ID, status='queued'))
            db.session.commit()
            assert resolve_mail_queue_status(lead) == 'queued'

    def test_returns_sent_recently_from_mailer_history(self, app):
        with app.app_context():
            lead = _make_lead(app, '8 Sent St')
            lead.mailer_history = [{
                'campaign_id': 1,
                'sent_at': datetime.now(timezone.utc).isoformat(),
            }]
            from app import db
            db.session.commit()
            assert resolve_mail_queue_status(lead) == 'sent_recently'


class TestSubmitCampaignFollowUp:
    def test_submit_campaign_schedules_follow_up_task(self, app, fernet_key, monkeypatch):
        from app import db
        from app.services.open_letter_client_service import OpenLetterClientService

        monkeypatch.setenv('HUBSPOT_ENCRYPTION_KEY', fernet_key)

        with app.app_context():
            lead = _make_lead(app, '9 Campaign St')
            db.session.add(MailQueueItem(lead_id=lead.id, user_id=USER_ID, status='queued'))
            token = OpenLetterClientService.encrypt_token('test-token')
            config = OpenLetterConfig(
                user_id=USER_ID,
                encrypted_api_token=token,
                batch_minimum=1,
                default_product_id='prod-1',
                default_template_id='tmpl-1',
            )
            campaign = MailCampaign(
                status='pending',
                lead_count=1,
                product_id='prod-1',
                template_id='tmpl-1',
                created_by=USER_ID,
            )
            db.session.add_all([config, campaign])
            db.session.flush()
            item = MailQueueItem.query.filter_by(lead_id=lead.id, status='queued').first()
            item.campaign_id = campaign.id
            db.session.commit()

            mock_client = MagicMock()
            mock_client.place_order.return_value = {
                'data': {'id': 'olc-1', 'cost': 1.25},
            }

            cfg_svc = MagicMock()
            cfg_svc.require_config.return_value = config
            cfg_svc.get_client.return_value = mock_client

            svc = MailCampaignService()
            svc._config_service = cfg_svc

            with patch('app.services.mail_campaign_service.refresh_leads_after_mail_task_changes'):
                svc.submit_campaign(campaign.id)

            follow_up = LeadTask.query.filter(
                LeadTask.lead_id == lead.id,
                LeadTask.status == 'open',
                LeadTask.task_type == 'call_owner_today',
            ).first()
            assert follow_up is not None
            assert 'Follow up after mailer' in follow_up.title
