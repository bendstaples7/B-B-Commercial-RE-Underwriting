"""Heal placeholder owner names (Taxpayer of) out of mail staging."""
from __future__ import annotations

import pytest

from app import db
from app.models.lead import Lead
from app.models.mail_queue_item import MailQueueItem
from app.services.entity_owner_policy import cold_mail_block_reason
from app.services.generic_owner_heal_service import GenericOwnerHealService
from app.services.lead_scoring_engine import LeadScoringEngine


@pytest.mark.usefixtures('app')
class TestGenericOwnerHeal:
    def _lead(self, **kwargs):
        defaults = dict(
            property_street='100 Main St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_first_name='Taxpayer',
            owner_last_name='of',
            mailing_address='PO Box 1',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            lead_status='mailing_no_contact_made',
            recommended_action='mail_ready',
            owner_user_id='user-1',
        )
        defaults.update(kwargs)
        lead = Lead(**defaults)
        db.session.add(lead)
        db.session.commit()
        return lead

    def test_heal_clears_name_and_unstages_mail(self, app):
        with app.app_context():
            lead = self._lead()
            item = MailQueueItem(
                lead_id=lead.id,
                user_id='user-1',
                status='queued',
            )
            db.session.add(item)
            db.session.commit()

            assert cold_mail_block_reason(lead) == 'generic_owner_name'
            summary = GenericOwnerHealService().heal_lead(
                lead, rescore=True, commit=True,
            )
            assert summary['healed'] is True
            assert summary['removed_queue_items'] == 1

            db.session.refresh(lead)
            assert lead.owner_first_name == ''
            assert lead.owner_last_name is None
            item = MailQueueItem.query.filter_by(lead_id=lead.id).first()
            assert item.status == 'removed'
            assert lead.recommended_action != 'mail_ready'

    def test_real_owner_with_empty_owner2_is_not_candidate(self, app):
        with app.app_context():
            lead = self._lead(
                owner_first_name='Pat',
                owner_last_name='Owner',
            )
            assert GenericOwnerHealService().is_heal_candidate(lead) is False

    def test_commercial_entity_clears_name_but_keeps_queue(self, app):
        with app.app_context():
            from app.models.organization import Organization
            from app.models.property_organization_link import PropertyOrganizationLink

            lead = self._lead(lead_category='commercial')
            org = Organization(name='Stub Holdings LLC', org_type='llc')
            db.session.add(org)
            db.session.flush()
            db.session.add(
                PropertyOrganizationLink(
                    property_id=lead.id,
                    organization_id=org.id,
                    role='owner',
                )
            )
            item = MailQueueItem(
                lead_id=lead.id,
                user_id='user-1',
                status='queued',
            )
            db.session.add(item)
            db.session.commit()

            assert cold_mail_block_reason(lead) is None
            summary = GenericOwnerHealService().heal_lead(
                lead, rescore=False, commit=True,
            )
            assert summary['healed'] is True
            assert summary['removed_queue_items'] == 0
            db.session.refresh(lead)
            assert lead.owner_first_name == ''
            item = MailQueueItem.query.filter_by(lead_id=lead.id).first()
            assert item.status == 'queued'

    def test_scoring_routes_placeholder_to_enrich(self, monkeypatch):
        from unittest.mock import MagicMock

        monkeypatch.setattr(
            'app.services.lead_scoring_engine._resolve_crm_flags',
            lambda _lead: (False, False, True),
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.is_mailable_lead',
            lambda _lead: True,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda _lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_cadence_block_outcome',
            lambda _lead: None,
        )
        monkeypatch.setattr(
            'app.services.scoring_rubric.is_recently_sold',
            lambda _lead: False,
        )
        lead = MagicMock()
        lead.id = 2983
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'residential'
        lead.do_not_contact = False
        lead.follow_up_overdue = False
        lead.is_warm = False
        lead.motivation_score = 0
        lead.property_street = '100 Main'
        lead.owner_first_name = 'Taxpayer'
        lead.owner_last_name = 'of'
        lead.ownership_type = None
        lead.permit_data = None
        lead.mailing_address = '100 Main'
        lead.mailing_city = 'Chicago'
        lead.mailing_state = 'IL'
        lead.mailing_zip = '60601'
        action, rule, signals = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=50.0, data_quality_score=50.0, score_tier='C',
        )
        assert action == 'enrich_data'
        assert rule == 'generic_owner_name'
        assert signals.get('cold_mail_blocked') is True
