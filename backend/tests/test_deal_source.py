"""Tests for HubSpot-aligned deal_source helpers and CoStar import mapping."""
from app.services.helpers.deal_source import (
    DEAL_SOURCE_OPTIONS,
    normalize_imported_source_to_deal_source,
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

    def test_exact_enum_aliases(self):
        assert normalize_imported_source_to_deal_source('cityscape') == 'Cityscape'
        assert normalize_imported_source_to_deal_source('Driving For Dollars') == 'Driving For Dollars'

    def test_unmapped_returns_none(self):
        assert normalize_imported_source_to_deal_source('random sheet note') is None
        assert normalize_imported_source_to_deal_source('') is None
        assert normalize_imported_source_to_deal_source(None) is None

    def test_costar_in_options(self):
        assert 'CoStar' in DEAL_SOURCE_OPTIONS


class TestFillDealSourceFromImportSource:
    def test_fills_blank_deal_source_from_costar_source(self, app):
        with app.app_context():
            lead = Lead(source='skip as costar', deal_source=None)
            assert _fill_deal_source_from_import_source(lead) is True
            assert lead.deal_source == 'CoStar'

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
