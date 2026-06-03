"""Unit tests for DuPageGISConnector — Task 4.3.

Covers:
- Successful lookup_by_address: verifies all GISParcel fields are mapped correctly
- Successful lookup_by_pin: verifies PIN-based WHERE clause and field mapping
- Empty features list returns None (both methods)
- requests.Timeout is propagated, not swallowed (both methods)
- connector_name == "dupage_gis" and market == "dupage_il"
- TIMEOUT_SECONDS == 10

Requirements: 8.1, 8.6
"""

import pytest
import requests
from unittest.mock import patch, MagicMock

from app.services.gis.dupage_gis_connector import DuPageGISConnector
from app.services.gis.base import GISParcel


# ---------------------------------------------------------------------------
# Sample API response data
# ---------------------------------------------------------------------------

_SAMPLE_ATTRIBUTES = {
    "PIN": "0912101018",
    "PROPNAME": "DOE, JANE",
    "PROPADDRL1": "123 MAIN ST",
    "PROPADDRL2": "WHEATON IL 60187",
    "BILLADDRL1": "123 Main St",
    "BILLADDRL2": "Wheaton IL 60187",
    "REA017_PROP_CLASS": "Single Family Residence",
}

_SAMPLE_RESPONSE = {
    "features": [
        {"attributes": _SAMPLE_ATTRIBUTES}
    ]
}

_EMPTY_RESPONSE = {
    "features": []
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# Connector metadata
# ---------------------------------------------------------------------------

class TestConnectorMetadata:
    """Connector-level constants and property values."""

    def test_connector_name(self):
        connector = DuPageGISConnector()
        assert connector.connector_name == "dupage_gis"

    def test_market(self):
        connector = DuPageGISConnector()
        assert connector.market == "dupage_il"

    def test_timeout_seconds(self):
        assert DuPageGISConnector.TIMEOUT_SECONDS == 10


# ---------------------------------------------------------------------------
# lookup_by_address — success path
# ---------------------------------------------------------------------------

class TestLookupByAddress:
    """Tests for the lookup_by_address method."""

    @patch("requests.get")
    def test_returns_gis_parcel_on_match(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        result = connector.lookup_by_address("123 Main St")
        assert isinstance(result, GISParcel)

    @patch("requests.get")
    def test_all_fields_mapped_correctly(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_address("123 Main St")

        assert parcel.county_assessor_pin == "0912101018"
        assert parcel.property_type == "Single Family Residence"
        assert parcel.year_built is None
        assert parcel.square_footage is None
        assert parcel.bedrooms is None
        assert parcel.bathrooms is None
        assert parcel.lot_size is None
        assert parcel.owner_first_name == "JANE"
        assert parcel.owner_last_name == "DOE"
        assert parcel.mailing_address == "123 Main St"
        assert parcel.mailing_city == "Wheaton"
        assert parcel.mailing_state == "IL"
        assert parcel.mailing_zip == "60187"

    @patch("requests.get")
    def test_where_clause_uses_address(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_address("123 Main St")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        where = params["where"]
        assert "PROPADDRL1" in where
        assert "123 MAIN ST" in where

    @patch("requests.get")
    def test_timeout_passed_to_requests(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_address("123 Main St")

        call_kwargs = mock_get.call_args
        timeout = call_kwargs[1].get("timeout")
        assert timeout == 10

    @patch("requests.get")
    def test_returns_none_when_no_features(self, mock_get):
        mock_get.return_value = _make_mock_response(_EMPTY_RESPONSE)
        connector = DuPageGISConnector()
        result = connector.lookup_by_address("Nonexistent Address")
        assert result is None

    @patch("requests.get")
    def test_timeout_exception_propagated(self, mock_get):
        mock_get.side_effect = requests.Timeout("timed out")
        connector = DuPageGISConnector()
        with pytest.raises(requests.Timeout):
            connector.lookup_by_address("123 Main St")

    @patch("requests.get")
    def test_address_uppercased_in_where_clause(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_address("lower case address")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert "LOWER CASE ADDRESS" in params["where"]

    @patch("requests.get")
    def test_single_quote_in_address_is_escaped(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_address("O'Hare Ave")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        # Single quote must be doubled to prevent SQL injection
        assert "''" in params["where"]

    @patch("requests.get")
    def test_percent_sign_in_address_is_escaped(self, mock_get):
        """Percent signs must be escaped to prevent LIKE wildcard matching."""
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_address("50% Off St")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        # Percent must be backslash-escaped
        assert r"\%" in params["where"]

    @patch("requests.get")
    def test_underscore_in_address_is_escaped(self, mock_get):
        """Underscores must be escaped to prevent LIKE wildcard matching."""
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_address("Main_Street")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        # Underscore must be backslash-escaped
        assert r"\_" in params["where"]

    @patch("requests.get")
    def test_escape_clause_present_in_where(self, mock_get):
        """WHERE clause must include ESCAPE '\\' for backslash escaping to work."""
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_address("any address")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert "ESCAPE" in params["where"]


# ---------------------------------------------------------------------------
# lookup_by_pin — success path
# ---------------------------------------------------------------------------

class TestLookupByPin:
    """Tests for the lookup_by_pin method."""

    @patch("requests.get")
    def test_returns_gis_parcel_on_match(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        result = connector.lookup_by_pin("0912101018")
        assert isinstance(result, GISParcel)

    @patch("requests.get")
    def test_all_fields_mapped_correctly(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_pin("0912101018")

        assert parcel.county_assessor_pin == "0912101018"
        assert parcel.property_type == "Single Family Residence"
        assert parcel.year_built is None
        assert parcel.square_footage is None
        assert parcel.bedrooms is None
        assert parcel.bathrooms is None
        assert parcel.lot_size is None
        assert parcel.owner_first_name == "JANE"
        assert parcel.owner_last_name == "DOE"
        assert parcel.mailing_address == "123 Main St"
        assert parcel.mailing_city == "Wheaton"
        assert parcel.mailing_state == "IL"
        assert parcel.mailing_zip == "60187"

    @patch("requests.get")
    def test_where_clause_uses_pin_column(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_pin("0912101018")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        where = params["where"]
        assert "PIN" in where
        assert "0912101018" in where

    @patch("requests.get")
    def test_pin_where_clause_format(self, mock_get):
        """WHERE clause should be PIN = '<pin>' (equality, not LIKE)."""
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_pin("0912101018")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        where = params["where"]
        # Must be exact equality match, not LIKE
        assert "=" in where
        assert "LIKE" not in where

    @patch("requests.get")
    def test_timeout_passed_to_requests(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_pin("0912101018")

        call_kwargs = mock_get.call_args
        timeout = call_kwargs[1].get("timeout")
        assert timeout == 10

    @patch("requests.get")
    def test_returns_none_when_no_features(self, mock_get):
        mock_get.return_value = _make_mock_response(_EMPTY_RESPONSE)
        connector = DuPageGISConnector()
        result = connector.lookup_by_pin("9999999999")
        assert result is None

    @patch("requests.get")
    def test_timeout_exception_propagated(self, mock_get):
        mock_get.side_effect = requests.Timeout("timed out")
        connector = DuPageGISConnector()
        with pytest.raises(requests.Timeout):
            connector.lookup_by_pin("0912101018")

    @patch("requests.get")
    def test_single_quote_in_pin_is_escaped(self, mock_get):
        mock_get.return_value = _make_mock_response(_SAMPLE_RESPONSE)
        connector = DuPageGISConnector()
        connector.lookup_by_pin("091'2101018")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert "''" in params["where"]


# ---------------------------------------------------------------------------
# Field type coercion
# ---------------------------------------------------------------------------

class TestOwnerNameParsing:
    """Verify PROPNAME parsing into owner_first_name and owner_last_name."""

    @patch("requests.get")
    def test_string_propname_splits_on_comma(self, mock_get):
        """PROPNAME with comma format splits into first/last correctly."""
        attrs = {**_SAMPLE_ATTRIBUTES, "PROPNAME": "SMITH, JOHN A"}
        mock_get.return_value = _make_mock_response({"features": [{"attributes": attrs}]})
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_address("any")
        assert parcel.owner_first_name == "JOHN A"
        assert parcel.owner_last_name == "SMITH"

    @patch("requests.get")
    def test_propname_without_comma(self, mock_get):
        """PROPNAME without comma uses last word as last name."""
        attrs = {**_SAMPLE_ATTRIBUTES, "PROPNAME": "JOHN SMITH"}
        mock_get.return_value = _make_mock_response({"features": [{"attributes": attrs}]})
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_address("any")
        assert parcel.owner_first_name == "JOHN"
        assert parcel.owner_last_name == "SMITH"

    @patch("requests.get")
    def test_none_fields_remain_none(self, mock_get):
        attrs = {k: None for k in _SAMPLE_ATTRIBUTES}
        mock_get.return_value = _make_mock_response({"features": [{"attributes": attrs}]})
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_address("any")
        assert parcel.county_assessor_pin is None
        assert parcel.year_built is None
        assert parcel.bathrooms is None
        assert parcel.owner_first_name is None

    @patch("requests.get")
    def test_blank_string_propname_returns_none_owner(self, mock_get):
        attrs = {**_SAMPLE_ATTRIBUTES, "PROPNAME": "   "}
        mock_get.return_value = _make_mock_response({"features": [{"attributes": attrs}]})
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_address("any")
        assert parcel.owner_first_name is None
        assert parcel.owner_last_name is None

    @patch("requests.get")
    def test_none_propname_returns_none_owner(self, mock_get):
        attrs = {**_SAMPLE_ATTRIBUTES, "PROPNAME": None}
        mock_get.return_value = _make_mock_response({"features": [{"attributes": attrs}]})
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_address("any")
        assert parcel.owner_first_name is None
        assert parcel.owner_last_name is None

    @patch("requests.get")
    def test_first_feature_used_when_multiple_returned(self, mock_get):
        """When multiple features are returned the first one is used."""
        second_attrs = {**_SAMPLE_ATTRIBUTES, "PIN": "9999999999"}
        response = {
            "features": [
                {"attributes": _SAMPLE_ATTRIBUTES},
                {"attributes": second_attrs},
            ]
        }
        mock_get.return_value = _make_mock_response(response)
        connector = DuPageGISConnector()
        parcel = connector.lookup_by_address("123 Main St")
        assert parcel.county_assessor_pin == "0912101018"
