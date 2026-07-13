"""Tests for HubSpot-aligned deal_source helpers and import mapping."""
from app.services.helpers.deal_source import (
    DEAL_SOURCE_OPTIONS,
    infer_deal_source_from_lead_fields,
    normalize_imported_source_to_deal_source,
    resolve_blank_deal_source,
)
from app.services.google_sheets_importer import _fill_deal_source_from_import_source
from app.models.lead import Lead


class TestNormalizeImportedSourceToDealSource:
    def test_costar_exact(self):
        assert normalize_imported_source_to_deal_source('CoStar') == 'CoStar'

    def test_costar_variants(self):
        assert normalize_imported_source_to_deal_source('skip as costar') == 'CoStar'
        assert normalize_imported_source_to_deal_source('Co-Star') == 'CoStar'
        assert normalize_imported_source_to_deal_source('co star list') == 'CoStar'

    def test_listsource_variants(self):
        assert normalize_imported_source_to_deal_source('Listsource') == 'Listsource'
        assert normalize_imported_source_to_deal_source('List Source') == 'Listsource'
        assert normalize_imported_source_to_deal_source(
            'Listsource Date ID: 3/1/2021 Munawar'
        ) == 'Listsource'

    def test_exact_enum_aliases(self):
        assert normalize_imported_source_to_deal_source('cityscape') == 'Cityscape'
        assert normalize_imported_source_to_deal_source('Driving For Dollars') == 'Driving For Dollars'

    def test_unmapped_returns_none(self):
        assert normalize_imported_source_to_deal_source('random sheet note') is None
        assert normalize_imported_source_to_deal_source('') is None
        assert normalize_imported_source_to_deal_source(None) is None

    def test_options_include_listsource_and_costar(self):
        assert 'CoStar' in DEAL_SOURCE_OPTIONS
        assert 'Listsource' in DEAL_SOURCE_OPTIONS


class TestResolveBlankDealSourceEqualPriority:
    def test_sheet_source_fills_when_hubspot_blank(self):
        assert (
            resolve_blank_deal_source(
                hubspot_deal_source=None,
                sheet_source='Listsource',
            )
            == 'Listsource'
        )

    def test_hubspot_fills_when_sheet_blank(self):
        assert (
            resolve_blank_deal_source(
                hubspot_deal_source='Cityscape',
                sheet_source='hubspot_import',
            )
            == 'Cityscape'
        )

    def test_does_not_overwrite_current(self):
        assert (
            resolve_blank_deal_source(
                current='CoStar',
                hubspot_deal_source='Cityscape',
                sheet_source='Listsource',
            )
            == 'CoStar'
        )

    def test_description_is_tertiary_when_peers_blank(self):
        assert (
            resolve_blank_deal_source(
                hubspot_deal_source=None,
                sheet_source='hubspot_import',
                deal_description='Listsource Date ID: 3/1/2021',
            )
            == 'Listsource'
        )


class TestInferDealSourceFromLeadFields:
    def test_prefers_sheet_source_over_description(self):
        assert (
            infer_deal_source_from_lead_fields(
                source='Listsource',
                deal_description='Driving For Dollars note',
            )
            == 'Listsource'
        )

    def test_uses_description_when_source_is_hubspot_import(self):
        assert (
            infer_deal_source_from_lead_fields(
                source='hubspot_import',
                deal_description='Listsource Date ID: 3/1/2021 Munawar',
            )
            == 'Listsource'
        )


class TestFillDealSourceFromImportSource:
    def test_fills_blank_deal_source_from_costar_source(self, app):
        with app.app_context():
            lead = Lead(source='skip as costar', deal_source=None)
            assert _fill_deal_source_from_import_source(lead) is True
            assert lead.deal_source == 'CoStar'

    def test_fills_from_listsource_description_when_hubspot_import(self, app):
        with app.app_context():
            lead = Lead(
                source='hubspot_import',
                deal_source=None,
                deal_description='Listsource Date ID: 3/1/2021 Munawar Upwork',
            )
            assert _fill_deal_source_from_import_source(lead) is True
            assert lead.deal_source == 'Listsource'

    def test_does_not_overwrite_existing_deal_source(self, app):
        with app.app_context():
            lead = Lead(source='CoStar', deal_source='Cityscape')
            assert _fill_deal_source_from_import_source(lead) is False
            assert lead.deal_source == 'Cityscape'

    def test_noop_when_source_unmapped(self, app):
        with app.app_context():
            lead = Lead(source='handwritten note', deal_source=None)
            assert _fill_deal_source_from_import_source(lead) is False
            assert lead.deal_source is None
