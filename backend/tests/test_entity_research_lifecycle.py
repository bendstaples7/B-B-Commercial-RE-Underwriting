"""Tests for preemptive entity research and legacy LLC-search retirement."""
from datetime import date, timedelta

from app.services.entity_research_lifecycle_service import (
    is_legacy_llc_search_task,
    preempt_entity_research_for_lead,
    retire_legacy_llc_search_tasks,
)


class TestLegacyLlcSearchDetection:
    def test_matches_llc_search_title(self):
        task = type('T', (), {'task_type': 'custom', 'title': 'LLC search'})()
        assert is_legacy_llc_search_task(task) is True

    def test_ignores_call_tasks(self):
        task = type('T', (), {'task_type': 'custom', 'title': 'Call owner today'})()
        assert is_legacy_llc_search_task(task) is False


class TestPreemptEntityResearch:
    def test_promotes_asset_management_and_retires_llc_search(self, app):
        from app import db
        from app.models.lead import Lead
        from app.models.lead_task import LeadTask
        from app.models.organization import Organization
        from app.models.property_organization_link import PropertyOrganizationLink

        with app.app_context():
            lead = Lead(
                property_street='650-652 W Buckingham Pl',
                property_city='Chicago',
                property_state='IL',
                property_zip='60657',
                owner_first_name='Svigos Asset Management',
                owner_last_name=None,
                lead_category='residential',
                lead_status='mailing_no_contact_made',
                has_phone=True,
                recommended_action='call_ready',
            )
            db.session.add(lead)
            db.session.flush()
            task = LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title='LLC search',
                status='open',
                due_date=date.today() - timedelta(days=400),
                created_by='test',
            )
            db.session.add(task)
            db.session.commit()

            outcome = preempt_entity_research_for_lead(
                lead.id, actor='test', sync=True, commit=True,
            )

            assert outcome['promoted_organization_id'] is not None
            org = db.session.get(Organization, outcome['promoted_organization_id'])
            assert org is not None
            assert org.org_type == 'property_management'
            assert PropertyOrganizationLink.query.filter_by(
                property_id=lead.id, organization_id=org.id, role='owner',
            ).first() is not None

            refreshed = db.session.get(LeadTask, task.id)
            assert refreshed.status == 'completed'
            assert task.id in outcome['retired_task_ids']

    def test_retires_llc_search_for_unresolved_inc_without_prior_org(self, app):
        """Entity-shaped owners retire HubSpot LLC search even before org exists."""
        from app import db
        from app.models.lead import Lead
        from app.models.lead_task import LeadTask
        from app.services.entity_research_lifecycle_service import (
            should_retire_legacy_llc_search,
            preempt_entity_research_for_lead,
        )

        with app.app_context():
            lead = Lead(
                property_street='847-849 W Sunnyside Ave',
                property_city='Chicago',
                property_state='IL',
                property_zip='60640',
                owner_first_name='Voice',
                owner_last_name='of The People in Uptown Inc',
                lead_category='residential',
                lead_status='mailing_no_contact_made',
                has_phone=True,
            )
            db.session.add(lead)
            db.session.flush()
            task = LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title='LLC Search',
                status='open',
                due_date=date.today() - timedelta(days=60),
                created_by='test',
            )
            db.session.add(task)
            db.session.commit()

            assert should_retire_legacy_llc_search(lead) is True
            outcome = preempt_entity_research_for_lead(
                lead.id, actor='test', sync=True, commit=True,
            )
            assert task.id in outcome['retired_task_ids']
            assert db.session.get(LeadTask, task.id).status == 'completed'

    def test_retire_legacy_tasks_helper(self, app):
        from app import db
        from app.models.lead import Lead
        from app.models.lead_task import LeadTask

        with app.app_context():
            lead = Lead(
                property_street='1 Research Retire St',
                owner_first_name='Jane',
                owner_last_name='Doe',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()
            keep = LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title='Call phone 1',
                status='open',
                due_date=date.today(),
                created_by='test',
            )
            drop = LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title='LLC search',
                status='open',
                due_date=date.today() - timedelta(days=10),
                created_by='test',
            )
            db.session.add_all([keep, drop])
            db.session.commit()

            retired = retire_legacy_llc_search_tasks(lead.id, commit=True)
            assert drop.id in retired
            assert db.session.get(LeadTask, drop.id).status == 'completed'
            assert db.session.get(LeadTask, keep.id).status == 'open'
