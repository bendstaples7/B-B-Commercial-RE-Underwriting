"""Tests for Cook County / Chicago open-data enrichment plugins."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.data_source_connector import DataSourceConnector
from app.services.plugins.address_utils import is_chicago_address, normalize_chicago_street
from app.services.plugins.chicago_building_violations import ChicagoBuildingViolationsPlugin
from app.services.plugins.chicago_scofflaw import ChicagoScofflawPlugin
from app.services.plugins.cook_county_appeals import CookCountyAppealsPlugin
from app.services.plugins.cook_county_commercial_valuation import (
    CookCountyCommercialValuationPlugin,
)
from app.services.plugins.cook_county_owner_lookup import CookCountyOwnerLookupPlugin
from app.services.plugins.cook_county_scavenger_tax_sale import CookCountyScavengerTaxSalePlugin
from app.services.plugins.cook_county_tax_exempt import CookCountyTaxExemptPlugin
from app.services.plugins.owner_name_utils import apply_owner_name_fields


class TestAddressUtils:
    def test_normalize_chicago_street(self):
        assert normalize_chicago_street("7464 North Sheridan Avenue") == "7464 N SHERIDAN AVE"

    def test_is_chicago_address_by_city(self):
        assert is_chicago_address(city="Chicago") is True
        assert is_chicago_address(city="Evanston") is False


class TestOwnerNameUtils:
    def test_entity_owner(self):
        fields = {}
        apply_owner_name_fields(fields, "BSD JEFFERY, LLC")
        assert fields["ownership_type"] == "entity"
        assert fields["owner_last_name"] == "BSD JEFFERY, LLC"

    def test_individual_owner(self):
        fields = {}
        apply_owner_name_fields(fields, "John Smith")
        assert fields["owner_first_name"] == "John"
        assert fields["owner_last_name"] == "Smith"

    def test_individual_name_not_misclassified_as_entity(self):
        fields = {}
        apply_owner_name_fields(fields, "Vincent Alpha")
        assert fields["ownership_type"] == "individual"
        assert fields["owner_first_name"] == "Vincent"


class TestPluginRegistration:
    def test_all_new_plugins_registered(self):
        connector = DataSourceConnector()
        expected = {
            "cook_county_commercial_valuation",
            "cook_county_appeals",
            "cook_county_tax_exempt",
            "cook_county_scavenger_tax_sale",
            "chicago_building_violations",
            "chicago_scofflaw",
            "cook_county_owner_lookup",
        }
        assert expected.issubset(set(connector._plugins.keys()))


class TestCommercialValuationPlugin:
    @patch("app.services.plugins.cook_county_pin_plugin.socrata_get")
    def test_maps_commercial_fields(self, mock_get):
        mock_get.return_value = [{
            "property_type_use": "Retail-Storefront",
            "bldgsf": "9586.0",
            "finalmarketvalue": "633366.19",
            "yearbuilt": "1975.0",
        }]
        plugin = CookCountyCommercialValuationPlugin()
        result = plugin.lookup_by_pin("01-02-202-045-0000")
        assert result is not None
        assert result.fields["property_type"] == "retail-storefront"
        assert result.fields["square_footage"] == 9586
        assert result.fields["assessed_value"] == pytest.approx(633366.19)
        assert result.fields["year_built"] == 1975


class TestAppealsPlugin:
    @patch("app.services.plugins.cook_county_pin_plugin.socrata_get")
    def test_wraps_appeals_in_tax_distress_data(self, mock_get):
        mock_get.return_value = [{"case_no": "9000140", "change": "change"}]
        result = CookCountyAppealsPlugin().lookup_by_pin("01011000060000")
        assert result.fields["tax_distress_data"]["appeals"] == mock_get.return_value


class TestTaxExemptPlugin:
    @patch("app.services.plugins.cook_county_pin_plugin.socrata_get")
    def test_maps_owner_name(self, mock_get):
        mock_get.return_value = [{
            "owner_name": "BARRINGTON VILLAGE",
            "class": "EX",
        }]
        result = CookCountyTaxExemptPlugin().lookup_by_pin("01011000080000")
        assert result.fields["ownership_type"] == "tax_exempt"
        assert result.fields["owner_last_name"] == "BARRINGTON VILLAGE"


class TestScavengerPlugin:
    @patch("app.services.plugins.cook_county_pin_plugin.socrata_get")
    def test_uses_dashed_pin_query(self, mock_get):
        mock_get.return_value = [{"buyer_name": "TEST BUYER"}]
        CookCountyScavengerTaxSalePlugin().lookup_by_pin("17-21-321-018-0000")
        assert mock_get.call_args.kwargs["params"]["$where"] == "pin='17-21-321-018-0000'"


class TestChicagoPlugins:
    @patch("app.services.plugins.chicago_building_violations.socrata_get")
    def test_violations_require_chicago(self, mock_get):
        mock_get.return_value = [{"violation_code": "CN194029"}]
        lead = SimpleNamespace(
            property_street="7464 N Sheridan Rd",
            property_city="Chicago",
        )
        result = ChicagoBuildingViolationsPlugin().lookup_for_lead(lead)
        assert result is not None
        assert "chicago_building_violations" in result.fields["violation_data"]

    def test_violations_skip_non_chicago(self):
        lead = SimpleNamespace(
            property_street="123 Main St",
            property_city="Evanston",
        )
        assert ChicagoBuildingViolationsPlugin().lookup_for_lead(lead) is None

    @patch("app.services.plugins.chicago_scofflaw.socrata_get")
    def test_scofflaw_maps_defendant_owner(self, mock_get):
        mock_get.return_value = [{"defendant_owner": "BSD JEFFERY, LLC"}]
        lead = SimpleNamespace(
            property_street="7501 S Jeffery Blvd",
            property_city="Chicago",
        )
        result = ChicagoScofflawPlugin().lookup_for_lead(lead)
        assert result.fields["owner_last_name"] == "BSD JEFFERY, LLC"


class TestJsonMerge:
    def test_merge_dict_fields(self):
        merged = DataSourceConnector._merge_json_field(
            {"appeals": [{"case_no": "1"}]},
            {"scavenger_tax_sale": [{"buyer_name": "A"}]},
        )
        assert "appeals" in merged
        assert "scavenger_tax_sale" in merged

    def test_merge_list_with_dict(self):
        merged = DataSourceConnector._merge_json_field(
            [{"tax_sale_year": "2020"}],
            {"appeals": [{"case_no": "1"}]},
        )
        assert merged["records"][0]["tax_sale_year"] == "2020"
        assert merged["appeals"][0]["case_no"] == "1"


class TestOwnerLookupPlugin:
    @patch("app.services.plugins.cook_county_owner_lookup.lookup_owner_fields")
    def test_lookup_for_lead_uses_pin_and_city(self, mock_lookup):
        mock_lookup.return_value = {
            "owner_last_name": "TEST LLC",
            "permit_data": {"owner_lookup_sources": {"clerk_grantee": "TEST LLC"}},
        }
        lead = SimpleNamespace(
            id=1,
            county_assessor_pin="17-21-321-018-0000",
            property_street="123 Main St",
            property_city="Chicago",
        )
        result = CookCountyOwnerLookupPlugin().lookup_for_lead(lead)
        assert result is not None
        mock_lookup.assert_called_once_with(
            pin="17-21-321-018-0000",
            address="123 Main St",
            city="Chicago",
        )
