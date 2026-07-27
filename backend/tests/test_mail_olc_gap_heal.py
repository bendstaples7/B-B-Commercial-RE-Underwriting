"""Tests for mailing-address dedupe and OLC silent-omit heal."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app import db
from app.models import Lead, MailCampaign, MailQueueItem
from app.models.lead_task import LeadTask
from app.services.mail_campaign_service import MailCampaignService
from app.services.open_letter_contact_mapper import (
    DUPLICATE_MAILING_REASON,
    OLC_OMIT_TWICE_REASON,
    OLC_SUPPORT_WORKFLOW_KEY,
    owner_mailing_dedupe_key,
    validate_owner_mailing_address,
)


def _lead(**kwargs):
    defaults = dict(
        property_street='100 Main St',
        mailing_address='100 Main St',
        mailing_city='Chicago',
        mailing_state='IL',
        mailing_zip='60614',
        owner_first_name='Pat',
        owner_last_name='Owner',
        owner_user_id='user-1',
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.flush()
    return lead


def _queue(user_id, lead_id, *, status='queued', campaign_id=None, validation_error=None):
    item = MailQueueItem(
        user_id=user_id,
        lead_id=lead_id,
        status=status,
        campaign_id=campaign_id,
        validation_error=validation_error,
    )
    db.session.add(item)
    db.session.flush()
    return item


def test_dedupe_key_normalizes(app):
    with app.app_context():
        lead = _lead(
            mailing_address='100 North Main Street',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60614-1234',
        )
        key = owner_mailing_dedupe_key(lead)
        assert key is not None
        assert 'n main st' in key
        assert key.endswith('|60614')


def test_first_omit_requeues_and_stamps(app):
    with app.app_context():
        lead = _lead()
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            submitted_count=1,
            staged_count=1,
            olc_order_id='ord-1',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = _queue('user-1', lead.id, status='sent', campaign_id=campaign.id)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        touched = svc._detect_and_heal_silent_omits(campaign, tracked_lead_ids=set())
        db.session.commit()

        db.session.refresh(item)
        db.session.refresh(lead)
        db.session.refresh(campaign)
        assert lead.id in touched
        assert item.status == 'queued'
        assert item.campaign_id is None
        assert campaign.olc_omitted_lead_ids == [lead.id]
        assert campaign.olc_tracked_lead_ids == []
        assert any(
            isinstance(e, dict) and e.get('olc_silent_omit')
            for e in (lead.mailer_history or [])
        )


def test_second_omit_escalates_support(app):
    with app.app_context():
        lead = _lead()
        lead.mailer_history = [{
            'olc_order_id': 'ord-old',
            'olc_silent_omit': True,
            'campaign_id': 1,
        }]
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            submitted_count=1,
            staged_count=1,
            olc_order_id='ord-new',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = _queue('user-1', lead.id, status='sent', campaign_id=campaign.id)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        svc._detect_and_heal_silent_omits(campaign, tracked_lead_ids=set())
        db.session.commit()

        db.session.refresh(item)
        db.session.refresh(lead)
        assert item.status == 'failed'
        assert item.validation_error == OLC_OMIT_TWICE_REASON
        task = LeadTask.query.filter_by(
            lead_id=lead.id,
            workflow_key=OLC_SUPPORT_WORKFLOW_KEY,
            status='open',
        ).first()
        assert task is not None
        assert validate_owner_mailing_address(lead) == OLC_OMIT_TWICE_REASON


def test_idempotent_same_order_omit(app):
    with app.app_context():
        lead = _lead()
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            submitted_count=1,
            olc_order_id='ord-1',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = _queue('user-1', lead.id, status='sent', campaign_id=campaign.id)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        svc._detect_and_heal_silent_omits(campaign, tracked_lead_ids=set())
        db.session.commit()
        db.session.refresh(item)
        assert item.status == 'queued'

        svc._detect_and_heal_silent_omits(campaign, tracked_lead_ids=set())
        db.session.commit()
        db.session.refresh(lead)
        stamps = [
            e for e in (lead.mailer_history or [])
            if isinstance(e, dict) and e.get('olc_silent_omit')
        ]
        assert len(stamps) == 1
        assert LeadTask.query.filter_by(
            lead_id=lead.id, workflow_key=OLC_SUPPORT_WORKFLOW_KEY,
        ).count() == 0


def test_list_gap_leads_invalid_and_omitted(app):
    with app.app_context():
        invalid_lead = _lead(property_street='9 Invalid')
        omitted_lead = _lead(
            property_street='8 Omitted',
            mailing_address='200 Oak',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60618',
        )
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            staged_count=2,
            submitted_count=1,
            invalid_at_submit_count=1,
            olc_order_id='ord-x',
            olc_omitted_lead_ids=[omitted_lead.id],
            olc_tracked_lead_ids=[],
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        _queue(
            'user-1', invalid_lead.id,
            status='invalid_address',
            campaign_id=campaign.id,
            validation_error='No owner mailing street address',
        )
        _queue('user-1', omitted_lead.id, status='queued', campaign_id=None)
        db.session.commit()

        svc = MailCampaignService()
        invalid_rows = svc.list_gap_leads(campaign.id, 'user-1', kind='invalid_local')
        assert len(invalid_rows) == 1
        assert invalid_rows[0]['lead_id'] == invalid_lead.id
        assert 'No owner mailing' in (invalid_rows[0]['reason'] or '')
        assert invalid_rows[0].get('resolution')

        omitted_rows = svc.list_gap_leads(campaign.id, 'user-1', kind='olc_omitted')
        assert len(omitted_rows) == 1
        assert omitted_rows[0]['lead_id'] == omitted_lead.id
        assert omitted_rows[0]['disposition'] == 'requeued'
        assert omitted_rows[0]['resolution'] == 'Ready to Mail'


def test_list_gap_leads_omitted_does_not_call_olc_sync(app):
    """Opening the omit dialog must not block on sync_campaign_analytics."""
    with app.app_context():
        from unittest.mock import patch

        lead = _lead(property_street='8 Omitted')
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            submitted_count=1,
            olc_order_id='ord-x',
            olc_omitted_lead_ids=[lead.id],
            olc_tracked_lead_ids=[],
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        _queue('user-1', lead.id, status='queued', campaign_id=None)
        db.session.commit()

        svc = MailCampaignService()
        with patch.object(svc, 'sync_campaign_analytics') as sync:
            rows = svc.list_gap_leads(campaign.id, 'user-1', kind='olc_omitted')
            sync.assert_not_called()
        assert len(rows) == 1
        assert rows[0]['resolution'] == 'Ready to Mail'


def test_duplicate_reason_constant(app):
    assert DUPLICATE_MAILING_REASON == 'Duplicate mailing address in batch'


def test_omitted_list_shrinks_when_lead_now_tracked(app):
    with app.app_context():
        lead = _lead()
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            submitted_count=1,
            olc_order_id='ord-1',
            olc_omitted_lead_ids=[lead.id, 99999],
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        _queue('user-1', lead.id, status='queued', campaign_id=None)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        # Lead is now on the order; only non-tracked known ids remain omitted.
        svc._detect_and_heal_silent_omits(campaign, tracked_lead_ids={lead.id})
        db.session.commit()
        db.session.refresh(campaign)
        assert lead.id not in (campaign.olc_omitted_lead_ids or [])
        assert campaign.olc_omitted_lead_ids == [99999]


def test_empty_tracked_skips_heal_on_sync(app):
    with app.app_context():
        from unittest.mock import patch

        lead = _lead()
        campaign = MailCampaign(
            status='submitted',
            lead_count=50,
            submitted_count=50,
            olc_order_id='ord-empty',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = _queue('user-1', lead.id, status='sent', campaign_id=campaign.id)
        db.session.commit()

        client = MagicMock()
        client.get_order_analytics.return_value = {
            'data': {
                'orderItemStatuses': {},
                'geoChart': {'scannedOrderItems': 0, 'notScannedOrderItems': 0},
            },
        }
        client.iter_order_contacts.return_value = []

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        svc._config_service = MagicMock()
        svc._config_service.get_client.return_value = client

        with patch(
            'app.services.mail_campaign_service.refresh_leads_after_mail_task_changes',
        ):
            svc.sync_campaign_analytics(campaign.id)

        db.session.refresh(item)
        assert item.status == 'sent'
        assert item.campaign_id == campaign.id


def test_first_omit_creates_queue_row_when_missing(app):
    with app.app_context():
        lead = _lead()
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            submitted_count=1,
            olc_order_id='ord-missing-item',
            olc_omitted_lead_ids=[lead.id],
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        touched = svc._detect_and_heal_silent_omits(campaign, tracked_lead_ids=set())
        db.session.commit()

        assert lead.id in touched
        item = (
            MailQueueItem.query
            .filter_by(lead_id=lead.id, status='queued')
            .filter(MailQueueItem.campaign_id.is_(None))
            .first()
        )
        assert item is not None


def test_iter_order_contacts_starts_at_page_one(app):
    with app.app_context():
        from app.models.open_letter_config import OpenLetterConfig
        from app.services.open_letter_client_service import OpenLetterClientService

        config = OpenLetterConfig(
            user_id='user-1',
            encrypted_api_token='x',
            use_demo_api=True,
        )
        client = OpenLetterClientService(config, api_token='tok')
        pages_requested: list[int] = []

        def fake_list(order_id, page=1, page_size=100):
            pages_requested.append(page)
            if page == 1:
                return {
                    'data': {
                        'rows': [{'id': 1}],
                        'total': 1,
                        'lastPage': 1,
                    },
                }
            return {'data': {'rows': [], 'total': 1, 'lastPage': 1}}

        client.list_order_contacts = fake_list  # type: ignore[method-assign]
        rows = list(client.iter_order_contacts('ord-1', page_size=100))
        assert pages_requested[0] == 1
        assert len(rows) == 1


def test_submit_dedupes_duplicate_mailing_address(app, monkeypatch):
    with app.app_context():
        from unittest.mock import patch

        from cryptography.fernet import Fernet

        from app.models.open_letter_config import OpenLetterConfig
        from app.services.open_letter_client_service import OpenLetterClientService

        fernet_key = Fernet.generate_key().decode()
        monkeypatch.setenv('HUBSPOT_ENCRYPTION_KEY', fernet_key)

        lead_a = _lead(property_street='10 A', mailing_address='Same St')
        lead_b = _lead(
            property_street='11 B',
            mailing_address='Same St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60614',
        )
        # Match mailing fields for dedupe
        lead_a.mailing_address = 'Same St'
        lead_a.mailing_city = 'Chicago'
        lead_a.mailing_state = 'IL'
        lead_a.mailing_zip = '60614'

        token = OpenLetterClientService.encrypt_token('test-token')
        config = OpenLetterConfig(
            user_id='user-1',
            encrypted_api_token=token,
            batch_minimum=1,
            default_product_id='prod-1',
            default_template_id='tmpl-1',
        )
        campaign = MailCampaign(
            status='pending',
            lead_count=2,
            staged_count=2,
            product_id='prod-1',
            template_id='tmpl-1',
            creative={
                'first_name': 'Bessy',
                'last_name': 'Tam',
                'phone': '3125550100',
                'font_color': '#25408F',
                'return_address': {
                    'address1': '123 Main St',
                    'city': 'Chicago',
                    'state': 'IL',
                    'zip': '60601',
                },
            },
            created_by='user-1',
        )
        db.session.add_all([config, campaign])
        db.session.flush()
        item_a = _queue('user-1', lead_a.id, status='queued', campaign_id=campaign.id)
        item_b = _queue('user-1', lead_b.id, status='queued', campaign_id=campaign.id)
        db.session.commit()

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            'data': {'id': 'olc-dedupe', 'cost': 1.0},
        }
        cfg_svc = MagicMock()
        cfg_svc.require_config.return_value = config
        cfg_svc.get_client.return_value = mock_client

        svc = MailCampaignService()
        svc._config_service = cfg_svc
        svc._timeline = MagicMock()

        with patch('app.services.mail_campaign_service.refresh_leads_after_mail_task_changes'):
            with patch.object(
                MailCampaignService,
                '_schedule_post_submit_analytics_sync',
                staticmethod(lambda _cid: None),
            ):
                result = svc.submit_campaign(campaign.id)

        assert result.status == 'submitted'
        assert result.submitted_count == 1
        db.session.refresh(item_a)
        db.session.refresh(item_b)
        winner = item_a if item_a.id < item_b.id else item_b
        loser = item_b if winner is item_a else item_a
        assert winner.status == 'sent'
        assert winner.campaign_id == campaign.id
        assert loser.status == 'queued'
        assert loser.campaign_id is None
        assert DUPLICATE_MAILING_REASON in (result.submit_drop_summary or {})
