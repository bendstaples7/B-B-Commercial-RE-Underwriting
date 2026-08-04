"""Tests for Part D — auto demote mailing_no_contact_made -> skip_trace.

Symmetric with test_skip_trace_mailable_heal.py (which promotes skip_trace ->
mailing once mailable): these cover the reverse drift, where a mailing-stage
lead's owner mailing address is no longer complete.
"""
from __future__ import annotations

from app import db
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.services.skip_trace_enqueue import (
    MAILING_DEMOTE_REASON,
    maybe_demote_mailing_if_not_mailable,
)


def _mailing_lead(**kwargs) -> Lead:
    defaults = dict(
        owner_first_name='Test',
        owner_last_name='Owner',
        property_street='4301 N Saint Louis',
        property_city='Chicago',
        property_state='IL',
        property_zip='60618',
        mailing_address='6434 N Oakley Ave',
        mailing_city='Chicago',
        mailing_state='IL',
        mailing_zip='60645',
        owner_user_id='user-demote',
        lead_status='mailing_no_contact_made',
        lead_category='residential',
        lead_score=50,
        has_property_match=True,
        source_type='import',
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.flush()
    return lead


class TestMaybeDemoteMailingIfNotMailable:
    def test_blank_street_demotes(self, app):
        with app.app_context():
            lead = _mailing_lead(mailing_address='')
            db.session.commit()

            result = maybe_demote_mailing_if_not_mailable(lead)

            assert result['demoted'] is True
            assert result['lead_status'] == 'skip_trace'
            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'
            assert lead.needs_skip_trace is True

            handoff = LeadTask.query.filter_by(
                lead_id=lead.id, task_type='skip_trace_owner', status='open',
            ).first()
            assert handoff is not None
            assert handoff.workflow_key == 'awaiting_skip_trace_handoff'

    def test_incomplete_city_state_zip_demotes(self, app):
        with app.app_context():
            lead = _mailing_lead(mailing_city=None, mailing_state=None, mailing_zip=None)
            db.session.commit()

            result = maybe_demote_mailing_if_not_mailable(lead)

            assert result['demoted'] is True
            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'
            assert lead.needs_skip_trace is True

    def test_timeline_entry_records_demote_reason(self, app):
        with app.app_context():
            from app.models.lead_timeline_entry import LeadTimelineEntry

            lead = _mailing_lead(mailing_address='')
            db.session.commit()

            maybe_demote_mailing_if_not_mailable(lead)

            entry = (
                LeadTimelineEntry.query
                .filter_by(lead_id=lead.id, event_type='status_changed')
                .order_by(LeadTimelineEntry.id.desc())
                .first()
            )
            assert entry is not None
            assert entry.event_metadata.get('reason') == MAILING_DEMOTE_REASON
            assert 'no longer complete' in entry.summary

    def test_still_mailable_lead_is_not_demoted(self, app):
        with app.app_context():
            lead = _mailing_lead()
            db.session.commit()

            result = maybe_demote_mailing_if_not_mailable(lead)

            assert result['demoted'] is False
            assert result['reason'] == 'still_mailable'
            db.session.refresh(lead)
            assert lead.lead_status == 'mailing_no_contact_made'

    def test_non_mailing_status_is_a_no_op(self, app):
        with app.app_context():
            lead = _mailing_lead(mailing_address='', lead_status='skip_trace')
            db.session.commit()

            result = maybe_demote_mailing_if_not_mailable(lead)

            assert result['demoted'] is False
            assert result['reason'] == 'not_mailing_status'

    def test_phone_lead_still_call_capable_after_demote(self, app):
        """A phone number means there IS a way to reach the owner — the
        demoted lead must not get stuck on "add contact info"; the owner
        mail gate's phone fallback (lead_scoring_engine) should surface
        call_ready once scoring refreshes after the demote.
        """
        with app.app_context():
            lead = _mailing_lead(
                mailing_address='',
                phone_1='3125551234',
                has_phone=True,
            )
            db.session.commit()

            result = maybe_demote_mailing_if_not_mailable(lead)
            assert result['demoted'] is True

            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'
            assert lead.recommended_action == 'call_ready'
            assert lead.recommended_contact_method == 'phone'

    def test_email_only_lead_gets_ready_for_outreach_after_demote(self, app):
        with app.app_context():
            lead = _mailing_lead(
                mailing_address='',
                email_1='owner@example.com',
                has_email=True,
            )
            db.session.commit()

            maybe_demote_mailing_if_not_mailable(lead)

            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'
            assert lead.recommended_action == 'ready_for_outreach'

    def test_no_contact_info_lead_still_needs_add_contact_info(self, app):
        with app.app_context():
            lead = _mailing_lead(mailing_address='')
            db.session.commit()

            maybe_demote_mailing_if_not_mailable(lead)

            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'
            assert lead.recommended_action == 'add_contact_info'

    def test_commit_false_defers_write(self, app):
        with app.app_context():
            lead = _mailing_lead(mailing_address='')
            db.session.commit()

            result = maybe_demote_mailing_if_not_mailable(lead, commit=False)
            assert result['demoted'] is True

            # In-memory mutation happened, but nothing durable until caller commits.
            assert lead.lead_status == 'skip_trace'
            db.session.commit()
            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'
