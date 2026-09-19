"""Direct-mail response attribution for Channel ROI."""
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.mail_campaign import MailCampaign
from app.models.mail_campaign_lead_attribution import MailCampaignLeadAttribution
from app.models.mail_queue_item import MailQueueItem
from app.services.call_log_service import CallLogService
from app.services.mail_campaign_service import (
    MailCampaignService,
    backfill_inbound_mail_responses,
)


def _lead(street='544 West Oakdale Ave', owner='test-user'):
    lead = Lead(
        property_street=street,
        lead_status='mailing_no_contact_made',
        owner_user_id=owner,
    )
    db.session.add(lead)
    db.session.commit()
    return lead


def _campaign(*, status='submitted', created_by='test-user', submitted_at=None, lead_count=12):
    campaign = MailCampaign(
        status=status,
        lead_count=lead_count,
        created_by=created_by,
        template_name='Yellow letter',
        submitted_at=submitted_at or datetime.now(timezone.utc) - timedelta(days=2),
        response_count=0,
    )
    db.session.add(campaign)
    db.session.commit()
    return campaign


def _queue(lead_id, campaign_id, *, status='submitted', user_id='test-user'):
    item = MailQueueItem(
        lead_id=lead_id,
        campaign_id=campaign_id,
        user_id=user_id,
        status=status,
    )
    db.session.add(item)
    db.session.commit()
    return item


def test_submitted_batch_is_recent_and_counts_inbound_call(app):
    """A lead still marked submitted on the latest batch is a mailer response."""
    with app.app_context():
        lead = _lead()
        campaign = _campaign()
        _queue(lead.id, campaign.id)

        recent = MailCampaignService().get_recent_for_lead(lead.id, 'test-user')
        assert [c.id for c in recent] == [campaign.id]

        CallLogService().log_call(
            lead.id,
            'answered',
            None,
            'called about the letter',
            actor='test-user',
            mail_campaign_id=campaign.id,
            direction='inbound',
        )

        saved = MailCampaign.query.get(campaign.id)
        assert saved.response_count == 1
        assert MailCampaignLeadAttribution.query.filter_by(
            lead_id=lead.id, mail_campaign_id=campaign.id,
        ).count() == 1

        entry = (
            LeadTimelineEntry.query.filter_by(lead_id=lead.id, event_type='call_logged')
            .order_by(LeadTimelineEntry.id.desc())
            .first()
        )
        assert (entry.event_metadata or {}).get('attributed_to_mail') is True

        CallLogService().log_call(
            lead.id,
            'answered',
            None,
            'called again',
            actor='test-user',
            mail_campaign_id=campaign.id,
            direction='inbound',
        )
        saved = MailCampaign.query.get(campaign.id)
        assert saved.response_count == 1


def test_soft_deleted_first_call_does_not_double_count(app):
    with app.app_context():
        lead = _lead('100 Ledger St')
        campaign = _campaign()
        _queue(lead.id, campaign.id, status='sent')
        campaign.status = 'mailed'
        db.session.add(campaign)
        db.session.commit()

        svc = CallLogService()
        entry = svc.log_call(
            lead.id, 'answered', None, 'first', actor='test-user',
            mail_campaign_id=campaign.id, direction='inbound',
        )
        entry.is_deleted = True
        db.session.add(entry)
        db.session.commit()

        svc.log_call(
            lead.id, 'answered', None, 'second', actor='test-user',
            mail_campaign_id=campaign.id, direction='inbound',
        )
        assert MailCampaign.query.get(campaign.id).response_count == 1


def test_pending_or_other_user_batch_is_not_attributable(app):
    with app.app_context():
        lead = _lead('200 Pending St')
        pending = _campaign(status='pending')
        _queue(lead.id, pending.id)
        CallLogService().log_call(
            lead.id, 'answered', None, 'too early', actor='test-user',
            mail_campaign_id=pending.id, direction='inbound',
        )
        assert MailCampaign.query.get(pending.id).response_count == 0

        foreign_lead = _lead('201 Foreign St', owner='other-user')
        foreign = _campaign(created_by='someone-else')
        _queue(foreign_lead.id, foreign.id, user_id='someone-else')
        CallLogService().log_call(
            foreign_lead.id, 'answered', None, 'not mine', actor='test-user',
            mail_campaign_id=foreign.id, direction='inbound',
        )
        assert MailCampaign.query.get(foreign.id).response_count == 0


def test_inbound_text_counts_once(app):
    with app.app_context():
        lead = _lead('300 Text St')
        campaign = _campaign()
        _queue(lead.id, campaign.id)
        CallLogService().log_note(
            lead.id,
            'Got your letter',
            actor='test-user',
            activity_kind='text',
            mail_campaign_id=campaign.id,
        )
        assert MailCampaign.query.get(campaign.id).response_count == 1
        entry = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, event_type='note_added',
        ).order_by(LeadTimelineEntry.id.desc()).first()
        assert entry.summary.startswith('Inbound text:')
        assert (entry.event_metadata or {}).get('activity_kind') == 'text'
        assert (entry.event_metadata or {}).get('attributed_to_mail') is True


def test_backfill_attributes_unconfirmed_inbound_call(app):
    """The call already logged without a source still counts after heal."""
    with app.app_context():
        lead = _lead('544 W Oakdale')
        campaign = _campaign(submitted_at=datetime.now(timezone.utc) - timedelta(days=3))
        _queue(lead.id, campaign.id)

        CallLogService().log_call(
            lead.id,
            'answered',
            None,
            'just called in',
            actor='test-user',
            direction='inbound',
        )
        assert MailCampaign.query.get(campaign.id).response_count == 0

        stats = backfill_inbound_mail_responses()
        db.session.commit()

        assert stats['stamped'] == 1
        saved = MailCampaign.query.get(campaign.id)
        assert saved.response_count == 1
        entry = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, event_type='call_logged',
        ).first()
        meta = entry.event_metadata or {}
        assert meta.get('attributed_to_mail') is True
        assert meta.get('mail_campaign_id') == campaign.id

        again = backfill_inbound_mail_responses()
        db.session.commit()
        assert again['stamped'] == 0
        assert MailCampaign.query.get(campaign.id).response_count == 1


def test_backfill_ignores_outbound_and_calls_before_the_mailer(app):
    with app.app_context():
        lead = _lead('400 Before Mail St')
        CallLogService().log_call(
            lead.id, 'no_answer', None, 'before', actor='test-user', direction='inbound',
        )
        old = LeadTimelineEntry.query.filter_by(lead_id=lead.id).first()
        old.occurred_at = datetime.now(timezone.utc) - timedelta(days=30)
        db.session.add(old)
        db.session.commit()

        campaign = _campaign(submitted_at=datetime.now(timezone.utc) - timedelta(days=2))
        _queue(lead.id, campaign.id)

        CallLogService().log_call(
            lead.id, 'voicemail', None, 'I called them', actor='test-user', direction='outbound',
        )
        backfill_inbound_mail_responses()
        db.session.commit()
        assert MailCampaign.query.get(campaign.id).response_count == 0
