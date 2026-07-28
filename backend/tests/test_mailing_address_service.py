"""Tests for canonical owner mailing normalize / heal / readiness."""
from __future__ import annotations

from app.models.lead import Lead
from app.services.mailing_address_service import (
    apply_owner_mailing,
    apply_parsed_owner_mailing,
    heal_incomplete_owner_mailings,
    normalize_mailing_parts,
    owner_mailing_needs_normalize,
    owner_mailing_readiness_detail,
)


def _lead(**kwargs) -> Lead:
    defaults = {
        'id': 1,
        'owner_first_name': 'Fran',
        'owner_last_name': 'Solis',
        'mailing_address': None,
        'mailing_city': None,
        'mailing_state': None,
        'mailing_zip': None,
        'property_street': '1 Property St',
        'property_city': 'Chicago',
        'property_state': 'IL',
        'property_zip': '60601',
    }
    defaults.update(kwargs)
    return Lead(**defaults)


class TestNormalizeMailingParts:
    def test_tab_separated_short_zip(self):
        assert normalize_mailing_parts(
            '167 Lakeview Ter\tSandy Hook\tCT\t6482',
        ) == ('167 Lakeview Ter', 'Sandy Hook', 'CT', '06482')

    def test_structured_passthrough(self):
        assert normalize_mailing_parts(
            '167 Lakeview Ter', 'Sandy Hook', 'CT', '06482',
        ) == ('167 Lakeview Ter', 'Sandy Hook', 'CT', '06482')

    def test_city_column_embeds_state_zip(self):
        assert normalize_mailing_parts(
            '3105 W Palmer Blvd', 'Chicago, IL 60647', None, None,
        ) == ('3105 W Palmer Blvd', 'Chicago', 'IL', '60647')

    def test_multi_space_separated_short_zip(self):
        # Fixed-width / pasted dumps sometimes use runs of spaces instead of
        # tabs to separate columns — must normalize the same as tab-separated.
        assert normalize_mailing_parts(
            '167 Lakeview Ter   Sandy Hook   CT   6482',
        ) == ('167 Lakeview Ter', 'Sandy Hook', 'CT', '06482')

    def test_structured_preserves_zip_plus_four(self):
        # OLC Corrected / USPS feedback often includes ZIP+4; parse must not
        # collapse it to ZIP5 when locality is already structured.
        assert normalize_mailing_parts(
            '2041 W Cuyler Ave', 'Chicago', 'IL', '60618-3005',
        ) == ('2041 W Cuyler Ave', 'Chicago', 'IL', '60618-3005')


class TestApplyOwnerMailing:
    def test_fill_empty_from_tab_dump(self):
        lead = _lead()
        updated = apply_owner_mailing(
            lead,
            street='167 Lakeview Ter\tSandy Hook\tCT\t6482',
            fill_empty_only=True,
        )
        assert 'mailing_address' in updated
        assert lead.mailing_address == '167 Lakeview Ter'
        assert lead.mailing_city == 'Sandy Hook'
        assert lead.mailing_state == 'CT'
        assert lead.mailing_zip == '06482'

    def test_fill_empty_does_not_overwrite_clean_street(self):
        lead = _lead(
            mailing_address='10 Clean St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
        )
        updated = apply_owner_mailing(
            lead,
            street='999 Other\tChicago\tIL\t60601',
            fill_empty_only=True,
        )
        assert updated == []
        assert lead.mailing_address == '10 Clean St'


class TestReadinessAndApplyParsed:
    def test_readiness_can_apply_tabular(self):
        lead = _lead(
            mailing_address='167 Lakeview Ter\tSandy Hook\tCT\t6482',
        )
        detail = owner_mailing_readiness_detail(lead)
        assert detail['is_mailable'] is True  # in-memory parse succeeds
        assert detail['parsed']['zip'] == '06482'
        assert detail['can_apply_parsed'] is True

    def test_readiness_can_apply_city_column_dump(self):
        lead = _lead(
            mailing_address='3105 W Palmer Blvd',
            mailing_city='Chicago, IL 60647',
        )
        detail = owner_mailing_readiness_detail(lead)
        assert detail['parsed'] == {
            'street': '3105 W Palmer Blvd',
            'city': 'Chicago',
            'state': 'IL',
            'zip': '60647',
        }
        assert detail['can_apply_parsed'] is True

    def test_apply_parsed_persists_columns(self):
        lead = _lead(
            mailing_address='167 Lakeview Ter\tSandy Hook\tCT\t6482',
        )
        result = apply_parsed_owner_mailing(lead)
        assert result['applied'] is True
        assert lead.mailing_address == '167 Lakeview Ter'
        assert lead.mailing_city == 'Sandy Hook'
        assert lead.mailing_zip == '06482'
        assert result['detail']['can_apply_parsed'] is False


class TestHealIncompleteOwnerMailings:
    def test_heal_single_lead(self, app):
        with app.app_context():
            from app import db

            lead = Lead(
                owner_first_name='Fran',
                owner_last_name='Solis',
                mailing_address='167 Lakeview Ter\tSandy Hook\tCT\t6482',
                property_street='1 Property St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60601',
                lead_status='mailing_no_contact_made',
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            assert owner_mailing_needs_normalize(lead) is True
            summary = heal_incomplete_owner_mailings(
                lead_id=lead_id,
                dry_run=False,
                commit=True,
                persist_cursor=False,
            )
            assert summary['healed'] == 1
            refreshed = Lead.query.get(lead_id)
            assert refreshed.mailing_address == '167 Lakeview Ter'
            assert refreshed.mailing_city == 'Sandy Hook'
            assert refreshed.mailing_zip == '06482'
