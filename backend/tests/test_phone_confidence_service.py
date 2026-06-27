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
