"""HubSpot additional_addresses → lead mailing / address_2 enrichment."""
from __future__ import annotations

from app import db
from app.models.hubspot_contact import HubSpotContact
from app.models.lead import Lead
from app.services.hubspot_matcher_service import HubSpotMatcherService
from app.services.open_letter_contact_mapper import lead_to_olc_contact


def _contact(props: dict, hubspot_id: str = 'hs_addr_1') -> HubSpotContact:
    return HubSpotContact(
        hubspot_id=hubspot_id,
        raw_payload={'properties': props},
    )


class TestHubSpotAdditionalAddressesEnrichment:
    def test_additional_promotes_to_mailing_when_primary_empty(self, app):
        with app.app_context():
            lead = Lead(
                property_street='2627 W Leland Ave 1 Chicago IL 60625',
                lead_status='mailing_contacted_interested',
            )
            db.session.add(lead)
            db.session.flush()

            hs = _contact({
                'firstname': 'Anthony',
                'lastname': 'Skrobowski',
                'address': None,
                'city': None,
                'state': None,
                'zip': None,
                'additional_addresses': '2041 W Cuyler Ave Chicago IL 60618',
            })
            db.session.add(hs)
            db.session.flush()

            updated = HubSpotMatcherService().enrich_lead_from_contact(lead, hs)
            assert 'mailing_address' in updated
            assert lead.mailing_address == '2041 W Cuyler Ave'
            assert lead.mailing_city == 'Chicago'
            assert lead.mailing_state == 'IL'
            assert lead.mailing_zip == '60618'
            assert lead.address_2 is None

    def test_orphan_hubspot_city_does_not_override_additional_locality(self, app):
        """HS city/state/zip without a primary street must not win over additional."""
        with app.app_context():
            lead = Lead(
                property_street='2627 W Leland Ave',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            hs = _contact({
                'city': 'Bolingbrook',
                'state': 'IL',
                'zip': '60440',
                'additional_addresses': '2041 W Cuyler Ave Chicago IL 60618',
            }, hubspot_id='hs_addr_orphan')
            db.session.add(hs)
            db.session.flush()

            HubSpotMatcherService().enrich_lead_from_contact(lead, hs)
            assert lead.mailing_address == '2041 W Cuyler Ave'
            assert lead.mailing_city == 'Chicago'
            assert lead.mailing_state == 'IL'
            assert lead.mailing_zip == '60618'

    def test_additional_goes_to_address_2_when_mailing_present(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                mailing_address='100 Owner St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            hs = _contact({
                'address': '100 Owner St',
                'city': 'Chicago',
                'state': 'IL',
                'zip': '60601',
                'additional_addresses': '2041 W Cuyler Ave Chicago IL 60618',
            }, hubspot_id='hs_addr_2')
            db.session.add(hs)
            db.session.flush()

            updated = HubSpotMatcherService().enrich_lead_from_contact(lead, hs)
            assert lead.mailing_address == '100 Owner St'
            assert 'address_2' in updated
            assert lead.address_2 == '2041 W Cuyler Ave Chicago IL 60618'

    def test_first_additional_promotes_rest_to_address_2(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            hs = _contact({
                'additional_addresses': (
                    '2041 W Cuyler Ave Chicago IL 60618\n'
                    '198 Karen Cir Bolingbrook IL 60440'
                ),
            }, hubspot_id='hs_addr_multi')
            db.session.add(hs)
            db.session.flush()

            HubSpotMatcherService().enrich_lead_from_contact(lead, hs)
            assert lead.mailing_address == '2041 W Cuyler Ave'
            assert lead.mailing_city == 'Chicago'
            assert lead.mailing_zip == '60618'
            assert lead.address_2 == '198 Karen Cir Bolingbrook IL 60440'

    def test_completes_incomplete_mailing_from_same_street_additional(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                mailing_address='100 Owner St',
                mailing_city=None,
                mailing_state=None,
                mailing_zip=None,
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            hs = _contact({
                'additional_addresses': '100 Owner Street Chicago IL 60601',
            }, hubspot_id='hs_addr_complete')
            db.session.add(hs)
            db.session.flush()

            HubSpotMatcherService().enrich_lead_from_contact(lead, hs)
            assert lead.mailing_address == '100 Owner St'
            assert lead.mailing_city == 'Chicago'
            assert lead.mailing_state == 'IL'
            assert lead.mailing_zip == '60601'
            assert lead.address_2 is None

    def test_does_not_overwrite_existing_mailing_or_unit_address_2(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                mailing_address='Keep Me St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
                address_2='Apt 2B',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            hs = _contact({
                'address': 'Override Primary',
                'city': 'Naperville',
                'state': 'IL',
                'zip': '60540',
                'additional_addresses': 'Brand New Extra Rd Chicago IL 60618',
            }, hubspot_id='hs_addr_3')
            db.session.add(hs)
            db.session.flush()

            HubSpotMatcherService().enrich_lead_from_contact(lead, hs)
            assert lead.mailing_address == 'Keep Me St'
            assert lead.mailing_city == 'Chicago'
            # Full street must not append onto unit-style address_2.
            assert lead.address_2 == 'Apt 2B'

    def test_skips_additional_duplicate_of_mailing(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                mailing_address='2041 W Cuyler Avenue',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60618',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            hs = _contact({
                'additional_addresses': '2041 W Cuyler Ave Chicago IL 60618',
            }, hubspot_id='hs_addr_4')
            db.session.add(hs)
            db.session.flush()

            updated = HubSpotMatcherService().enrich_lead_from_contact(lead, hs)
            assert 'address_2' not in updated
            assert lead.address_2 is None

    def test_olc_omits_full_street_address_2(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                mailing_address='100 Owner St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
                address_2='2041 W Cuyler Ave Chicago IL 60618',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            contact = lead_to_olc_contact(lead)
            assert contact['address1'] == '100 Owner St'
            assert contact['address2'] is None

    def test_olc_omits_multiline_address_2_with_full_street(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                mailing_address='100 Owner St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
                address_2='2041 W Cuyler Ave Chicago IL 60618\nApt 2B',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            contact = lead_to_olc_contact(lead)
            assert contact['address2'] is None

    def test_olc_keeps_unit_style_address_2(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Property St',
                mailing_address='100 Owner St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
                address_2='Apt 2B',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.flush()

            contact = lead_to_olc_contact(lead)
            assert contact['address2'] == 'Apt 2B'
