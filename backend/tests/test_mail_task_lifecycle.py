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
    adjust_earliest_task_for_recent_sale,
    complete_mail_prep_tasks,
    complete_tasks_superseded_by_mail,
    count_superseded_tasks_for_lead,
    create_pending_mail_follow_up_task,
    find_mail_awaiting_lead_ids,
    reconcile_recent_sale_mail_tasks,
    reconcile_recent_sale_mail_tasks_for_lead,
    recent_sale_mail_eligible_date,
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


class TestRecentSaleMailReconciliation:
    def test_manual_adjustment_moves_earliest_task_without_changing_it(self, app):
        from app import db

        with app.app_context():
            sale_date = date.today() - timedelta(days=45)
            lead = _make_lead(
                app,
                '0 Recent Sale Manual Adjust St',
                acquisition_date=sale_date,
            )
            task = LeadTask(
                lead_id=lead.id,
                task_type='research_missing_pin',
                title='Research the existing PIN',
                status='open',
                due_date=date.today(),
                created_by='test',
            )
            db.session.add(task)
            db.session.commit()

            result = adjust_earliest_task_for_recent_sale(
                lead,
                actor='test',
            )

            refreshed = db.session.get(LeadTask, task.id)
            assert result['task_id'] == task.id
            assert result['task_created'] is False
            assert refreshed.title == 'Research the existing PIN'
            assert refreshed.task_type == 'research_missing_pin'
            assert refreshed.due_date == sale_date + timedelta(days=730)
            assert LeadTask.query.filter_by(lead_id=lead.id).count() == 1

    def test_manual_adjustment_creates_task_when_none_exists(self, app):
        from app import db

        with app.app_context():
            sale_date = date.today() - timedelta(days=20)
            lead = _make_lead(
                app,
                '0 Recent Sale Manual Create St',
                acquisition_date=sale_date,
            )

            result = adjust_earliest_task_for_recent_sale(
                lead,
                actor='test',
            )

            task = db.session.get(LeadTask, result['task_id'])
            assert result['task_created'] is True
            assert task.task_type == 'skip_trace_owner'
            assert task.due_date == sale_date + timedelta(days=730)

    def test_manual_adjustment_rejects_stale_explicit_task(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                '0 Recent Sale Stale Task St',
                acquisition_date=date.today() - timedelta(days=20),
            )
            earliest = _make_task(app, lead.id)

            with pytest.raises(ValueError, match='Selected task is not open'):
                adjust_earliest_task_for_recent_sale(
                    lead,
                    actor='test',
                    task_id=earliest.id + 9999,
                )

            assert LeadTask.query.get(earliest.id).due_date == date.today()

    def test_manual_adjustment_rejects_terminal_lead_without_task(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                '0 Recent Sale Terminal St',
                acquisition_date=date.today() - timedelta(days=20),
                lead_status='deal_lost',
            )

            with pytest.raises(ValueError, match='cannot be moved'):
                adjust_earliest_task_for_recent_sale(lead, actor='test')

            assert LeadTask.query.filter_by(lead_id=lead.id).count() == 0

    def test_bulk_dry_run_reports_changes_without_persisting(self, app):
        from app import db

        with app.app_context():
            sale_date = date.today() - timedelta(days=20)
            lead = _make_lead(
                app,
                '0 Recent Sale Dry Run St',
                acquisition_date=sale_date,
            )
            task = _make_task(app, lead.id)
            queued_item = MailQueueItem(
                lead_id=lead.id,
                user_id=USER_ID,
                status='queued',
            )
            db.session.add(queued_item)
            db.session.commit()

            with patch(
                'app.services.mail_task_lifecycle_service.sql_not_recently_sold',
                return_value=Lead.acquisition_date <= date.today() - timedelta(days=730),
            ):
                result = reconcile_recent_sale_mail_tasks(
                    actor='test',
                    commit=False,
                )

            assert result['affected_lead_count'] == 1
            assert result['rescheduled_task_count'] == 1
            assert result['skip_trace_scheduled_count'] == 1
            assert result['results'][0]['removed_queue_item_count'] == 1
            assert db.session.get(LeadTask, task.id).due_date == date.today()
            assert db.session.get(MailQueueItem, queued_item.id).status == 'queued'
            assert LeadTask.query.filter_by(
                lead_id=lead.id,
                task_type='skip_trace_owner',
            ).count() == 0

    def test_bulk_reconciliation_commits_queue_only_change(self, app):
        from app import db

        with app.app_context():
            sale_date = date.today() - timedelta(days=20)
            eligible_date = sale_date + timedelta(days=730)
            lead = _make_lead(
                app,
                '0 Recent Sale Queue Only St',
                acquisition_date=sale_date,
                lead_status='skip_trace',
            )
            hold_task = LeadTask(
                lead_id=lead.id,
                task_type='skip_trace_owner',
                title='Recent-sale hold ended — verify new owner and contact information',
                status='open',
                due_date=eligible_date,
                workflow_key='recent_sale_hold',
                created_by='test',
            )
            queued_item = MailQueueItem(
                lead_id=lead.id,
                user_id=USER_ID,
                status='queued',
            )
            db.session.add_all([hold_task, queued_item])
            db.session.commit()

            with patch(
                'app.services.mail_task_lifecycle_service.sql_not_recently_sold',
                return_value=Lead.acquisition_date <= date.today() - timedelta(days=730),
            ), patch(
                'app.services.mail_task_lifecycle_service.refresh_leads_after_mail_task_changes',
            ):
                result = reconcile_recent_sale_mail_tasks(actor='test')

            assert result['affected_lead_count'] == 1
            assert result['rescheduled_task_count'] == 0
            assert result['skip_trace_scheduled_count'] == 0
            assert db.session.get(MailQueueItem, queued_item.id).status == 'removed'

    def test_bulk_reconciliation_excludes_terminal_recent_sale(self, app):
        from app import db

        with app.app_context():
            terminal = _make_lead(
                app,
                '0 Recent Sale Excluded Terminal St',
                acquisition_date=date.today() - timedelta(days=20),
                lead_status='deal_lost',
            )
            task = _make_task(app, terminal.id)

            with patch(
                'app.services.mail_task_lifecycle_service.sql_not_recently_sold',
                return_value=Lead.acquisition_date <= date.today() - timedelta(days=730),
            ):
                result = reconcile_recent_sale_mail_tasks(
                    actor='test',
                    commit=False,
                )

            assert result['affected_lead_count'] == 0
            assert db.session.get(LeadTask, task.id).due_date == date.today()

    def test_reused_skip_trace_task_updates_crm_mirror(self, app):
        from app import db
        from app.models.task import Task
        from app.services.skip_trace_enqueue import SkipTraceEnqueue

        with app.app_context():
            sale_date = date.today() - timedelta(days=20)
            eligible_date = sale_date + timedelta(days=730)
            lead = _make_lead(
                app,
                '0 Recent Sale Mirror St',
                acquisition_date=sale_date,
            )
            mirror = Task(
                title='Old skip trace title',
                status='open',
                source='manual',
                lead_id=lead.id,
                task_type='skip_trace_owner',
                due_date=datetime.utcnow(),
            )
            db.session.add(mirror)
            db.session.flush()
            task = LeadTask(
                lead_id=lead.id,
                task_type='skip_trace_owner',
                title='Old skip trace title',
                status='open',
                due_date=date.today(),
                workflow_key='recent_sale_hold',
                created_by='test',
                mirror_task_id=mirror.id,
            )
            db.session.add(task)
            db.session.commit()

            SkipTraceEnqueue().schedule_recent_sale(
                lead.id,
                due_date=eligible_date,
                actor='test',
            )

            refreshed = db.session.get(Task, mirror.id)
            assert refreshed.title.startswith('Recent-sale hold ended')
            assert refreshed.due_date.date() == eligible_date

    def test_reschedules_native_and_crm_mirror_to_end_of_hold(self, app):
        from app import db
        from app.models.task import Task

        with app.app_context():
            sale_date = date.today() - timedelta(days=30)
            lead = _make_lead(
                app,
                '1 Recent Sale Reconcile St',
                acquisition_date=sale_date,
                recommended_contact_method='direct_mail',
            )
            mirror = Task(
                title='Follow up on property',
                status='overdue',
                source='hubspot_import',
                lead_id=lead.id,
                task_type='custom',
                hubspot_task_id='recent-sale-hs-1',
                due_date=datetime.utcnow() - timedelta(days=10),
            )
            db.session.add(mirror)
            db.session.flush()
            native = LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title=mirror.title,
                status='open',
                due_date=date.today() - timedelta(days=10),
                created_by='test',
                hubspot_task_id=mirror.hubspot_task_id,
                mirror_task_id=mirror.id,
            )
            research = LeadTask(
                lead_id=lead.id,
                task_type='research_missing_pin',
                title='Research missing PIN',
                status='open',
                due_date=date.today(),
                created_by='test',
            )
            queued_item = MailQueueItem(
                lead_id=lead.id,
                user_id=USER_ID,
                status='queued',
            )
            db.session.add_all([native, research, queued_item])
            db.session.commit()

            result = reconcile_recent_sale_mail_tasks_for_lead(
                lead,
                actor='test',
                commit=False,
            )
            db.session.commit()

            expected = sale_date + timedelta(days=730)
            assert recent_sale_mail_eligible_date(lead) == expected
            assert result['rescheduled_to'] == expected.isoformat()
            assert result['rescheduled_task_count'] == 1
            assert result['hubspot_task_ids'] == ['recent-sale-hs-1']
            assert result['skip_trace_scheduled'] is True
            assert result['skip_trace_task_id'] is not None
            assert result['removed_queue_item_count'] == 1
            assert db.session.get(Lead, lead.id).lead_status == 'skip_trace'
            assert db.session.get(Lead, lead.id).needs_skip_trace is False
            skip_task = LeadTask.query.filter_by(
                lead_id=lead.id,
                task_type='skip_trace_owner',
                status='open',
            ).one()
            assert skip_task.due_date == expected
            assert LeadTask.query.get(native.id).due_date == expected
            assert LeadTask.query.get(research.id).due_date == date.today()
            refreshed_mirror = Task.query.get(mirror.id)
            assert refreshed_mirror.due_date.date() == expected
            assert refreshed_mirror.status == 'open'
            assert db.session.get(MailQueueItem, queued_item.id).status == 'removed'

    def test_is_idempotent_after_due_date_moves_to_future(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                '2 Recent Sale Idempotent St',
                acquisition_date=date.today() - timedelta(days=5),
                recommended_contact_method='direct_mail',
            )
            _make_task(app, lead.id)

            first = reconcile_recent_sale_mail_tasks_for_lead(lead, commit=True)
            second = reconcile_recent_sale_mail_tasks_for_lead(lead, commit=True)

            assert first['rescheduled_task_count'] == 1
            assert second['rescheduled_task_count'] == 0
            assert first['skip_trace_scheduled'] is True
            assert second['skip_trace_scheduled'] is False

    def test_activates_skip_trace_only_when_scheduled_date_arrives(self, app):
        from app import db
        from app.services.skip_trace_enqueue import SkipTraceEnqueue

        with app.app_context():
            lead = _make_lead(
                app,
                '3 Recent Sale Activation St',
                acquisition_date=date.today() - timedelta(days=30),
            )
            service = SkipTraceEnqueue()
            scheduled = service.schedule_recent_sale(
                lead.id,
                due_date=date.today(),
                actor='test',
            )

            before = db.session.get(Lead, lead.id)
            assert before.lead_status == 'skip_trace'
            assert before.needs_skip_trace is False

            result = service.activate_due_recent_sale_tasks(actor='test')

            activated = db.session.get(Lead, lead.id)
            assert scheduled['scheduled'] is True
            assert result['activated_lead_ids'] == [lead.id]
            assert activated.lead_status == 'awaiting_skip_trace'
            assert activated.needs_skip_trace is True

    def test_retires_matured_hold_task_for_terminal_lead(self, app):
        from app import db
        from app.services.skip_trace_enqueue import SkipTraceEnqueue

        with app.app_context():
            lead = _make_lead(
                app,
                '4 Terminal Recent Sale Activation St',
                acquisition_date=date.today() - timedelta(days=30),
            )
            service = SkipTraceEnqueue()
            scheduled = service.schedule_recent_sale(
                lead.id,
                due_date=date.today(),
                actor='test',
            )
            lead.lead_status = 'deal_lost'
            db.session.commit()

            result = service.activate_due_recent_sale_tasks(actor='test')

            task = db.session.get(LeadTask, scheduled['task_id'])
            assert result['retired_task_ids'] == [task.id]
            assert task.status == 'completed'
            assert db.session.get(Lead, lead.id).lead_status == 'deal_lost'

    def test_bounded_reconciliation_prioritizes_matured_hold_activation(self, app):
        from app import db
        from app.services.skip_trace_enqueue import SkipTraceEnqueue

        with app.app_context():
            matured = _make_lead(
                app,
                '5 Matured Hold Priority St',
                acquisition_date=date.today() - timedelta(days=800),
            )
            SkipTraceEnqueue().schedule_recent_sale(
                matured.id,
                due_date=date.today(),
                actor='test',
            )
            recent = _make_lead(
                app,
                '6 New Recent Sale Candidate St',
                acquisition_date=date.today() - timedelta(days=30),
                recommended_contact_method='direct_mail',
            )
            recent_task = _make_task(app, recent.id)

            result = reconcile_recent_sale_mail_tasks(
                actor='test',
                limit=1,
                commit=True,
            )

            assert result['processed_lead_ids'] == [matured.id]
            assert result['activated_lead_ids'] == [matured.id]
            assert db.session.get(Lead, matured.id).lead_status == 'awaiting_skip_trace'
            assert db.session.get(LeadTask, recent_task.id).due_date == date.today()


class TestCompleteTasksSupersededByMail:
    def test_completes_overdue_call_task_on_enqueue(self, app):
        with app.app_context():
            lead = _make_lead(app, '1b Call Overdue St')
            task = _make_task(
                app,
                lead.id,
                task_type='call_owner_today',
                title='Call owner',
                due_date=date.today() - timedelta(days=30),
            )

            count, _pending = complete_tasks_superseded_by_mail(
                lead.id, actor=USER_ID, commit=True,
            )

            assert count == 1
            assert LeadTask.query.get(task.id).status == 'completed'

    def test_completes_mail_prep_and_call_tasks(self, app):
        with app.app_context():
            lead = _make_lead(app, '1c Both Tasks St')
            mail_task = _make_task(app, lead.id)
            call_task = _make_task(
                app,
                lead.id,
                task_type='call_owner_today',
                title='Follow up call',
                due_date=date.today() - timedelta(days=10),
            )

            count, _pending = complete_tasks_superseded_by_mail(
                lead.id, actor=USER_ID, commit=True,
            )

            assert count == 2
            assert LeadTask.query.get(mail_task.id).status == 'completed'
            assert LeadTask.query.get(call_task.id).status == 'completed'

    def test_skips_research_task(self, app):
        with app.app_context():
            lead = _make_lead(app, '1d Research St')
            task = _make_task(
                app,
                lead.id,
                task_type='research_missing_pin',
                title='Research missing PIN',
                due_date=date.today() - timedelta(days=5),
            )

            count, _pending = complete_tasks_superseded_by_mail(
                lead.id, actor=USER_ID, commit=True,
            )

            assert count == 0
            assert LeadTask.query.get(task.id).status == 'open'

    def test_completes_hubspot_follow_up_task(self, app):
        from app import db
        from app.models.task import Task
        from app.models.task_association import TaskAssociation

        with app.app_context():
            lead = _make_lead(app, '1e HubSpot St')
            hs_task = Task(
                title='Follow up on 123 Main St',
                status='open',
                source='hubspot_import',
                hubspot_task_id='hs-999',
                due_date=datetime.now(timezone.utc),
            )
            db.session.add(hs_task)
            db.session.flush()
            db.session.add(
                TaskAssociation(
                    task_id=hs_task.id,
                    target_type='lead',
                    target_id=lead.id,
                ),
            )
            db.session.commit()

            with patch(
                'app.services.hubspot_task_completion_service.sync_hubspot_task_to_hubspot',
                return_value=True,
            ):
                count, pending = complete_tasks_superseded_by_mail(
                    lead.id, actor=USER_ID, commit=True,
                )

            assert count == 1
            assert pending == ['hs-999']
            refreshed = Task.query.get(hs_task.id)
            assert refreshed.status == 'completed'

    def test_completes_mirrored_manual_task(self, app):
        from app import db
        from app.models.task import Task

        with app.app_context():
            lead = _make_lead(app, '1f Mirror St')
            mirror = Task(
                title='Call owner back',
                status='open',
                source='manual',
                lead_id=lead.id,
                task_type='call_owner_today',
            )
            db.session.add(mirror)
            db.session.commit()

            count, _pending = complete_tasks_superseded_by_mail(
                lead.id, actor=USER_ID, commit=True,
            )

            assert count == 1
            assert Task.query.get(mirror.id).status == 'completed'

    def test_completes_associated_mirrored_task(self, app):
        from app import db
        from app.models.task import Task
        from app.models.task_association import TaskAssociation

        with app.app_context():
            lead = _make_lead(app, '1g Assoc Mirror St')
            mirror = Task(
                title='Follow up with owner',
                status='open',
                source='manual',
                task_type='custom',
            )
            db.session.add(mirror)
            db.session.flush()
            db.session.add(
                TaskAssociation(
                    task_id=mirror.id,
                    target_type='lead',
                    target_id=lead.id,
                ),
            )
            db.session.commit()

            assert count_superseded_tasks_for_lead(lead.id) == 1
            count, _pending = complete_tasks_superseded_by_mail(
                lead.id, actor=USER_ID, commit=True,
            )

            assert count == 1
            assert Task.query.get(mirror.id).status == 'completed'


class TestFollowUpOverdueMailAwaitingExclusion:
    def test_excludes_lead_with_overdue_task_when_up_next_to_mail(self, app):
        with app.app_context():
            lead = _make_lead(app, '10 Overdue Mail St', up_next_to_mail=True)
            _make_task(
                app,
                lead.id,
                task_type='call_owner_today',
                title='Call owner',
                due_date=date.today() - timedelta(days=5),
            )

            svc = QueueService()
            rows, _total = svc.get_follow_up_overdue()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids


class TestFindMailAwaitingLeadIds:
    def test_finds_up_next_to_mail_leads(self, app):
        with app.app_context():
            lead = _make_lead(app, '11 Awaiting St', up_next_to_mail=True)
            ids = find_mail_awaiting_lead_ids()
            assert lead.id in ids


class TestEnqueueCompletesMailPrepTasks:
    def test_enqueue_completes_add_to_mail_batch_task(self, app):
        with app.app_context():
            lead = _make_lead(app, '2 Enqueue Complete St')
            task = _make_task(app, lead.id)

            with patch('app.services.mail_queue_service.refresh_leads_after_mail_task_changes'):
                with patch('app.services.mail_queue_service.sync_pending_hubspot_completions'):
                    result = MailQueueService().enqueue_leads([lead.id], USER_ID)

            assert result['added'] == 1
            db_task = LeadTask.query.get(task.id)
            assert db_task.status == 'completed'
            # Canonical readiness is MailQueueItem membership, not up_next_to_mail.
            assert Lead.query.get(lead.id).up_next_to_mail is not True
            assert MailQueueItem.query.filter_by(
                lead_id=lead.id, user_id=USER_ID, status='queued',
            ).count() == 1

    def test_enqueue_completes_overdue_call_task(self, app):
        with app.app_context():
            lead = _make_lead(app, '2b Enqueue Call St')
            task = _make_task(
                app,
                lead.id,
                task_type='call_owner_today',
                title='Call owner',
                due_date=date.today() - timedelta(days=20),
            )

            with patch('app.services.mail_queue_service.refresh_leads_after_mail_task_changes'):
                with patch('app.services.mail_queue_service.sync_pending_hubspot_completions'):
                    result = MailQueueService().enqueue_leads([lead.id], USER_ID)

            assert result['added'] == 1
            assert LeadTask.query.get(task.id).status == 'completed'


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

    def test_updates_pending_follow_up_due_date_on_send(self, app):
        with app.app_context():
            from app import db
            from app.services.mail_task_lifecycle_service import create_pending_mail_follow_up_task

            lead = _make_lead(app, '6 Pending Follow Up St')
            pending = create_pending_mail_follow_up_task(lead, actor=USER_ID)
            db.session.commit()
            assert pending.due_date is None

            sent_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            task = schedule_mail_follow_up_task(
                lead=lead,
                sent_at=sent_at,
                actor=USER_ID,
            )
            db.session.commit()

            assert task is not None
            assert task.id == pending.id
            assert task.due_date == sent_at.date() + timedelta(days=MAIL_FOLLOW_UP_OFFSET_DAYS)

    def test_returns_existing_when_follow_up_already_dated(self, app):
        with app.app_context():
            lead = _make_lead(app, '6b Dup Follow Up St')
            sent_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            due = sent_at.date() + timedelta(days=MAIL_FOLLOW_UP_OFFSET_DAYS)

            existing = LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up after mailer — 6b Dup Follow Up St',
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
            assert task is not None
            assert task.id == existing.id
            assert LeadTask.query.filter_by(
                lead_id=lead.id, status='open',
            ).count() == 1


class TestEnqueueCreatesPendingMailFollowUp:
    def test_enqueue_creates_pending_follow_up_task(self, app):
        with app.app_context():
            lead = _make_lead(app, '2c Enqueue Pending St')
            prep = _make_task(app, lead.id)

            with patch('app.services.mail_queue_service.refresh_leads_after_mail_task_changes'):
                with patch('app.services.mail_queue_service.sync_pending_hubspot_completions'):
                    result = MailQueueService().enqueue_leads([lead.id], USER_ID)

            assert result['added'] == 1
            assert LeadTask.query.get(prep.id).status == 'completed'
            pending = LeadTask.query.filter_by(lead_id=lead.id, status='open').all()
            assert len(pending) == 1
            assert pending[0].due_date is None
            assert 'Follow up after mailer' in pending[0].title

    def test_remove_from_batch_cancels_pending_follow_up(self, app):
        with app.app_context():
            from app import db

            lead = _make_lead(app, '2d Remove Pending St')
            with patch('app.services.mail_queue_service.refresh_leads_after_mail_task_changes'):
                with patch('app.services.mail_queue_service.sync_pending_hubspot_completions'):
                    MailQueueService().enqueue_leads([lead.id], USER_ID)

            item = MailQueueItem.query.filter_by(
                lead_id=lead.id, user_id=USER_ID, status='queued',
            ).one()
            with patch('app.services.mail_queue_service.refresh_leads_after_mail_task_changes'):
                MailQueueService().remove_item(item.id, USER_ID)

            open_followups = [
                t for t in LeadTask.query.filter_by(lead_id=lead.id).all()
                if 'Follow up after mailer' in (t.title or '')
            ]
            assert open_followups
            assert all(t.status == 'cancelled' for t in open_followups)
    def test_preserves_pending_mail_follow_up_and_mirror_on_enqueue(self, app):
        with app.app_context():
            from app import db
            from app.models.task import Task
            from app.services.mail_task_lifecycle_service import create_pending_mail_follow_up_task

            lead = _make_lead(app, '2e Preserve Pending St')
            pending = create_pending_mail_follow_up_task(lead, actor=USER_ID)
            db.session.commit()
            mirror = Task.query.filter_by(lead_id=lead.id, title=pending.title).one()

            count, _ = complete_tasks_superseded_by_mail(lead.id, actor=USER_ID, commit=True)
            assert count == 0
            assert LeadTask.query.get(pending.id).status == 'open'
            assert LeadTask.query.get(pending.id).due_date is None
            assert Task.query.get(mirror.id).status == 'open'

    def test_does_not_wipe_dated_mail_follow_up_on_reenqueue(self, app):
        with app.app_context():
            from app import db
            from app.services.mail_task_lifecycle_service import create_pending_mail_follow_up_task

            lead = _make_lead(app, '2f Keep Dated St')
            due = date.today() + timedelta(days=5)
            existing = LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up after mailer — 2f Keep Dated St',
                status='open',
                due_date=due,
                created_by='test',
            )
            db.session.add(existing)
            db.session.commit()

            complete_tasks_superseded_by_mail(lead.id, actor=USER_ID, commit=True)
            task = create_pending_mail_follow_up_task(lead, actor=USER_ID)
            db.session.commit()

            assert task.id == existing.id
            assert task.due_date == due
            assert task.status == 'open'

    def test_schedule_after_complete_keeps_mirror_open(self, app):
        with app.app_context():
            from app import db
            from app.models.task import Task
            from app.services.mail_task_lifecycle_service import create_pending_mail_follow_up_task

            lead = _make_lead(app, '2g Schedule Mirror St')
            pending = create_pending_mail_follow_up_task(lead, actor=USER_ID)
            db.session.commit()

            # Simulate send path: supersede then schedule
            complete_tasks_superseded_by_mail(lead.id, actor=USER_ID, commit=False)
            sent_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            task = schedule_mail_follow_up_task(lead=lead, sent_at=sent_at, actor=USER_ID)
            db.session.commit()

            assert task is not None
            assert task.id == pending.id
            assert task.due_date == sent_at.date() + timedelta(days=MAIL_FOLLOW_UP_OFFSET_DAYS)
            mirror = Task.query.filter_by(lead_id=lead.id, title=task.title).one()
            assert mirror.status == 'open'
            assert mirror.due_date is not None


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

    def test_submit_campaign_failure_cancels_pending_follow_up(self, app, fernet_key, monkeypatch):
        from app import db
        from app.services.open_letter_client_service import OpenLetterClientService

        monkeypatch.setenv('HUBSPOT_ENCRYPTION_KEY', fernet_key)

        with app.app_context():
            lead = _make_lead(app, '9b Failed Campaign St')
            pending = create_pending_mail_follow_up_task(lead, actor=USER_ID)
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
            mock_client.place_order.side_effect = RuntimeError('olc down')
            cfg_svc = MagicMock()
            cfg_svc.require_config.return_value = config
            cfg_svc.get_client.return_value = mock_client

            svc = MailCampaignService()
            svc._config_service = cfg_svc

            with patch('app.services.mail_campaign_service.refresh_leads_after_mail_task_changes') as refresh:
                with pytest.raises(RuntimeError, match='olc down'):
                    svc.submit_campaign(campaign.id)

            assert MailQueueItem.query.get(item.id).status == 'failed'
            assert LeadTask.query.get(pending.id).status == 'cancelled'
            refresh.assert_called_once_with([lead.id])
