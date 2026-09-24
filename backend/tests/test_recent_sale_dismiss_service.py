"""Dismiss incorrect recent-sale holds (wrong condo unit / PIN)."""
from datetime import date, timedelta

from app import db
from app.models import Lead, LeadTask
from app.services.recent_sale_dismiss_service import dismiss_incorrect_recent_sale


def test_dismiss_incorrect_recent_sale_clears_sale_and_hold(app):
    with app.app_context():
        lead = Lead(
            property_street='717 W Bittersweet Pl Unit L2',
            property_city='Chicago',
            property_state='IL',
            property_zip='60613',
            county_assessor_pin='14163050211081',
            has_property_match=True,
            most_recent_sale=(date.today() - timedelta(days=30)).isoformat(),
            acquisition_date=date.today() - timedelta(days=30),
            most_recent_sale_price=450000,
            lead_status='skip_trace',
            needs_skip_trace=False,
            owner_first_name='',
            owner_user_id='user-test',
        )
        db.session.add(lead)
        db.session.flush()
        hold = LeadTask(
            lead_id=lead.id,
            title='Recent sale hold — re-verify owner',
            task_type='skip_trace_owner',
            status='open',
            workflow_key='recent_sale_hold',
            due_date=date.today() + timedelta(days=700),
        )
        db.session.add(hold)
        db.session.commit()
        lead_id = lead.id
        hold_id = hold.id

        result = dismiss_incorrect_recent_sale(
            db.session.get(Lead, lead_id),
            actor='tester',
            reason='not_this_unit',
            clear_pin=True,
        )

        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.most_recent_sale is None
        assert refreshed.acquisition_date is None
        assert refreshed.most_recent_sale_price is None
        assert refreshed.county_assessor_pin is None
        assert refreshed.has_property_match is False
        assert refreshed.needs_skip_trace is True
        assert refreshed.lead_status == 'skip_trace'
        assert result['pin_cleared'] is True
        assert hold_id in result['completed_hold_task_ids']
        assert db.session.get(LeadTask, hold_id).status == 'completed'
