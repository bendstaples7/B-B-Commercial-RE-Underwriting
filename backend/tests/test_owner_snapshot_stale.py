"""Tests for contacts_likely_prior_owner and owner snapshot capture."""
from datetime import date, timedelta
from unittest.mock import MagicMock

from app import db
from app.models.lead import Lead
from app.models.lead_owner_snapshot import LeadOwnerSnapshot
from app.models.property_contact import PropertyContact
from app.services.contact_service import ContactService
from app.services.owner_snapshot_service import (
    REASON_CONTACT_REPLACED,
    REASON_RECENT_SALE,
    archive_active_owners_to_former,
    ensure_stale_owner_snapshot,
    list_past_owners_payload,
)
from app.services.scoring_rubric import (
    contacts_likely_prior_owner,
    contacts_need_post_hold_verification,
    contacts_stale_since,
)


def _lead(**kwargs):
    lead = MagicMock()
    lead.acquisition_date = kwargs.get('acquisition_date')
    lead.most_recent_sale = kwargs.get('most_recent_sale')
    lead.date_skip_traced = kwargs.get('date_skip_traced')
    return lead


class TestContactsLikelyPriorOwner:
    def test_false_when_no_sale(self):
        assert contacts_likely_prior_owner(_lead()) is False
        assert contacts_stale_since(_lead()) is None

    def test_true_when_sale_and_never_skip_traced(self):
        sale = date.today() - timedelta(days=30)
        lead = _lead(acquisition_date=sale, date_skip_traced=None)
        assert contacts_likely_prior_owner(lead) is True
        assert contacts_stale_since(lead) == sale.isoformat()

    def test_true_when_skip_traced_before_sale(self):
        sale = date.today() - timedelta(days=10)
        lead = _lead(
            acquisition_date=sale,
            date_skip_traced=sale - timedelta(days=60),
        )
        assert contacts_likely_prior_owner(lead) is True

    def test_false_when_skip_traced_on_sale_date(self):
        sale = date.today() - timedelta(days=10)
        lead = _lead(acquisition_date=sale, date_skip_traced=sale)
        assert contacts_likely_prior_owner(lead) is False
        assert contacts_stale_since(lead) is None

    def test_false_when_skip_traced_after_sale(self):
        sale = date.today() - timedelta(days=40)
        lead = _lead(
            acquisition_date=sale,
            date_skip_traced=sale + timedelta(days=5),
        )
        assert contacts_likely_prior_owner(lead) is False

    def test_false_when_sale_outside_recent_window(self):
        sale = date.today() - timedelta(days=800)
        lead = _lead(acquisition_date=sale, date_skip_traced=None)
        assert contacts_likely_prior_owner(lead) is False
        assert contacts_stale_since(lead) is None

    def test_false_when_year_2000_sale_never_skip_traced(self):
        lead = _lead(acquisition_date=date(2000, 2, 1), date_skip_traced=None)
        assert contacts_likely_prior_owner(lead) is False
        assert contacts_stale_since(lead) is None

    def test_false_when_old_sale_but_skip_traced_after(self):
        sale = date.today() - timedelta(days=800)
        lead = _lead(
            acquisition_date=sale,
            date_skip_traced=sale + timedelta(days=5),
        )
        assert contacts_likely_prior_owner(lead) is False
        assert contacts_stale_since(lead) is None


class TestContactsNeedPostHoldVerification:
    def test_true_shortly_after_hold_ends(self):
        # Hold is 730 days; sale at 800 days is past hold but still post-hold stale.
        sale = date.today() - timedelta(days=800)
        lead = _lead(acquisition_date=sale, date_skip_traced=None)
        assert contacts_likely_prior_owner(lead) is False
        assert contacts_need_post_hold_verification(lead) is True

    def test_false_during_hold_window(self):
        sale = date.today() - timedelta(days=30)
        lead = _lead(acquisition_date=sale, date_skip_traced=None)
        assert contacts_likely_prior_owner(lead) is True
        assert contacts_need_post_hold_verification(lead) is False

    def test_false_for_year_2000_sale(self):
        lead = _lead(acquisition_date=date(2000, 2, 1), date_skip_traced=None)
        assert contacts_need_post_hold_verification(lead) is False

    def test_false_when_skip_traced_after_sale(self):
        sale = date.today() - timedelta(days=800)
        lead = _lead(
            acquisition_date=sale,
            date_skip_traced=sale + timedelta(days=5),
        )
        assert contacts_need_post_hold_verification(lead) is False


class TestOwnerSnapshotService:
    def test_ensure_stale_captures_once_per_sale(self, app):
        with app.app_context():
            lead = Lead(
                property_street='900 Snapshot Ave',
                owner_first_name='Prior',
                owner_last_name='Owner',
                mailing_address='1 Old St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60614',
                acquisition_date=date.today() - timedelta(days=14),
                date_skip_traced=None,
            )
            db.session.add(lead)
            db.session.commit()

            first = ensure_stale_owner_snapshot(lead, commit=True)
            assert first is not None
            assert first.reason == REASON_RECENT_SALE
            assert first.sale_date == lead.acquisition_date
            assert first.payload['owner_names']
            assert first.payload['mailing_address'] == '1 Old St'

            second = ensure_stale_owner_snapshot(lead, commit=True)
            assert second is None
            assert LeadOwnerSnapshot.query.filter_by(lead_id=lead.id).count() == 1

    def test_archive_re_roles_owners_and_snapshots(self, app):
        with app.app_context():
            lead = Lead(
                property_street='901 Archive Ave',
                owner_first_name='Old',
                owner_last_name='Name',
                mailing_address='2 Prior Rd',
                acquisition_date=date.today() - timedelta(days=20),
            )
            db.session.add(lead)
            db.session.commit()

            svc = ContactService()
            contact = svc.create_contact({
                'first_name': 'Old',
                'last_name': 'Name',
                'role': 'owner',
                'phones': [{'value': '555-0100', 'label': 'mobile'}],
            })
            svc.link_contact_to_property(lead.id, contact.id, 'owner', True)

            archived = archive_active_owners_to_former(
                lead, reason=REASON_CONTACT_REPLACED, commit=True,
            )
            assert archived == 1

            link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=contact.id,
            ).first()
            assert link.role == 'former_owner'
            assert link.superseded_at is not None
            assert link.is_primary is False

            snaps = list_past_owners_payload(lead.id)
            assert len(snaps) >= 1
            assert snaps[0]['reason'] == REASON_CONTACT_REPLACED
            assert any(
                (n.get('first_name') == 'Old') for n in snaps[0]['owner_names']
            )

            # Active payload excludes former owners
            active = svc.get_ordered_contacts_payload(lead.id)
            assert active == []

    def test_upsert_archives_unmatched_owners(self, app):
        with app.app_context():
            lead = Lead(
                property_street='902 Replace Ave',
                owner_first_name='Alice',
                owner_last_name='Prior',
            )
            db.session.add(lead)
            db.session.commit()

            svc = ContactService()
            svc.upsert_owners_from_lead(lead, commit=True)

            lead.owner_first_name = 'Bob'
            lead.owner_last_name = 'Buyer'
            db.session.add(lead)
            db.session.commit()

            svc.upsert_owners_from_lead(lead, commit=True)

            former = PropertyContact.query.filter_by(
                property_id=lead.id, role='former_owner',
            ).all()
            owners = PropertyContact.query.filter_by(
                property_id=lead.id, role='owner',
            ).all()
            assert len(former) >= 1
            assert len(owners) == 1
            assert LeadOwnerSnapshot.query.filter_by(
                lead_id=lead.id, reason=REASON_CONTACT_REPLACED,
            ).count() >= 1

    def test_upsert_reactivates_former_owner(self, app):
        with app.app_context():
            lead = Lead(
                property_street='903 Reactivate Ave',
                owner_first_name='Alice',
                owner_last_name='Prior',
                acquisition_date=date.today() - timedelta(days=20),
            )
            db.session.add(lead)
            db.session.commit()

            svc = ContactService()
            svc.upsert_owners_from_lead(lead, commit=True)

            lead.owner_first_name = 'Bob'
            lead.owner_last_name = 'Buyer'
            db.session.add(lead)
            db.session.commit()
            svc.upsert_owners_from_lead(lead, commit=True)

            lead.owner_first_name = 'Alice'
            lead.owner_last_name = 'Prior'
            db.session.add(lead)
            db.session.commit()
            svc.upsert_owners_from_lead(lead, commit=True)

            owners = PropertyContact.query.filter_by(
                property_id=lead.id, role='owner',
            ).all()
            assert len(owners) == 1
            from app.models.contact import Contact
            contact = Contact.query.get(owners[0].contact_id)
            assert contact.first_name == 'Alice'
            assert owners[0].superseded_at is None

    def test_ensure_stale_skips_after_owner_replace(self, app):
        with app.app_context():
            lead = Lead(
                property_street='904 No Fake Snapshot Ave',
                owner_first_name='Alice',
                owner_last_name='Prior',
                mailing_address='1 Old',
                acquisition_date=date.today() - timedelta(days=20),
                date_skip_traced=None,
            )
            db.session.add(lead)
            db.session.commit()

            svc = ContactService()
            svc.upsert_owners_from_lead(lead, commit=True)

            lead.owner_first_name = 'Bob'
            lead.owner_last_name = 'Buyer'
            db.session.add(lead)
            db.session.commit()
            svc.upsert_owners_from_lead(lead, commit=True)

            assert (
                LeadOwnerSnapshot.query.filter_by(
                    lead_id=lead.id, reason=REASON_CONTACT_REPLACED,
                ).count()
                >= 1
            )
            # Must not invent a recent_sale row of Bob (the buyer)
            assert ensure_stale_owner_snapshot(lead, commit=True) is None
            assert (
                LeadOwnerSnapshot.query.filter_by(
                    lead_id=lead.id, reason=REASON_RECENT_SALE,
                ).count()
                == 0
            )
