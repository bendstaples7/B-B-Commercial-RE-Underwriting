"""Tests for inbound HubSpot task status reconciliation."""
from datetime import datetime

import pytest

from app import db
from app.models.hubspot_engagement import HubSpotEngagement
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.models.lead import Property as Lead
from app.services.hubspot_activity_converter_service import HubSpotActivityConverterService


def _task_engagement(hubspot_id: str, status: str = 'NOT_STARTED'):
    return HubSpotEngagement(
        hubspot_id=hubspot_id,
        engagement_type='TASK',
        raw_payload={
            'metadata': {'subject': 'Follow up', 'status': status},
            'engagement': {'timestamp': 1700000000000},
            'associations': {},
        },
    )


@pytest.fixture
def lead(app):
    with app.app_context():
        row = Lead(
            owner_first_name='Test',
            owner_last_name='Owner',
            property_street='1 Test St',
            lead_status='awaiting_skip_trace',
        )
        db.session.add(row)
        db.session.commit()
        lead_id = row.id
    yield lead_id
    with app.app_context():
        from app.models import LeadTask
        LeadTask.query.filter_by(hubspot_task_id='hs-reconcile-1').delete()
        TaskAssociation.query.filter_by(target_id=lead_id).delete()
        Task.query.filter_by(hubspot_task_id='hs-reconcile-1').delete()
        HubSpotEngagement.query.filter_by(hubspot_id='hs-reconcile-1').delete()
        Lead.query.filter_by(id=lead_id).delete()
        db.session.commit()


def test_reconcile_completes_existing_open_task(app, lead):
    """Updated HubSpot payload with COMPLETED closes the local open task."""
    with app.app_context():
        engagement = _task_engagement('hs-reconcile-1', 'NOT_STARTED')
        db.session.add(engagement)
        db.session.commit()

        task = Task(
            title='Follow up',
            status='open',
            source='hubspot_import',
            hubspot_task_id='hs-reconcile-1',
            raw_payload=engagement.raw_payload,
        )
        db.session.add(task)
        db.session.flush()
        db.session.add(TaskAssociation(
            task_id=task.id,
            target_type='lead',
            target_id=lead,
        ))
        db.session.commit()

        engagement.raw_payload = {
            **engagement.raw_payload,
            'metadata': {'subject': 'Follow up', 'status': 'COMPLETED'},
        }
        db.session.commit()

        svc = HubSpotActivityConverterService()
        assert svc.reconcile_task_from_engagement(engagement) is True

        refreshed = Task.query.filter_by(hubspot_task_id='hs-reconcile-1').first()
        assert refreshed.status == 'completed'
        assert refreshed.completion_timestamp is not None

        from app.models import LeadTask
        lt = LeadTask.query.filter_by(hubspot_task_id='hs-reconcile-1').first()
        assert lt is not None
        assert lt.status == 'completed'
        assert lt.lead_id == lead


def test_reconcile_skips_completed_to_open_downgrade(app, lead):
    """Stale engagement payload must not re-open a locally completed task."""
    with app.app_context():
        engagement = _task_engagement('hs-reconcile-1', 'NOT_STARTED')
        db.session.add(engagement)
        db.session.commit()

        task = Task(
            title='Follow up',
            status='completed',
            source='hubspot_import',
            hubspot_task_id='hs-reconcile-1',
            raw_payload={'metadata': {'status': 'COMPLETED'}},
            completion_timestamp=datetime.utcnow(),
        )
        db.session.add(task)
        db.session.commit()

        svc = HubSpotActivityConverterService()
        assert svc.reconcile_task_from_engagement(engagement) is False

        refreshed = Task.query.filter_by(hubspot_task_id='hs-reconcile-1').first()
        assert refreshed.status == 'completed'


def test_convert_task_creates_lead_task_for_lead_association(app, lead):
    """convert_task upserts a LeadTask when the HubSpot task is lead-linked."""
    with app.app_context():
        from app.models import LeadTask
        from app.models.hubspot_match import HubSpotMatch

        engagement = HubSpotEngagement(
            hubspot_id='hs-convert-lead-task-1',
            engagement_type='TASK',
            raw_payload={
                'metadata': {'subject': 'Call seller', 'status': 'NOT_STARTED'},
                'engagement': {'timestamp': 1700000000000},
                'associations': {'dealIds': ['deal-convert-1']},
            },
        )
        db.session.add(engagement)
        db.session.add(HubSpotMatch(
            hubspot_record_type='deal',
            hubspot_id='deal-convert-1',
            internal_record_type='lead',
            internal_record_id=lead,
            confidence='HIGH',
            status='confirmed',
        ))
        db.session.commit()

        svc = HubSpotActivityConverterService()
        created = svc.convert_task(engagement)
        assert created is not None

        lt = LeadTask.query.filter_by(hubspot_task_id='hs-convert-lead-task-1').first()
        assert lt is not None
        assert lt.lead_id == lead
        assert lt.title == 'Call seller'
        assert lt.status == 'open'

        LeadTask.query.filter_by(hubspot_task_id='hs-convert-lead-task-1').delete()
        TaskAssociation.query.filter_by(target_id=lead).delete()
        Task.query.filter_by(hubspot_task_id='hs-convert-lead-task-1').delete()
        HubSpotEngagement.query.filter_by(hubspot_id='hs-convert-lead-task-1').delete()
        HubSpotMatch.query.filter_by(hubspot_id='deal-convert-1').delete()
        db.session.commit()


def test_convert_task_reconciles_when_already_exists(app, lead):
    """convert_task on existing hubspot_task_id reconciles instead of skipping."""
    with app.app_context():
        engagement = _task_engagement('hs-reconcile-1', 'COMPLETED')
        db.session.add(engagement)
        db.session.commit()

        task = Task(
            title='Follow up',
            status='open',
            source='hubspot_import',
            hubspot_task_id='hs-reconcile-1',
            raw_payload={'metadata': {'status': 'NOT_STARTED'}},
        )
        db.session.add(task)
        db.session.commit()

        svc = HubSpotActivityConverterService()
        result = svc.convert_task(engagement)
        assert result is not None
        assert result.status == 'completed'


def test_reconcile_idempotent_when_unchanged(app, lead):
    """Reconcile returns False when status already matches HubSpot."""
    with app.app_context():
        engagement = _task_engagement('hs-reconcile-1', 'COMPLETED')
        db.session.add(engagement)
        db.session.commit()

        task = Task(
            title='Follow up',
            status='completed',
            source='hubspot_import',
            hubspot_task_id='hs-reconcile-1',
            raw_payload=engagement.raw_payload,
            completion_timestamp=datetime.utcnow(),
        )
        db.session.add(task)
        db.session.commit()

        svc = HubSpotActivityConverterService()
        assert svc.reconcile_task_from_engagement(engagement) is False


def test_sync_task_from_crm_v3_completes_overdue_task(app, lead):
    """Live CRM v3 payload with COMPLETED closes a local overdue task."""
    with app.app_context():
        task = Task(
            title='Follow up with Ronald Jutkins',
            status='overdue',
            due_date=datetime(2026, 5, 15, 16, 49, 31),
            source='hubspot_import',
            hubspot_task_id='109610257829',
            raw_payload={},
        )
        db.session.add(task)
        db.session.flush()
        db.session.add(TaskAssociation(
            task_id=task.id,
            target_type='lead',
            target_id=lead,
        ))
        db.session.commit()

        record = {
            'id': '109610257829',
            'properties': {
                'hs_task_status': 'COMPLETED',
                'hs_task_subject': 'Follow up with Ronald Jutkins',
                'hs_timestamp': '2026-05-21T13:00:00Z',
            },
        }
        svc = HubSpotActivityConverterService()
        assert svc.sync_task_from_crm_v3(record, lead_id=lead) == 'updated'

        refreshed = Task.query.filter_by(hubspot_task_id='109610257829').first()
        assert refreshed.status == 'completed'
        assert refreshed.completion_timestamp is not None


def test_sync_task_from_crm_v3_creates_future_task(app, lead):
    """Missing HubSpot task is created locally with ISO due date."""
    with app.app_context():
        record = {
            'id': '111466061173',
            'properties': {
                'hs_task_status': 'NOT_STARTED',
                'hs_task_subject': 'Follow up with Ronald Jutkins',
                'hs_timestamp': '2026-12-21T14:00:00Z',
            },
        }
        svc = HubSpotActivityConverterService()
        assert svc.sync_task_from_crm_v3(record, lead_id=lead) == 'created'

        created = Task.query.filter_by(hubspot_task_id='111466061173').first()
        assert created is not None
        assert created.status == 'open'
        assert created.due_date.year == 2026
        assert created.due_date.month == 12
        assoc = TaskAssociation.query.filter_by(task_id=created.id, target_id=lead).first()
        assert assoc is not None

        TaskAssociation.query.filter_by(task_id=created.id).delete()
        Task.query.filter_by(hubspot_task_id='111466061173').delete()
        db.session.commit()


def test_sync_task_from_crm_v3_keeps_earlier_local_due(app, lead):
    """HubSpot must not push an open/overdue local due date further into the future."""
    with app.app_context():
        local_due = datetime(2026, 4, 1, 12, 0, 0)
        task = Task(
            title='Follow up with Linda',
            status='overdue',
            due_date=local_due,
            source='hubspot_import',
            hubspot_task_id='hs-due-guard-10737',
            raw_payload={},
        )
        db.session.add(task)
        db.session.flush()
        db.session.add(TaskAssociation(
            task_id=task.id,
            target_type='lead',
            target_id=lead,
        ))
        db.session.commit()

        record = {
            'id': 'hs-due-guard-10737',
            'properties': {
                'hs_task_status': 'NOT_STARTED',
                'hs_task_subject': 'Follow up with Linda',
                'hs_timestamp': '2026-10-27T17:00:00Z',
            },
        }
        svc = HubSpotActivityConverterService()
        assert svc.sync_task_from_crm_v3(record, lead_id=lead) == 'updated'

        refreshed = Task.query.filter_by(hubspot_task_id='hs-due-guard-10737').first()
        assert refreshed.due_date == local_due
        assert refreshed.status == 'open'

        TaskAssociation.query.filter_by(task_id=task.id).delete()
        Task.query.filter_by(hubspot_task_id='hs-due-guard-10737').delete()
        db.session.commit()


def test_sync_task_from_crm_v3_preserves_open_lead_task(app, lead):
    """HubSpot COMPLETED must not close an already-open LeadTask (next-action SoT)."""
    with app.app_context():
        from app.models import LeadTask, LeadTimelineEntry

        task = Task(
            title='Follow up with Julian D Shin',
            status='open',
            due_date=datetime(2026, 7, 13, 13, 0, 0),
            source='hubspot_import',
            hubspot_task_id='hs-preserve-open-lt',
            raw_payload={},
        )
        db.session.add(task)
        db.session.flush()
        db.session.add(TaskAssociation(
            task_id=task.id,
            target_type='lead',
            target_id=lead,
        ))
        lt = LeadTask(
            lead_id=lead,
            task_type='custom',
            title='Follow up with Julian D Shin',
            status='open',
            due_date=datetime(2026, 7, 13).date(),
            created_by='HubSpot',
            hubspot_task_id='hs-preserve-open-lt',
            mirror_task_id=task.id,
        )
        db.session.add(lt)
        db.session.commit()

        record = {
            'id': 'hs-preserve-open-lt',
            'properties': {
                'hs_task_status': 'COMPLETED',
                'hs_task_subject': 'Follow up with Julian D Shin',
                'hs_timestamp': '2026-07-13T13:00:00Z',
                'hs_lastmodifieddate': '2026-07-16T15:20:41.383Z',
            },
        }
        svc = HubSpotActivityConverterService()
        assert svc.sync_task_from_crm_v3(record, lead_id=lead) == 'updated'

        refreshed_crm = Task.query.filter_by(hubspot_task_id='hs-preserve-open-lt').first()
        assert refreshed_crm.status == 'completed'

        refreshed_lt = LeadTask.query.filter_by(hubspot_task_id='hs-preserve-open-lt').first()
        assert refreshed_lt.status == 'open'
        assert refreshed_lt.completed_at is None

        assert LeadTimelineEntry.query.filter_by(
            lead_id=lead,
            event_type='task_completed',
        ).count() == 0

        LeadTimelineEntry.query.filter_by(lead_id=lead).delete()
        LeadTask.query.filter_by(hubspot_task_id='hs-preserve-open-lt').delete()
        TaskAssociation.query.filter_by(task_id=task.id).delete()
        Task.query.filter_by(hubspot_task_id='hs-preserve-open-lt').delete()
        db.session.commit()


def test_sync_task_from_crm_v3_open_to_completed_writes_timeline(app, lead):
    """Inbound complete writes one task_completed timeline row; second sync is idempotent."""
    with app.app_context():
        from app.models import LeadTimelineEntry

        task = Task(
            title='Follow up on 2915 N Hamlin Ave',
            status='open',
            due_date=datetime(2025, 10, 1, 12, 0, 0),
            source='hubspot_import',
            hubspot_task_id='82906161726',
            raw_payload={},
        )
        db.session.add(task)
        db.session.flush()
        db.session.add(TaskAssociation(
            task_id=task.id,
            target_type='lead',
            target_id=lead,
        ))
        db.session.commit()

        record = {
            'id': '82906161726',
            'properties': {
                'hs_task_status': 'COMPLETED',
                'hs_task_subject': 'Follow up on 2915 N Hamlin Ave',
                'hs_timestamp': '2025-10-01T12:00:00Z',
                'hs_lastmodifieddate': '2025-10-21T15:30:00Z',
            },
        }
        svc = HubSpotActivityConverterService()
        assert svc.sync_task_from_crm_v3(record, lead_id=lead) == 'updated'

        entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead,
            event_type='task_completed',
        ).all()
        assert len(entries) == 1
        assert entries[0].source == 'hubspot'
        assert entries[0].occurred_at.month == 10
        assert entries[0].occurred_at.day == 21
        assert entries[0].event_metadata['hubspot_task_id'] == '82906161726'

        assert svc.sync_task_from_crm_v3(record, lead_id=lead) in ('unchanged', 'updated')
        assert LeadTimelineEntry.query.filter_by(
            lead_id=lead,
            event_type='task_completed',
        ).count() == 1

        LeadTimelineEntry.query.filter_by(lead_id=lead).delete()
        TaskAssociation.query.filter_by(task_id=task.id).delete()
        Task.query.filter_by(hubspot_task_id='82906161726').delete()
        db.session.commit()


def test_sync_task_from_crm_v3_create_completed_writes_timeline(app, lead):
    """Creating an already-completed HubSpot task writes timeline once."""
    with app.app_context():
        from app.models import LeadTimelineEntry

        record = {
            'id': 'hs-create-completed-1',
            'properties': {
                'hs_task_status': 'COMPLETED',
                'hs_task_subject': 'Already done',
                'hs_timestamp': '2025-09-01T12:00:00Z',
                'hs_lastmodifieddate': '2025-09-15T10:00:00Z',
            },
        }
        svc = HubSpotActivityConverterService()
        assert svc.sync_task_from_crm_v3(record, lead_id=lead) == 'created'
        assert LeadTimelineEntry.query.filter_by(
            lead_id=lead,
            event_type='task_completed',
        ).count() == 1

        assert svc.sync_task_from_crm_v3(record, lead_id=lead) == 'unchanged'
        assert LeadTimelineEntry.query.filter_by(
            lead_id=lead,
            event_type='task_completed',
        ).count() == 1

        LeadTimelineEntry.query.filter_by(lead_id=lead).delete()
        TaskAssociation.query.filter_by(target_id=lead).delete()
        Task.query.filter_by(hubspot_task_id='hs-create-completed-1').delete()
        db.session.commit()


def test_backfill_missing_hubspot_task_completed_timelines(app, lead):
    """Backfill dry-run/apply for a completed LeadTask without timeline."""
    with app.app_context():
        from app.models import LeadTask, LeadTimelineEntry
        from app.services.hubspot_task_completion_service import (
            backfill_missing_hubspot_task_completed_timelines,
        )

        lt = LeadTask(
            lead_id=lead,
            title='Follow up missing timeline',
            status='completed',
            hubspot_task_id='hs-backfill-tl-1',
            completed_at=datetime(2025, 10, 21, 15, 30, 0),
            task_type='custom',
            created_by='HubSpot',
        )
        db.session.add(lt)
        db.session.commit()

        dry = backfill_missing_hubspot_task_completed_timelines(
            dry_run=True,
            lead_id=lead,
        )
        assert dry['missing'] == 1
        assert dry['applied'] == 0
        assert LeadTimelineEntry.query.filter_by(lead_id=lead).count() == 0

        applied = backfill_missing_hubspot_task_completed_timelines(
            dry_run=False,
            lead_id=lead,
        )
        assert applied['applied'] == 1
        entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead,
            event_type='task_completed',
        ).all()
        assert len(entries) == 1
        assert entries[0].occurred_at.day == 21
        assert entries[0].event_metadata['hubspot_task_id'] == 'hs-backfill-tl-1'

        again = backfill_missing_hubspot_task_completed_timelines(
            dry_run=False,
            lead_id=lead,
        )
        assert again['applied'] == 0
        assert again['skipped'] >= 1

        LeadTimelineEntry.query.filter_by(lead_id=lead).delete()
        LeadTask.query.filter_by(hubspot_task_id='hs-backfill-tl-1').delete()
        db.session.commit()
