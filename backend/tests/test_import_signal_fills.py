"""Tests for CRM/sheet import signal fills (CoStar commercial, Units: N)."""
from types import SimpleNamespace

from app.services.helpers.import_signal_fills import (
    apply_import_signal_fills,
    is_commercial_deal_source,
    parse_units_from_deal_description,
    resolve_commercial_category_fill_if_blank,
    resolve_units_fill_if_blank,
)


class TestIsCommercialDealSource:
    def test_costar(self):
        assert is_commercial_deal_source('CoStar') is True
        assert is_commercial_deal_source('co-star list') is True

    def test_cityscape(self):
        assert is_commercial_deal_source('Cityscape') is True

    def test_residential_sources(self):
        assert is_commercial_deal_source('Listsource') is False
        assert is_commercial_deal_source('Driving For Dollars') is False
        assert is_commercial_deal_source(None) is False


class TestParseUnitsFromDealDescription:
    def test_costar_sheet_style(self):
        text = 'Costar  Date ID: 3/7/2022 Not Yet Skip Traced Units: 12'
        assert parse_units_from_deal_description(text) == 12

    def test_units_equals_form(self):
        assert parse_units_from_deal_description('Units=3 duplex') == 3

    def test_unit_singular(self):
        assert parse_units_from_deal_description('Unit: 1') == 1

    def test_missing(self):
        assert parse_units_from_deal_description('No unit count here') is None
        assert parse_units_from_deal_description(None) is None


class TestResolveFills:
    def test_units_fill_when_blank(self):
        assert (
            resolve_units_fill_if_blank(
                current_units=None,
                deal_description='Units: 12',
            )
            == 12
        )

    def test_units_does_not_overwrite(self):
        assert (
            resolve_units_fill_if_blank(
                current_units=8,
                deal_description='Units: 12',
            )
            is None
        )

    def test_category_costar_upgrades_residential_default(self):
        assert (
            resolve_commercial_category_fill_if_blank(
                current_category='residential',
                deal_source='CoStar',
            )
            == 'commercial'
        )

    def test_category_noop_when_already_commercial(self):
        assert (
            resolve_commercial_category_fill_if_blank(
                current_category='commercial',
                deal_source='CoStar',
            )
            is None
        )

    def test_category_noop_for_listsource(self):
        assert (
            resolve_commercial_category_fill_if_blank(
                current_category='residential',
                deal_source='Listsource',
            )
            is None
        )


class TestApplyImportSignalFills:
    def test_costar_lead_10265_shape(self):
        lead = SimpleNamespace(
            deal_source='CoStar',
            deal_description='Costar  Date ID: 3/7/2022 Not Yet Skip Traced Units: 12',
            units=None,
            lead_category='residential',
            property_type=None,
        )
        updated = apply_import_signal_fills(lead)
        assert set(updated) == {'units', 'lead_category', 'property_type'}
        assert lead.units == 12
        assert lead.lead_category == 'commercial'
        assert lead.property_type == 'Commercial'

    def test_does_not_clobber_gis_units_or_category(self):
        lead = SimpleNamespace(
            deal_source='CoStar',
            deal_description='Units: 12',
            units=6,
            lead_category='commercial',
            property_type='Multi-Family',
        )
        assert apply_import_signal_fills(lead) == []
        assert lead.units == 6
        assert lead.property_type == 'Multi-Family'

    def test_locked_category_is_not_upgraded_from_costar(self):
        lead = SimpleNamespace(
            deal_source='CoStar',
            deal_description='Units: 12',
            units=2,
            lead_category='residential',
            lead_category_locked=True,
            property_type=None,
        )
        updated = apply_import_signal_fills(lead)
        assert 'lead_category' not in updated
        assert 'property_type' not in updated
        assert lead.lead_category == 'residential'
        assert lead.property_type is None

    def test_locked_commercial_category_gets_blank_display_label(self):
        lead = SimpleNamespace(
            deal_source='Listsource',
            deal_description='Units: 12',
            units=12,
            lead_category='commercial',
            lead_category_locked=True,
            property_type=None,
        )
        updated = apply_import_signal_fills(lead)
        assert updated == ['property_type']
        assert lead.lead_category == 'commercial'
        assert lead.property_type == 'Commercial'
