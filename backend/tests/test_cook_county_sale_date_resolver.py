"""Unit tests for Cook County sale-date resolve order (Tracks 4–5)."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.helpers.cook_county_sale_date_resolver import (
    PROVENANCE_ASSESSOR,
    PROVENANCE_MYDEC,
    PROVENANCE_RELATED,
    resolve_cook_county_sale_date,
    should_write_acquisition_date,
)
from app.services.helpers.illinois_mydec import (
    normalize_mydec_pin,
    parse_instrument_date,
)
from app.services.plugins.cook_county_assessor import CookCountyAssessorPlugin


def test_normalize_mydec_pin_truncates():
    assert normalize_mydec_pin("02-09-114-001-0000", keep_digits=10) == "0209114001"
    assert normalize_mydec_pin("14284000080000") == "14284000080000"


def test_parse_instrument_date():
    assert parse_instrument_date("2019-07-11T00:00:00.000") == date(2019, 7, 11)
    assert parse_instrument_date(None) is None


def test_resolve_prefers_primary_assessor():
    lead = SimpleNamespace(county_assessor_pin="14284000080000", id=1)

    def fetch(pin):
        if pin == "14284000080000":
            return {
                "acquisition_date": date(2020, 1, 15),
                "most_recent_sale_price": 250000.0,
                "sale_doc_no": "2012345678",
            }
        return {}

    with patch(
        "app.services.helpers.cook_county_sale_date_resolver.related_pin_candidates_for_lead",
        return_value=["99999999999999"],
    ):
        result = resolve_cook_county_sale_date(lead, fetch_assessor_sale=fetch)
    assert result is not None
    assert result.provenance == PROVENANCE_ASSESSOR
    assert result.acquisition_date == date(2020, 1, 15)
    assert result.doc_no == "2012345678"


def test_resolve_related_pin_when_primary_empty():
    lead = SimpleNamespace(county_assessor_pin="11111111111111", id=2)

    def fetch(pin):
        if pin == "22222222222222":
            return {
                "acquisition_date": date(2018, 6, 1),
                "most_recent_sale_price": 100000.0,
            }
        return {}

    with patch(
        "app.services.helpers.cook_county_sale_date_resolver.related_pin_candidates_for_lead",
        return_value=["22222222222222"],
    ), patch(
        "app.services.helpers.cook_county_sale_date_resolver.fetch_most_recent_transfer_for_pin",
    ) as mock_mydec:
        result = resolve_cook_county_sale_date(lead, fetch_assessor_sale=fetch)
        mock_mydec.assert_not_called()
    assert result is not None
    assert result.provenance == PROVENANCE_RELATED
    assert result.source_pin == "22222222222222"
    assert result.acquisition_date == date(2018, 6, 1)


def test_resolve_mydec_when_assessor_ladder_empty():
    lead = SimpleNamespace(county_assessor_pin="13262150360000", id=3)

    with patch(
        "app.services.helpers.cook_county_sale_date_resolver.related_pin_candidates_for_lead",
        return_value=[],
    ), patch(
        "app.services.helpers.cook_county_sale_date_resolver.fetch_most_recent_transfer_for_pin",
        return_value={
            "acquisition_date": date(2015, 3, 20),
            "pin": "13262150360000",
        },
    ):
        result = resolve_cook_county_sale_date(
            lead,
            fetch_assessor_sale=lambda _pin: {},
        )
    assert result is not None
    assert result.provenance == PROVENANCE_MYDEC
    assert result.acquisition_date == date(2015, 3, 20)


def test_related_and_mydec_are_fill_if_null_only():
    lead_empty = SimpleNamespace(acquisition_date=None)
    lead_set = SimpleNamespace(acquisition_date=date(2000, 1, 1))
    related = MagicMock(provenance=PROVENANCE_RELATED)
    mydec = MagicMock(provenance=PROVENANCE_MYDEC)
    assessor = MagicMock(provenance=PROVENANCE_ASSESSOR)
    assert should_write_acquisition_date(lead_empty, related) is True
    assert should_write_acquisition_date(lead_set, related) is False
    assert should_write_acquisition_date(lead_set, mydec) is False
    assert should_write_acquisition_date(lead_set, assessor) is True


def test_plugin_lookup_for_lead_uses_resolver(app):
    with app.app_context():
        from app.models.lead import Lead
        from app import db

        lead = Lead(
            property_street="100 Test St",
            property_city="Chicago",
            property_state="IL",
            property_zip="60618",
            county_assessor_pin="13262150360000",
        )
        db.session.add(lead)
        db.session.flush()

        plugin = CookCountyAssessorPlugin()
        with patch.object(plugin, "_fetch_improvement_characteristics", return_value={}), \
             patch.object(plugin, "_fetch_parcel_universe", return_value={"assessed_value": 1.0}), \
             patch(
                 "app.services.plugins.cook_county_assessor.resolve_cook_county_sale_date",
                 return_value=MagicMock(
                     provenance=PROVENANCE_MYDEC,
                     acquisition_date=date(2016, 4, 1),
                     source_pin="13262150360000",
                     sale_price=None,
                     doc_no=None,
                     sale_type=None,
                     to_enrichment_fields=lambda fill_if_null: {
                         "acquisition_date": date(2016, 4, 1),
                         "sale_date_provenance": PROVENANCE_MYDEC,
                         "_sale_fill_if_null": fill_if_null,
                     },
                 ),
             ):
            result = plugin.lookup_for_lead(lead)
        assert result is not None
        assert result.fields["sale_date_provenance"] == PROVENANCE_MYDEC
        assert result.fields["acquisition_date"] == date(2016, 4, 1)


def test_plugin_mydec_fill_if_null_skips_when_acquisition_set(app):
    with app.app_context():
        from app.models.lead import Lead
        from app import db
        from app.services.helpers.cook_county_sale_date_resolver import SaleDateResolution

        lead = Lead(
            property_street="100 Test St",
            property_city="Chicago",
            property_state="IL",
            property_zip="60618",
            county_assessor_pin="13262150360000",
            acquisition_date=date(1993, 8, 27),
        )
        db.session.add(lead)
        db.session.flush()

        plugin = CookCountyAssessorPlugin()
        resolution = SaleDateResolution(
            acquisition_date=date(2016, 4, 1),
            provenance=PROVENANCE_MYDEC,
            source_pin="13262150360000",
        )
        with patch.object(plugin, "_fetch_improvement_characteristics", return_value={}), \
             patch.object(plugin, "_fetch_parcel_universe", return_value={}), \
             patch(
                 "app.services.plugins.cook_county_assessor.resolve_cook_county_sale_date",
                 return_value=resolution,
             ):
            result = plugin.lookup_for_lead(lead)
        assert result is not None
        assert "acquisition_date" not in result.fields
        assert result.fields["sale_date_provenance"] == PROVENANCE_MYDEC
