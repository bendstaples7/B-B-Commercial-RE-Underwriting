"""QueueService.membership_for_lead uses the same filters as list endpoints."""
from datetime import date, timedelta

from app.services.queue_service import QueueService


def _make_lead(app, street, **kwargs):
    from app import db
    from app.models import Lead

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
        recommended_action=None,
        review_required=False,
        unanswered_call_count=0,
        owner_user_id='membership-test-user',
    )
    defaults.update(kwargs)
    lead = Lead(property_street=street, **defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


class TestMembershipForLead:
    def test_previously_warm_and_missing_match(self, app):
        lead = _make_lead(
            app,
            '100 Warm St',
            is_warm=True,
            has_property_match=False,
        )
        svc = QueueService(owner_user_id='membership-test-user')
        keys = {m['key'] for m in svc.membership_for_lead(lead.id)}
        assert 'previously-warm' in keys
        assert 'missing-property-match' in keys

    def test_follow_up_overdue_via_ra_and_stale_contact(self, app):
        lead = _make_lead(
            app,
            '200 Overdue Ave',
            recommended_action='follow_up_now',
            last_contact_date=date.today() - timedelta(days=10),
        )
        svc = QueueService(owner_user_id='membership-test-user')
        keys = {m['key'] for m in svc.membership_for_lead(lead.id)}
        assert 'follow-up-overdue' in keys

    def test_do_not_contact(self, app):
        lead = _make_lead(
            app,
            '300 DNC Blvd',
            lead_status='do_not_contact',
        )
        svc = QueueService(owner_user_id='membership-test-user')
        memberships = svc.membership_for_lead(lead.id)
        assert any(m['key'] == 'do-not-contact' for m in memberships)
        dnc = next(m for m in memberships if m['key'] == 'do-not-contact')
        assert dnc['path'] == '/queues/do-not-contact'
        assert dnc['label'] == 'Do Not Contact'
