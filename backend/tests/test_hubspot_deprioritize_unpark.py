"""HubSpot Deprioritize must not silently park working leads."""
from datetime import date, datetime, timedelta, timezone

from app import db
from app.models.hubspot_deal import HubSpotDeal
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.mail_queue_item import MailQueueItem
from app.services.hubspot_matcher_service import HubSpotMatcherService
from app.services.lead_scoring_engine import LeadScoringEngine
from app.services.lead_status_service import (
    count_working_deprioritize_heal_candidates,
    heal_working_deprioritize_leads,
    working_deprioritize_heal_candidates,
)
from app.services.mail_queue_service import MailQueueService


def _deal(hubspot_id: str) -> HubSpotDeal:
    return HubSpotDeal(
        hubspot_id=hubspot_id,
        raw_payload={
            'properties': {
                'dealstage': 'deprioritize_stage',
                'dealname': 'Monticello',
            }
        },
    )


class TestHubSpotDeprioritizeCopy:
    def test_idle_lead_copies_stage_and_writes_timeline(self, app):
        with app.app_context():
            lead = Lead(
                property_street='Idle Deprioritize St',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()
            deal = _deal('deal_idle_depri')
            db.session.add(deal)
            db.session.flush()

            HubSpotMatcherService().enrich_lead_from_deal(
                lead,
                deal,
                stage_label_map={'deprioritize_stage': 'Deprioritize'},
            )
            db.session.flush()

            assert lead.lead_status == 'deprioritize'
            rows = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed',
            ).all()
            assert len(rows) == 1
            assert rows[0].actor == 'System'
            assert rows[0].source == 'hubspot'
            assert 'Deprioritize' in rows[0].summary

    def test_open_follow_up_blocks_deprioritize_copy(self, app):
        with app.app_context():
            lead = Lead(
                property_street='Working Follow Up St',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up on Monticello',
                status='open',
                due_date=date.today() - timedelta(days=3),
                created_by='test',
            ))
            deal = _deal('deal_work_depri')
            db.session.add(deal)
            db.session.flush()

            HubSpotMatcherService().enrich_lead_from_deal(
                lead,
                deal,
                stage_label_map={'deprioritize_stage': 'Deprioritize'},
            )
            db.session.flush()

            assert lead.lead_status == 'mailing_no_contact_made'
            assert LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed',
            ).count() == 0


class TestUnparkDeprioritizeHeal:
    def test_heal_unparks_overdue_follow_up_shaped_like_10664(self, app):
        with app.app_context():
            lead = Lead(
                property_street='3054 N Monticello Ave 60618',
                lead_status='deprioritize',
                recommended_action='suppress',
                hubspot_deal_stage='Deprioritize',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='hubspot_call',
                occurred_at=datetime.now(timezone.utc) - timedelta(days=400),
                source='hubspot',
                actor='HubSpot',
                summary='Tried reaching out',
            ))
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title='Follow up on 3054 N Monticello Ave',
                status='open',
                due_date=date.today() - timedelta(days=10),
                created_by='hubspot',
            ))
            db.session.commit()

            healed = heal_working_deprioritize_leads(commit=True)
            assert healed == 1
            db.session.refresh(lead)
            assert lead.lead_status == 'mailing_contacted_no_interest'
            changed = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed',
            ).one()
            assert changed.actor == 'System'
            assert changed.source == 'system'
            assert changed.event_metadata['previous_status'] == 'deprioritize'
            score = LeadScoringEngine().evaluate_recommended_action(
                lead, 40.0, 50.0, 'C',
            )
            assert score[1] != 'terminal_status'

    def test_suppress_stays_when_heal_does_not_apply(self, app):
        with app.app_context():
            lead = Lead(
                property_street='Idle Parked St',
                lead_status='deprioritize',
                recommended_action='suppress',
            )
            db.session.add(lead)
            db.session.commit()

            healed = heal_working_deprioritize_leads(commit=True)
            assert healed == 0
            db.session.refresh(lead)
            assert lead.lead_status == 'deprioritize'
            action, reason, _meta = LeadScoringEngine().evaluate_recommended_action(
                lead, 40.0, 50.0, 'C',
            )
            assert action == 'suppress'
            assert reason == 'terminal_status'

    def test_heal_skips_manual_deprioritize(self, app):
        with app.app_context():
            lead = Lead(
                property_street='Manual Park St',
                lead_status='deprioritize',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='status_changed',
                occurred_at=datetime.now(timezone.utc),
                source='manual',
                actor='ben',
                summary="Status changed from 'mailing_no_contact_made' to 'deprioritize'.",
                event_metadata={
                    'previous_status': 'mailing_no_contact_made',
                    'new_status': 'deprioritize',
                },
            ))
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up',
                status='open',
                due_date=date.today() - timedelta(days=1),
                created_by='test',
            ))
            db.session.commit()

            healed = heal_working_deprioritize_leads(commit=True)
            assert healed == 0
            db.session.refresh(lead)
            assert lead.lead_status == 'deprioritize'

    def test_heal_candidates_match_apply_eligibility(self, app):
        with app.app_context():
            eligible = Lead(
                property_street='Eligible Park St',
                lead_status='deprioritize',
            )
            manual = Lead(
                property_street='Manual Candidate Park St',
                lead_status='deprioritize',
            )
            idle = Lead(
                property_street='Idle Candidate Park St',
                lead_status='deprioritize',
            )
            db.session.add_all([eligible, manual, idle])
            db.session.flush()
            db.session.add(LeadTask(
                lead_id=eligible.id,
                task_type='call_owner_today',
                title='Follow up',
                status='open',
                due_date=date.today(),
                created_by='test',
            ))
            db.session.add(LeadTimelineEntry(
                lead_id=manual.id,
                event_type='status_changed',
                occurred_at=datetime.now(timezone.utc),
                source='manual',
                actor='ben',
                summary="Status changed from 'mailing_no_contact_made' to 'deprioritize'.",
                event_metadata={
                    'previous_status': 'mailing_no_contact_made',
                    'new_status': 'deprioritize',
                },
            ))
            db.session.add(LeadTask(
                lead_id=manual.id,
                task_type='call_owner_today',
                title='Follow up',
                status='open',
                due_date=date.today(),
                created_by='test',
            ))
            db.session.commit()

            candidates = working_deprioritize_heal_candidates()
            assert [lead.id for lead in candidates] == [eligible.id]
            assert count_working_deprioritize_heal_candidates() == 1

    def test_heal_ignores_deleted_manual_deprioritize(self, app):
        with app.app_context():
            lead = Lead(
                property_street='Deleted Manual Park St',
                lead_status='deprioritize',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='status_changed',
                occurred_at=datetime.now(timezone.utc),
                source='manual',
                actor='ben',
                summary="Status changed from 'mailing_no_contact_made' to 'deprioritize'.",
                event_metadata={
                    'previous_status': 'mailing_no_contact_made',
                    'new_status': 'deprioritize',
                },
                is_deleted=True,
            ))
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up',
                status='open',
                due_date=date.today() - timedelta(days=1),
                created_by='test',
            ))
            db.session.commit()

            healed = heal_working_deprioritize_leads(commit=True)
            assert healed == 1
            db.session.refresh(lead)
            assert lead.lead_status == 'mailing_no_contact_made'

    def test_heal_unparks_same_day_follow_up(self, app):
        with app.app_context():
            lead = Lead(
                property_street='Due Today Park St',
                lead_status='deprioritize',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up',
                status='open',
                due_date=date.today(),
                created_by='test',
            ))
            db.session.commit()

            healed = heal_working_deprioritize_leads(commit=True)
            assert healed == 1
            db.session.refresh(lead)
            assert lead.lead_status == 'mailing_no_contact_made'

    def test_heal_can_skip_scoring_refresh_for_migration(self, app):
        with app.app_context():
            from unittest.mock import patch

            lead = Lead(
                property_street='No Rescore Park St',
                lead_status='deprioritize',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up',
                status='open',
                due_date=date.today(),
                created_by='test',
            ))
            db.session.commit()

            with patch('app.services.lead_refresh.refresh_lead_scoring') as refresh:
                healed = heal_working_deprioritize_leads(
                    commit=True,
                    recompute_action=False,
                )

            assert healed == 1
            refresh.assert_not_called()
            db.session.refresh(lead)
            assert lead.lead_status == 'mailing_no_contact_made'

    def test_heal_commits_unpark_before_scoring_refresh_rollback(self, app):
        with app.app_context():
            from unittest.mock import patch

            lead = Lead(
                property_street='Refresh Rollback Park St',
                lead_status='deprioritize',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='call_owner_today',
                title='Follow up',
                status='open',
                due_date=date.today(),
                created_by='test',
            ))
            db.session.commit()

            def rollback_refresh(_lead_id):
                db.session.rollback()

            with patch(
                'app.services.lead_refresh.refresh_lead_scoring',
                side_effect=rollback_refresh,
            ):
                healed = heal_working_deprioritize_leads(
                    commit=True,
                    recompute_action=True,
                )

            assert healed == 1
            db.session.expire_all()
            refreshed = db.session.get(Lead, lead.id)
            assert refreshed.lead_status == 'mailing_no_contact_made'

    def test_standalone_heal_script_uses_production_and_recomputes(self):
        from pathlib import Path

        script = Path(__file__).resolve().parents[1] / 'scripts' / 'heal_working_deprioritize.py'
        text = script.read_text(encoding='utf-8')
        assert "os.environ['FLASK_ENV'] = 'production'" in text
        assert "create_app('production')" in text
        assert 'count_working_deprioritize_heal_candidates' in text
        assert 'recompute_action=True' in text

    def test_enqueue_unparks_deprioritize(self, app):
        with app.app_context():
            from unittest.mock import patch

            lead = Lead(
                property_street='Queue Unpark St',
                lead_status='deprioritize',
                recommended_action='suppress',
                has_phone=True,
                has_email=True,
                has_property_match=True,
                analysis_complete=True,
                owner_user_id='test-user',
                mailing_address='123 Main St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
            )
            db.session.add(lead)
            db.session.commit()

            with patch('app.services.mail_queue_service.refresh_leads_after_mail_task_changes'):
                with patch('app.services.mail_queue_service.sync_pending_hubspot_completions'):
                    result = MailQueueService().enqueue_leads([lead.id], 'test-user')

            assert result['added'] == 1
            db.session.refresh(lead)
            assert lead.lead_status == 'mailing_no_contact_made'
            assert MailQueueItem.query.filter_by(
                lead_id=lead.id, status='queued',
            ).count() == 1
            assert LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed',
            ).count() == 1
