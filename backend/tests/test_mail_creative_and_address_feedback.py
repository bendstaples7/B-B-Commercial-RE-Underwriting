"""Tests for mail creative helpers and OLC address feedback sync."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.mail_creative import (
    build_olc_return_address,
    fill_to_hex,
    normalize_preset,
    snapshot_creative,
    validate_sender_ready,
)
from app.services.mail_campaign_service import MailCampaignService


def test_build_olc_return_address_uses_first_last_not_name():
    street = {
        'address1': '1343 W Irving Park Rd',
        'city': 'Chicago',
        'state': 'IL',
        'zip': '60613',
    }
    preset = normalize_preset({
        'first_name': 'Bessy',
        'last_name': 'Tam',
        'phone': '3125550100',
        'email': 'bessy@example.com',
        'include_email': True,
        'website': 'https://example.com',
        'include_website': False,
    })
    assert preset['phone'] == '(312) 555-0100'
    payload = build_olc_return_address(street, preset)
    assert payload['firstName'] == 'Bessy'
    assert payload['lastName'] == 'Tam'
    assert payload['phoneNo'] == '(312) 555-0100'
    assert payload['email'] == 'bessy@example.com'
    assert 'websiteUrl' not in payload
    assert 'name' not in payload


def test_format_mailer_phone_variants():
    from app.services.mail_creative import format_mailer_phone
    assert format_mailer_phone('312-555-0100') == '(312) 555-0100'
    assert format_mailer_phone('13125550100') == '(312) 555-0100'
    assert format_mailer_phone('+1 (312) 555-0100') == '(312) 555-0100'
    assert format_mailer_phone('12345') == '12345'


def test_validate_sender_ready_requires_name_and_phone():
    assert validate_sender_ready(None)
    assert validate_sender_ready(normalize_preset({'first_name': 'Ben'}))
    assert validate_sender_ready(normalize_preset({'phone': '312'}))
    assert validate_sender_ready(normalize_preset({
        'first_name': 'Ben', 'phone': '312-555-0199',
    })) is None


def test_extract_letter_body_style_prefers_merge_tag_body():
    from app.services.mail_creative import extract_letter_body_style

    design = {
        'pages': [{
            'children': [
                {
                    'type': 'text',
                    'fontFamily': 'Roboto',
                    'fill': 'grey',
                    'text': '0000001',
                },
                {
                    'type': 'text',
                    'fontFamily': 'Waiting for the Sunrise',
                    'fill': 'rgba(37,64,143,1)',
                    'text': 'Hi {{C.FIRST_NAME}},\nPlease call.',
                },
                {
                    'type': 'text',
                    'fontFamily': 'Noto Sans JP',
                    'fill': 'rgba(74,74,74,1)',
                    'text': 'Keep important text inside the green line.',
                },
            ],
        }],
    }
    style = extract_letter_body_style(design)
    assert style['font_name'] == 'Waiting for the Sunrise'
    assert style['font_color'] == '#25408F'


def test_fill_to_hex_rejects_invalid_hex_values():
    assert fill_to_hex('#ggg') is None
    assert fill_to_hex('#12345z') is None
    assert fill_to_hex('#123') == '#112233'


def test_snapshot_creative_freezes_fields():
    preset = normalize_preset({
        'label': 'Bessy blue',
        'first_name': 'Bessy',
        'last_name': 'Tam',
        'phone': '1',
        'envelope_color': 'blue',
        'font_name': 'Waiting for the Sunrise',
        'font_color': '#25408F',
        'include_email': False,
        'include_website': True,
        'website': 'https://x.com',
    })
    snap = snapshot_creative(preset, template_id=371, template_name='Standard')
    assert snap['sender_display_name'] == 'Bessy Tam'
    assert snap['envelope_color'] == 'blue'
    assert snap['font_name'] == 'Waiting for the Sunrise'
    assert snap['font_color'] == '#25408F'
    assert snap['olc_template_id'] == 371


def test_apply_corrected_overwrites_mailing(app):
    with app.app_context():
        from app import db
        from app.models import Lead

        lead = Lead(
            property_street='1 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='Old St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            mailer_history=[{'olc_order_id': '99', 'sent_at': 'x'}],
        )
        db.session.add(lead)
        db.session.commit()

        campaign = SimpleNamespace(
            id=1,
            olc_order_id='99',
            created_by='user-1',
        )
        svc = MailCampaignService()
        svc._timeline = MagicMock()
        changed = svc._apply_corrected(
            lead,
            {
                'address1': '2041 W Cuyler Ave',
                'city': 'Chicago',
                'state': 'IL',
                'zip': '60618-3005',
            },
            campaign,
        )
        assert changed is True
        assert lead.mailing_address == '2041 W Cuyler Ave'
        assert lead.mailing_zip == '60618-3005'
        # Idempotent
        assert svc._apply_corrected(lead, {
            'address1': '2041 W Cuyler Ave',
            'city': 'Chicago',
            'state': 'IL',
            'zip': '60618-3005',
        }, campaign) is False


def test_apply_failed_marks_item_and_returned(app):
    with app.app_context():
        from app import db
        from app.models import Lead, MailQueueItem, MailCampaign

        lead = Lead(
            property_street='1 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='9719 LAVELL AVE',
            mailing_city='Skokie',
            mailing_state='IL',
            mailing_zip='60076',
            mailer_history=[{'olc_order_id': '2128215'}],
            owner_user_id='user-1',
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            olc_order_id='2128215',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='sent',
            campaign_id=campaign.id,
        )
        db.session.add(item)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        changed = svc._apply_failed(
            lead,
            item,
            {'addressFailureReason': 'The address does not exist in the USPS database.'},
            campaign,
        )
        assert changed is True
        assert item.status == 'failed'
        assert 'USPS' in (item.validation_error or '')
        assert lead.returned_addresses
        # Idempotent second pass
        assert svc._apply_failed(lead, item, {
            'addressFailureReason': 'The address does not exist in the USPS database.',
        }, campaign) is False


def test_failed_wins_over_corrected_when_collapsing():
    from app.services.mail_campaign_service import collapse_recipients_by_lead

    recipients = [
        {
            'addressStatus': 'Corrected',
            'meta': {'data': {'lead_id': 7}},
            'address1': 'A',
        },
        {
            'addressStatus': 'Failed',
            'meta': {'data': {'lead_id': 7}},
            'addressFailureReason': 'bad',
        },
    ]
    by_lead = collapse_recipients_by_lead(recipients)
    assert by_lead[7]['addressStatus'] == 'Failed'


def test_cancel_campaign_holds_queue_when_olc_fails(app):
    with app.app_context():
        from app import db
        from app.models import Lead, MailQueueItem, MailCampaign
        from app.exceptions import MailQueueError

        lead = Lead(
            property_street='1 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            olc_order_id='2128215',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='sent',
            campaign_id=campaign.id,
        )
        db.session.add(item)
        db.session.commit()

        svc = MailCampaignService()
        client = MagicMock()
        client.cancel_order.return_value = {
            'ok': False,
            'detail': 'DELETE /orders/2128215: Open Letter authentication failed (HTTP 403)',
        }
        svc._config_service = MagicMock()
        svc._config_service.get_client.return_value = client

        cancelled, meta = svc.cancel_campaign(campaign.id, 'user-1')
        assert cancelled.status == 'cancelled'
        assert meta['olc_cancel_ok'] is False
        assert meta['queue_held'] is True
        assert meta['requeued_count'] == 0
        assert meta['warning']
        # Items stay attached until Connect cancel + Release to queue
        assert item.status == 'sent'
        assert item.campaign_id == campaign.id
        assert 'olc_cancel: failed' in (cancelled.error_message or '')

        with pytest.raises(MailQueueError) as exc_info:
            svc.redispatch_submit(campaign.id)
        assert 'cancelled' in str(exc_info.value).lower()

        # After Connect cancel, release re-queues
        cancelled2, meta2 = svc.cancel_campaign(
            campaign.id, 'user-1', release_queue=True,
        )
        assert meta2['queue_held'] is False
        assert meta2['requeued_count'] == 1
        assert item.status == 'queued'
        assert item.campaign_id is None
        assert lead.up_next_to_mail is True


def test_cancel_campaign_blocks_mailed(app):
    with app.app_context():
        from app import db
        from app.models import MailCampaign
        from app.exceptions import MailQueueError

        campaign = MailCampaign(
            status='mailed',
            lead_count=1,
            olc_order_id='999',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.commit()

        svc = MailCampaignService()
        with pytest.raises(MailQueueError) as exc_info:
            svc.cancel_campaign(campaign.id, 'user-1')
        assert exc_info.value.status_code == 409


def test_cancel_campaign_without_olc_order(app):
    with app.app_context():
        from app import db
        from app.models import Lead, MailQueueItem, MailCampaign

        lead = Lead(
            property_street='2 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='pending',
            lead_count=1,
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='queued',
            campaign_id=campaign.id,
        )
        db.session.add(item)
        db.session.commit()

        svc = MailCampaignService()
        cancelled, meta = svc.cancel_campaign(campaign.id, 'user-1')
        assert cancelled.status == 'cancelled'
        assert meta['olc_cancel_ok'] is True
        assert meta['warning'] is None
        assert meta['queue_held'] is False
        assert item.status == 'queued'
        assert item.campaign_id is None
        assert lead.up_next_to_mail is True


def test_cancel_campaign_holds_processing_without_olc_order_id(app):
    with app.app_context():
        from app import db
        from app.models import Lead, MailCampaign, MailQueueItem

        lead = Lead(
            property_street='3 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='processing',
            lead_count=1,
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='sent',
            campaign_id=campaign.id,
        )
        db.session.add(item)
        db.session.commit()

        svc = MailCampaignService()
        svc._best_effort_revoke_submit = MagicMock()
        cancelled, meta = svc.cancel_campaign(campaign.id, 'user-1')

        assert cancelled.status == 'cancelled'
        assert meta['queue_held'] is True
        assert meta['requeued_count'] == 0
        assert meta['warning']
        assert item.status == 'sent'
        assert item.campaign_id == campaign.id


def test_redispatch_restores_failed_items(app, monkeypatch):
    with app.app_context():
        from app import db
        from app.models import Lead, MailCampaign, MailQueueItem

        lead = Lead(
            property_street='4 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='failed',
            lead_count=1,
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='failed',
            validation_error='Open Letter timed out',
            campaign_id=campaign.id,
        )
        db.session.add(item)
        db.session.commit()

        send_task = MagicMock()
        monkeypatch.setattr('celery.current_app.send_task', send_task)

        redispatched = MailCampaignService().redispatch_submit(campaign.id)

        assert redispatched.status == 'pending'
        assert item.status == 'queued'
        assert item.validation_error is None
        send_task.assert_called_once_with(
            'open_letter.submit_campaign',
            args=[campaign.id],
        )


def test_fetch_template_design_sends_no_auth_header(monkeypatch):
    from app.services.open_letter_client_service import OpenLetterClientService

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {'pages': []}

    def fake_get(url, **kwargs):
        captured['url'] = url
        captured['headers'] = kwargs.get('headers')
        captured['allow_redirects'] = kwargs.get('allow_redirects')
        return FakeResp()

    config = SimpleNamespace(use_demo_api=True, encrypted_api_token='x')
    client = OpenLetterClientService(config, api_token='secret-token')
    monkeypatch.setattr(client, 'find_template', lambda _id: {
        'id': 1,
        'templateUrl': 'https://d123.cloudfront.net/design.json',
    })
    monkeypatch.setattr('app.services.open_letter_client_service.requests.get', fake_get)

    design = client.fetch_template_design(1)
    assert design == {'pages': []}
    assert captured['url'] == 'https://d123.cloudfront.net/design.json'
    assert captured['headers'] is None or 'Authorization' not in (captured['headers'] or {})
    assert captured['allow_redirects'] is False


def test_find_template_scans_until_pages_are_exhausted():
    from app.services.open_letter_client_service import OpenLetterClientService

    config = SimpleNamespace(use_demo_api=True, encrypted_api_token='x')
    client = OpenLetterClientService(config, api_token='secret-token')
    seen_pages = []

    def fake_list_templates(page=0, page_size=50, product_types=None):
        seen_pages.append(page)
        if page == 21:
            return {'data': [{'id': 'target', 'name': 'Late template'}]}
        return {'data': [{'id': f'{page}-{i}'} for i in range(page_size)]}

    client.list_templates = fake_list_templates

    assert client.find_template('target') == {'id': 'target', 'name': 'Late template'}
    assert max(seen_pages) == 21


def test_scrub_unsent_cancelled_campaign_removes_false_send(app):
    with app.app_context():
        from datetime import date

        from app import db
        from app.models import Lead, LeadTask, MailCampaign, MailQueueItem
        from app.models.lead_timeline_entry import LeadTimelineEntry
        from app.services.mail_campaign_scrub import scrub_unsent_cancelled_campaign

        lead = Lead(
            property_street='9 Scrub St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
            up_next_to_mail=False,
            mailer_history=[
                'Legacy free text mailer',
                {
                    'campaign_id': 1,
                    'olc_order_id': '2128215',
                    'sent_at': '2026-07-22T16:05:50+00:00',
                    'template_name': 'Standard',
                },
            ],
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='cancelled',
            lead_count=1,
            olc_order_id='2128215',
            created_by='user-1',
            error_message='olc_cancel: failed',
        )
        db.session.add(campaign)
        db.session.flush()
        # Rewrite history to use real campaign id
        lead.mailer_history = [
            'Legacy free text mailer',
            {
                'campaign_id': campaign.id,
                'olc_order_id': '2128215',
                'sent_at': '2026-07-22T16:05:50+00:00',
                'template_name': 'Standard',
            },
        ]
        db.session.add(MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='queued',
            campaign_id=None,
        ))
        db.session.add(LeadTimelineEntry(
            lead_id=lead.id,
            event_type='mail_sent',
            occurred_at=date.today(),
            source='system',
            actor='user-1',
            summary=f'Mailer sent (campaign {campaign.id})',
            event_metadata={
                'campaign_id': campaign.id,
                'olc_order_id': '2128215',
            },
            is_deleted=False,
        ))
        db.session.add(LeadTask(
            lead_id=lead.id,
            task_type='call_owner_today',
            title='Follow up after mailer — 9 Scrub St',
            status='open',
            due_date=None,  # undated — scrub may cancel these
            created_by='user-1',
        ))
        db.session.add(LeadTask(
            lead_id=lead.id,
            task_type='call_owner_today',
            title='Later follow up after other mail — 9 Scrub St',
            status='open',
            due_date=date(2026, 8, 15),  # dated — must not be cancelled by scrub
            created_by='user-1',
        ))
        db.session.commit()

        dry = scrub_unsent_cancelled_campaign(campaign.id, apply=False)
        assert dry['history_entries_removed'] == 1
        assert dry['timeline_mail_sent_deleted'] == 1
        assert dry['follow_ups_cancelled'] == 1
        assert dry['up_next_restored'] == 1
        db.session.refresh(lead)
        assert isinstance(lead.mailer_history, list) and len(lead.mailer_history) == 2

        applied = scrub_unsent_cancelled_campaign(campaign.id, apply=True)
        assert applied['apply'] is True
        db.session.refresh(lead)
        assert lead.mailer_history == ['Legacy free text mailer']
        assert lead.up_next_to_mail is True
        tl = LeadTimelineEntry.query.filter_by(lead_id=lead.id, event_type='mail_sent').one()
        assert tl.is_deleted is True
        undated = LeadTask.query.filter_by(
            lead_id=lead.id, due_date=None,
        ).one()
        assert undated.status == 'cancelled'
        dated = LeadTask.query.filter(
            LeadTask.lead_id == lead.id,
            LeadTask.due_date.isnot(None),
        ).one()
        assert dated.status == 'open'


def test_scrub_refuses_mailed_evidence_unless_force(app):
    with app.app_context():
        from app import db
        from app.exceptions import MailQueueError
        from app.models import Lead, MailCampaign, MailQueueItem
        from app.services.mail_campaign_scrub import scrub_unsent_cancelled_campaign

        lead = Lead(
            property_street='10 Force Scrub St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            owner_user_id='user-1',
            mailer_history=[],
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='cancelled',
            lead_count=1,
            olc_order_id='9990001',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        db.session.add(MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='sent',
            campaign_id=campaign.id,
        ))
        db.session.commit()

        try:
            scrub_unsent_cancelled_campaign(campaign.id, apply=False)
            assert False, 'expected MailQueueError'
        except MailQueueError as exc:
            assert exc.status_code == 409
            assert 'mailed' in str(exc).lower() or 'force' in str(exc).lower()

        forced = scrub_unsent_cancelled_campaign(campaign.id, apply=False, force=True)
        assert forced['force'] is True
    """After cancel/requeue, OLC Failed must drop Ready-to-Mail rows."""
    with app.app_context():
        from app import db
        from app.models import Lead, MailCampaign, MailQueueItem

        lead = Lead(
            property_street='1 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='9719 LAVELL AVE',
            mailing_city='Skokie',
            mailing_state='IL',
            mailing_zip='60076',
            owner_user_id='user-1',
            up_next_to_mail=True,
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='cancelled',
            lead_count=1,
            olc_order_id='2128215',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='queued',
            campaign_id=None,
        )
        db.session.add(item)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        changed = svc._apply_failed(
            lead,
            item,
            {'addressFailureReason': 'The address does not exist in the USPS database.'},
            campaign,
        )
        assert changed is True
        assert item.status == 'invalid_address'
        assert 'USPS' in (item.validation_error or '')
        assert lead.up_next_to_mail is False
        assert lead.returned_addresses


def test_apply_failed_idempotent_when_queue_already_invalid(app):
    """Partial prior apply (queue flipped, no history stamp) must not duplicate timeline."""
    with app.app_context():
        from app import db
        from app.models import Lead, MailCampaign, MailQueueItem

        lead = Lead(
            property_street='1 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='Bad',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='user-1',
            returned_addresses='Bad, Chicago, IL 60601',
        )
        db.session.add(lead)
        db.session.flush()
        campaign = MailCampaign(
            status='cancelled',
            lead_count=1,
            olc_order_id='2128215',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='invalid_address',
            campaign_id=None,
            validation_error='The address does not exist in the USPS database.',
        )
        db.session.add(item)
        db.session.commit()

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        changed = svc._apply_failed(
            lead,
            item,
            {'addressFailureReason': 'The address does not exist in the USPS database.'},
            campaign,
        )
        assert changed is False
        svc._timeline.append.assert_not_called()
        hist = lead.mailer_history
        assert isinstance(hist, list)
        assert any(
            isinstance(e, dict) and e.get('address_feedback') == 'Failed'
            for e in hist
        )


def test_stamp_address_feedback_persists_json_mutation(app):
    with app.app_context():
        from app import db
        from app.models import Lead

        lead = Lead(
            property_street='1 Main',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailer_history=['Legacy free text'],
        )
        db.session.add(lead)
        db.session.commit()

        MailCampaignService._stamp_address_feedback(lead, '2128215', 'Corrected')
        db.session.commit()
        db.session.refresh(lead)
        assert any(
            isinstance(e, dict)
            and e.get('olc_order_id') == '2128215'
            and e.get('address_feedback') == 'Corrected'
            for e in (lead.mailer_history or [])
        )


def test_sync_address_feedback_resolves_requeued_item_by_lead(app):
    """Sync must find queue rows even when campaign_id was cleared on requeue."""
    with app.app_context():
        from app import db
        from app.models import Lead, MailCampaign, MailQueueItem

        lead_failed = Lead(
            property_street='2 Fail St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='Bad Addr',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='user-1',
            up_next_to_mail=True,
        )
        lead_corrected = Lead(
            property_street='3 Fix St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='Old St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='user-1',
        )
        db.session.add_all([lead_failed, lead_corrected])
        db.session.flush()
        campaign = MailCampaign(
            status='cancelled',
            lead_count=2,
            olc_order_id='2128215',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.flush()
        item_failed = MailQueueItem(
            lead_id=lead_failed.id,
            user_id='user-1',
            status='queued',
            campaign_id=None,
        )
        item_corrected = MailQueueItem(
            lead_id=lead_corrected.id,
            user_id='user-1',
            status='queued',
            campaign_id=None,
        )
        db.session.add_all([item_failed, item_corrected])
        db.session.commit()

        client = MagicMock()
        client.iter_order_contacts.return_value = [
            {
                'addressStatus': 'Failed',
                'addressFailureReason': 'USPS unknown',
                'meta': {'data': {'lead_id': lead_failed.id}},
            },
            {
                'addressStatus': 'Corrected',
                'address1': '2041 W Cuyler Ave',
                'city': 'Chicago',
                'state': 'IL',
                'zip': '60618-3005',
                'meta': {'data': {'lead_id': lead_corrected.id}},
            },
            {
                'addressStatus': 'Verified',
                'meta': {'data': {'lead_id': 999999}},
            },
        ]

        svc = MailCampaignService()
        svc._timeline = MagicMock()
        summary = svc._sync_order_address_statuses(
            campaign, client, refresh_scoring=False,
        )

        assert summary['failed'] == 1
        assert summary['corrected'] == 1
        assert summary['verified'] == 1
        db.session.refresh(item_failed)
        db.session.refresh(lead_corrected)
        assert item_failed.status == 'invalid_address'
        assert lead_corrected.mailing_address == '2041 W Cuyler Ave'


def test_queue_feedback_fallback_ignores_other_campaign_items(app):
    """Failed sync for an old order must not mutate another campaign's queue row."""
    with app.app_context():
        from app import db
        from app.models import Lead, MailCampaign, MailQueueItem

        lead = Lead(
            property_street='4 Other Camp St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_address='Bad Addr',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            owner_user_id='user-1',
            up_next_to_mail=True,
        )
        db.session.add(lead)
        db.session.flush()
        old_campaign = MailCampaign(
            status='cancelled',
            lead_count=1,
            olc_order_id='111',
            created_by='user-1',
        )
        new_campaign = MailCampaign(
            status='submitted',
            lead_count=1,
            olc_order_id='222',
            created_by='user-1',
        )
        db.session.add_all([old_campaign, new_campaign])
        db.session.flush()
        new_item = MailQueueItem(
            lead_id=lead.id,
            user_id='user-1',
            status='queued',
            campaign_id=new_campaign.id,
        )
        db.session.add(new_item)
        db.session.commit()

        svc = MailCampaignService()
        by_lead = svc._queue_items_by_lead_for_feedback(old_campaign, [lead.id])
        assert by_lead.get(lead.id) is None

        client = MagicMock()
        client.iter_order_contacts.return_value = [
            {
                'addressStatus': 'Failed',
                'addressFailureReason': 'USPS unknown',
                'meta': {'data': {'lead_id': lead.id}},
            },
        ]
        svc._timeline = MagicMock()
        summary = svc._sync_order_address_statuses(
            old_campaign, client, refresh_scoring=False,
        )
        assert summary['failed'] == 1
        db.session.refresh(new_item)
        db.session.refresh(lead)
        assert new_item.status == 'queued'
        assert lead.up_next_to_mail is True


def test_sync_campaign_analytics_keeps_cancelled_status(app):
    """Refreshing a cancelled campaign with olc_order_id must not flip to mailed."""
    with app.app_context():
        from app import db
        from app.models import MailCampaign

        campaign = MailCampaign(
            status='cancelled',
            lead_count=0,
            olc_order_id='2128215',
            created_by='user-1',
        )
        db.session.add(campaign)
        db.session.commit()

        client = MagicMock()
        client.get_order_analytics.return_value = {
            'data': {
                'orderItemStatuses': {'Mailed': 10, 'Delivered': 2},
                'geoChart': {'scannedOrderItems': 1, 'notScannedOrderItems': 9},
            },
        }
        client.iter_order_contacts.return_value = []

        svc = MailCampaignService()
        svc._config_service = MagicMock()
        svc._config_service.get_client.return_value = client

        updated = svc.sync_campaign_analytics(campaign.id)
        assert updated.status == 'cancelled'
        assert updated.delivery_stats == {'Mailed': 10, 'Delivered': 2}
        assert updated._address_feedback_summary['verified'] == 0
