"""Tests for PhoneConfidenceService."""
import pytest

from app.services.phone_confidence_service import PhoneConfidenceService


class TestParseHubspotPhoneLine:
    def test_extracts_phone_and_confirmed_annotation(self):
        phone, notes = PhoneConfidenceService.parse_hubspot_phone_line(
            '1) (630) 430-5720 CONFIRMED'
        )
        assert phone is not None
        assert '430' in phone
        assert notes == 'CONFIRMED'

    def test_extracts_disconnected_annotation(self):
        phone, notes = PhoneConfidenceService.parse_hubspot_phone_line(
            '(630) 202-3839 (disconnected)'
        )
        assert phone is not None
        assert 'disconnected' in (notes or '').lower()

    def test_empty_line_returns_none(self):
        assert PhoneConfidenceService.parse_hubspot_phone_line('') == (None, None)


class TestConfidenceHelpers:
    def test_confidence_from_annotation_confirmed(self):
        assert PhoneConfidenceService.confidence_from_annotation('CONFIRMED') == 90

    def test_confidence_from_annotation_rejects_incorrect_and_not_good(self):
        assert PhoneConfidenceService.confidence_from_annotation('incorrect number') == 5
        assert PhoneConfidenceService.confidence_from_annotation('not good') == 5

    def test_confidence_from_annotation_disconnected_before_confirmed(self):
        assert PhoneConfidenceService.confidence_from_annotation('confirmed, now disconnected') == 5

    def test_parse_phones_primary_disconnected_wins_over_hubspot_primary(self):
        props = {
            'phone': '(630) 430-5720',
            'additional_phone_numbers': '1) (630) 430-5720 disconnected',
        }
        parsed = PhoneConfidenceService.parse_phones_from_hubspot_props(props)
        assert len(parsed) == 1
        assert 'disconnect' in (parsed[0][1] or '').lower()
        assert PhoneConfidenceService.confidence_from_annotation(parsed[0][1]) == 5

    def test_merge_prefers_confirmed_over_bare_primary(self):
        merged = PhoneConfidenceService.merge_parsed_phones([
            ('(630) 430-5720', None, 'other'),
            ('6304305720', 'CONFIRMED', 'other'),
        ])
        assert len(merged) == 1
        assert merged[0][1] == 'CONFIRMED'
        assert PhoneConfidenceService.confidence_from_annotation(merged[0][1]) == 90

    def test_parse_phones_from_props_merges_additional_confirmed(self):
        props = {
            'phone': '(630) 430-5720',
            'additional_phone_numbers': '1) (630) 430-5720 CONFIRMED\n2) (630) 202-3839 disconnected',
        }
        parsed = PhoneConfidenceService.parse_phones_from_hubspot_props(props)
        by_digits = {
            PhoneConfidenceService.normalize_phone(v): (v, n)
            for v, n, _ in parsed
        }
        assert by_digits['6304305720'][1] == 'CONFIRMED'
        assert 'disconnect' in (by_digits['6302023839'][1] or '').lower()

    def test_confidence_from_annotation_disconnected(self):
        assert PhoneConfidenceService.confidence_from_annotation('disconnected') == 5

    def test_confidence_from_annotation_wn_nis_family_na(self):
        assert PhoneConfidenceService.confidence_from_annotation('WN') == 5
        assert PhoneConfidenceService.confidence_from_annotation('NIS') == 5
        assert PhoneConfidenceService.confidence_from_annotation('Not in service') == 5
        assert PhoneConfidenceService.confidence_from_annotation('Son of the Owner') == 25
        assert PhoneConfidenceService.confidence_from_annotation('NA') == 35

    def test_sort_prefers_hubspot_primary_over_alphabetical(self):
        phones = [
            {'value': '(630) 111-0000', 'confidence_score': 50, 'notes': None, 'label': 'other'},
            {
                'value': '(312) 999-0000',
                'confidence_score': 50,
                'notes': 'HubSpot primary',
                'label': 'other',
            },
        ]
        sorted_phones = PhoneConfidenceService.sort_phones_for_display(phones)
        assert sorted_phones[0]['value'] == '(312) 999-0000'

    def test_confidence_from_outcome_answered(self):
        assert PhoneConfidenceService.confidence_from_outcome('answered', 50) == 85

    def test_confidence_from_outcome_wrong_number(self):
        assert PhoneConfidenceService.confidence_from_outcome('wrong_number', 90) == 5

    def test_sort_phones_for_display(self):
        phones = [
            {'value': '111', 'confidence_score': 20},
            {'value': '222', 'confidence_score': 90},
        ]
        sorted_phones = PhoneConfidenceService.sort_phones_for_display(phones)
        assert sorted_phones[0]['value'] == '222'

    def test_serialize_contact_phone_defaults_confidence(self):
        from app.models.contact_phone import ContactPhone

        phone = ContactPhone(
            id=1,
            contact_id=2,
            value='6304305720',
            label='mobile',
            confidence_score=None,
            notes='maybe',
        )
        payload = PhoneConfidenceService.serialize_contact_phone(phone)
        assert payload is not None
        assert payload['id'] == 1
        assert payload['value'] == '6304305720'
        assert payload['confidence_score'] == 50
        assert payload['notes'] == 'maybe'
        assert 'contact_id' not in payload

    def test_serialize_contact_phone_include_contact_id(self):
        from app.models.contact_phone import ContactPhone

        phone = ContactPhone(
            id=1,
            contact_id=7,
            value='6302023839',
            label='other',
            confidence_score=80,
        )
        payload = PhoneConfidenceService.serialize_contact_phone(
            phone, include_contact_id=True,
        )
        assert payload is not None
        assert payload['contact_id'] == 7
        assert payload['confidence_score'] == 80

    def test_serialize_contact_phone_skips_blank_value(self):
        from app.models.contact_phone import ContactPhone

        blank = ContactPhone(
            id=2,
            contact_id=7,
            value='   ',
            label='other',
            confidence_score=50,
        )
        assert PhoneConfidenceService.serialize_contact_phone(blank) is None
        assert PhoneConfidenceService.serialize_contact_phone(value='') is None

    def test_serialize_contact_phones_skips_blank_rows(self):
        from app.models.contact_phone import ContactPhone

        phones = [
            ContactPhone(id=1, contact_id=1, value='6304305720', label='mobile', confidence_score=90),
            ContactPhone(id=2, contact_id=1, value='  ', label='other', confidence_score=50),
        ]
        payloads = PhoneConfidenceService.serialize_contact_phones(phones)
        assert len(payloads) == 1
        assert payloads[0]['value'] == '6304305720'
        assert payloads[0]['confidence_score'] == 90


def test_update_from_call_updates_contact_phone(app):
    with app.app_context():
        from app import db
        from app.models import Lead
        from app.models.contact import Contact
        from app.models.contact_phone import ContactPhone
        from app.models.property_contact import PropertyContact

        lead = Lead(
            property_street='99 Phone Test St',
            lead_status='mailing_no_contact_made',
            has_phone=True,
            has_email=True,
            has_property_match=True,
            analysis_complete=True,
            lead_score=50.0,
        )
        db.session.add(lead)
        db.session.flush()

        contact = Contact(first_name='Test', last_name='Owner', role='owner')
        db.session.add(contact)
        db.session.flush()

        db.session.add(PropertyContact(
            property_id=lead.id,
            contact_id=contact.id,
            role='owner',
            is_primary=True,
        ))

        phone = ContactPhone(
            contact_id=contact.id,
            value='6304305720',
            label='mobile',
            confidence_score=50,
        )
        db.session.add(phone)
        db.session.commit()

        PhoneConfidenceService.update_from_call(
            lead.id,
            'answered',
            contact_phone_id=phone.id,
        )
        db.session.commit()

        updated = ContactPhone.query.get(phone.id)
        assert updated.confidence_score == 85
        assert updated.last_outcome == 'answered'


def test_sync_phones_from_hubspot_contact_applies_annotations(app):
    with app.app_context():
        from app import db
        from app.models import Lead
        from app.models.contact import Contact
        from app.models.contact_phone import ContactPhone
        from app.models.hubspot_contact import HubSpotContact
        from app.models.property_contact import PropertyContact

        lead = Lead(
            property_street='2553 N Drake Ave',
            owner_first_name='Gilberto',
            owner_last_name='Olivares',
            lead_status='mailing_no_contact_made',
            has_phone=True,
            has_email=True,
            has_property_match=True,
            analysis_complete=True,
            lead_score=50.0,
        )
        db.session.add(lead)
        db.session.flush()

        contact = Contact(first_name='Gilberto', last_name='Olivares', role='owner')
        db.session.add(contact)
        db.session.flush()
        db.session.add(PropertyContact(
            property_id=lead.id,
            contact_id=contact.id,
            role='owner',
            is_primary=True,
        ))

        db.session.add(ContactPhone(
            contact_id=contact.id,
            value='6304305720',
            label='other',
            confidence_score=50,
        ))
        db.session.flush()

        hs_contact = HubSpotContact(
            hubspot_id='999001',
            raw_payload={
                'properties': {
                    'phone': '(630) 430-5720',
                    'additional_phone_numbers': '1) (630) 430-5720 CONFIRMED',
                },
            },
        )
        db.session.add(hs_contact)
        db.session.commit()

        updated = PhoneConfidenceService.sync_phones_from_hubspot_contact(lead.id, hs_contact)
        db.session.commit()

        assert updated >= 1
        phone = ContactPhone.query.filter_by(contact_id=contact.id).first()
        assert phone.notes == 'CONFIRMED'
        assert phone.confidence_score == 90
