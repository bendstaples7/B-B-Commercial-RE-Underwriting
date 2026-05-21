"""Unit tests for ComparableSalesFinder service."""
import pytest
from datetime import datetime, timedelta
from app.services.comparable_sales_finder import (
    ComparableSalesFinder,
    _map_mls_property_type,
    _map_mls_construction_type,
    _map_mls_interior_condition,
)
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition


class TestComparableSalesFinder:
    """Test suite for ComparableSalesFinder."""
    
    def test_radius_expansion_sequence(self):
        """Test that radius expansion follows correct sequence."""
        finder = ComparableSalesFinder()
        
        # Test expansion from each radius
        assert finder.expand_search_radius(0.25) == 0.5
        assert finder.expand_search_radius(0.5) == 0.75
        assert finder.expand_search_radius(0.75) == 1.0
        assert finder.expand_search_radius(1.0) is None
    
    def test_radius_expansion_from_non_standard_radius(self):
        """Test radius expansion from non-standard starting point."""
        finder = ComparableSalesFinder()
        
        # Should return next larger radius in sequence
        assert finder.expand_search_radius(0.3) == 0.5
        assert finder.expand_search_radius(0.6) == 0.75
        assert finder.expand_search_radius(0.9) == 1.0
        assert finder.expand_search_radius(1.5) is None
    
    def test_property_type_filtering(self):
        """Test filtering sales by property type."""
        finder = ComparableSalesFinder()
        
        sales = [
            {'address': '123 Main St', 'property_type': 'single_family'},
            {'address': '456 Oak Ave', 'property_type': 'multi_family'},
            {'address': '789 Elm St', 'property_type': 'single_family'},
            {'address': '321 Pine Rd', 'property_type': 'commercial'},
        ]
        
        # Filter for single family
        filtered = finder.filter_by_property_type(sales, PropertyType.SINGLE_FAMILY)
        assert len(filtered) == 2
        assert all(s['property_type'] == 'single_family' for s in filtered)
        
        # Filter for multi family
        filtered = finder.filter_by_property_type(sales, PropertyType.MULTI_FAMILY)
        assert len(filtered) == 1
        assert filtered[0]['address'] == '456 Oak Ave'
        
        # Filter for commercial
        filtered = finder.filter_by_property_type(sales, PropertyType.COMMERCIAL)
        assert len(filtered) == 1
        assert filtered[0]['address'] == '321 Pine Rd'
    
    def test_sale_date_filtering(self):
        """Test filtering sales by date."""
        finder = ComparableSalesFinder()
        
        now = datetime.now()
        cutoff = now - timedelta(days=365)
        
        sales = [
            {'address': '123 Main St', 'sale_date': (now - timedelta(days=30)).strftime('%Y-%m-%d')},
            {'address': '456 Oak Ave', 'sale_date': (now - timedelta(days=180)).strftime('%Y-%m-%d')},
            {'address': '789 Elm St', 'sale_date': (now - timedelta(days=400)).strftime('%Y-%m-%d')},
            {'address': '321 Pine Rd', 'sale_date': (now - timedelta(days=90)).strftime('%Y-%m-%d')},
        ]
        
        filtered = finder._filter_by_sale_date(sales, cutoff)
        
        # Should only include sales within last 365 days
        assert len(filtered) == 3
        assert '789 Elm St' not in [s['address'] for s in filtered]
    
    def test_distance_calculation(self):
        """Test Haversine distance calculation."""
        finder = ComparableSalesFinder()
        
        # Chicago coordinates
        chicago_loop = (41.8781, -87.6298)
        chicago_north = (41.9742, -87.6589)
        
        # Calculate distance
        distance = finder._calculate_distance(chicago_loop, chicago_north)
        
        # Distance should be approximately 6.7 miles
        assert 6.0 < distance < 7.5
    
    def test_distance_calculation_same_point(self):
        """Test distance calculation for same point."""
        finder = ComparableSalesFinder()
        
        point = (41.8781, -87.6298)
        distance = finder._calculate_distance(point, point)
        
        # Distance should be 0
        assert distance < 0.001
    
    def test_find_comparables_requires_coordinates(self):
        """Test that find_comparables requires geocoded subject property."""
        finder = ComparableSalesFinder()
        
        # Create subject without coordinates
        subject = PropertyFacts()
        subject.address = "123 Main St"
        subject.property_type = PropertyType.SINGLE_FAMILY
        subject.latitude = None
        subject.longitude = None
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="must have geocoded coordinates"):
            finder.find_comparables(subject)
    
    def test_property_type_mapping(self):
        """Test mapping of external property types to internal enum."""
        # Test single family variations
        assert _map_mls_property_type('single family') == PropertyType.SINGLE_FAMILY.value
        assert _map_mls_property_type('single-family') == PropertyType.SINGLE_FAMILY.value
        assert _map_mls_property_type('sfr') == PropertyType.SINGLE_FAMILY.value
        
        # Test multi family variations
        assert _map_mls_property_type('multi family') == PropertyType.MULTI_FAMILY.value
        assert _map_mls_property_type('multi-family') == PropertyType.MULTI_FAMILY.value
        assert _map_mls_property_type('multifamily') == PropertyType.MULTI_FAMILY.value
        
        # Test commercial variations
        assert _map_mls_property_type('commercial') == PropertyType.COMMERCIAL.value
        assert _map_mls_property_type('retail') == PropertyType.COMMERCIAL.value
        assert _map_mls_property_type('office') == PropertyType.COMMERCIAL.value
        
        # Test None
        assert _map_mls_property_type(None) is None
    
    def test_construction_type_mapping(self):
        """Test mapping of external construction types to internal enum."""
        # Test frame variations
        assert _map_mls_construction_type('frame') == ConstructionType.FRAME.value
        assert _map_mls_construction_type('wood') == ConstructionType.FRAME.value
        assert _map_mls_construction_type('wood frame') == ConstructionType.FRAME.value
        
        # Test brick variations
        assert _map_mls_construction_type('brick') == ConstructionType.BRICK.value
        assert _map_mls_construction_type('brick veneer') == ConstructionType.BRICK.value
        
        # Test masonry variations
        assert _map_mls_construction_type('masonry') == ConstructionType.MASONRY.value
        assert _map_mls_construction_type('concrete') == ConstructionType.MASONRY.value
        assert _map_mls_construction_type('stone') == ConstructionType.MASONRY.value
        
        # Test None (should return default)
        assert _map_mls_construction_type(None) == ConstructionType.FRAME.value
    
    def test_interior_condition_mapping(self):
        """Test mapping of external interior conditions to internal enum."""
        # Test needs gut
        assert _map_mls_interior_condition('needs gut') == InteriorCondition.NEEDS_GUT.value
        assert _map_mls_interior_condition('needs_gut') == InteriorCondition.NEEDS_GUT.value
        
        # Test poor/fair
        assert _map_mls_interior_condition('poor') == InteriorCondition.POOR.value
        assert _map_mls_interior_condition('fair') == InteriorCondition.POOR.value
        
        # Test average/good
        assert _map_mls_interior_condition('average') == InteriorCondition.AVERAGE.value
        assert _map_mls_interior_condition('good') == InteriorCondition.AVERAGE.value
        
        # Test new renovation
        assert _map_mls_interior_condition('new renovation') == InteriorCondition.NEW_RENO.value
        assert _map_mls_interior_condition('renovated') == InteriorCondition.NEW_RENO.value
        
        # Test high end
        assert _map_mls_interior_condition('high end') == InteriorCondition.HIGH_END.value
        assert _map_mls_interior_condition('luxury') == InteriorCondition.HIGH_END.value
        
        # Test None (should return default)
        assert _map_mls_interior_condition(None) == InteriorCondition.AVERAGE.value


# ---------------------------------------------------------------------------
# Tests for CookCountySalesDataSource
# ---------------------------------------------------------------------------
import urllib.parse
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from app.services.comparable_sales_finder import (
    CookCountySalesDataSource,
    ComparableSalesFinder,
)
from app.models.property_facts import PropertyType, ConstructionType


class TestCookCountySalesDataSource:
    """Tests for CookCountySalesDataSource — field mapping, date filtering,
    property type filtering, and the no-coordinates guard."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_subject(
        self,
        lat=41.8781,
        lon=-87.6298,
        property_type=PropertyType.SINGLE_FAMILY,
    ):
        subject = PropertyFacts()
        subject.address = "123 Main St, Chicago, IL 60601"
        subject.property_type = property_type
        subject.latitude = lat
        subject.longitude = lon
        return subject

    def _bbox_row(self, pin, lat, lon):
        return {"pin": pin, "lat": str(lat), "lon": str(lon)}

    def _sale_row(self, pin, sale_date, sale_price, prop_class="202"):
        return {
            "pin": pin,
            "sale_date": sale_date,
            "sale_price": str(sale_price),
            "class": prop_class,
        }

    def _chars_row(
        self,
        pin,
        bldg_sf="1500",
        beds="3",
        fbath="2",
        hbath="1",
        age="30",
        ext_wall="3",
        apts="1",
    ):
        return {
            "pin": pin,
            "bldg_sf": bldg_sf,
            "beds": beds,
            "fbath": fbath,
            "hbath": hbath,
            "age": age,
            "ext_wall": ext_wall,
            "apts": apts,
        }

    # ------------------------------------------------------------------
    # Field mapping tests
    # ------------------------------------------------------------------

    def test_fetch_comparables_maps_fields_correctly(self):
        """All three Socrata calls are mocked; verify the returned comparable
        dict has the expected field values."""
        pin = "14083010190000"
        sale_date_iso = "2024-03-15T00:00:00.000"
        source = CookCountySalesDataSource()
        subject = self._make_subject()

        bbox_rows = [self._bbox_row(pin, 41.8781, -87.6298)]
        sale_rows = [self._sale_row(pin, sale_date_iso, 350000, "202")]
        chars_rows = [self._chars_row(pin, bldg_sf="1500", beds="3", fbath="2", hbath="1", age="30", ext_wall="3")]

        call_count = [0]

        def fake_socrata_get(url):
            call_count[0] += 1
            if "pabr-t5kh" in url:
                return bbox_rows
            elif "wvhk-k5uv" in url:
                return sale_rows
            elif "bcnq-qi2z" in url:
                return chars_rows
            return []

        with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
            results = source.fetch_comparables(
                subject_facts=subject,
                max_age_months=12,
                max_distance_miles=1.0,
                max_count=10,
            )

        assert len(results) == 1
        comp = results[0]

        assert comp["sale_price"] == 350000.0
        assert comp["sale_date"] == "2024-03-15"
        assert comp["property_type"] == PropertyType.SINGLE_FAMILY.value
        assert comp["square_footage"] == 1500
        assert comp["bedrooms"] == 3
        assert comp["bathrooms"] == 2.5          # 2 full + 0.5 * 1 half
        assert comp["year_built"] == datetime.now().year - 30
        assert comp["construction_type"] == ConstructionType.BRICK.value  # ext_wall=3
        assert comp["latitude"] == 41.8781
        assert comp["longitude"] == -87.6298
        assert comp["pin"] == pin

    def test_parse_improvement_chars_full_bath_and_half_bath(self):
        """bathrooms = full + 0.5 * half (2 full + 1 half = 2.5)."""
        source = CookCountySalesDataSource()
        row = {"fbath": "2", "hbath": "1"}
        result = source._parse_improvement_chars(row)
        assert result["bathrooms"] == 2.5

    def test_parse_improvement_chars_only_full_baths(self):
        """bathrooms = full baths when no half baths present."""
        source = CookCountySalesDataSource()
        row = {"fbath": "3", "hbath": "0"}
        result = source._parse_improvement_chars(row)
        assert result["bathrooms"] == 3.0

    def test_parse_improvement_chars_year_built_from_age(self):
        """year_built = current_year - age."""
        source = CookCountySalesDataSource()
        age = 25
        row = {"age": str(age)}
        result = source._parse_improvement_chars(row)
        assert result["year_built"] == datetime.now().year - age

    def test_parse_improvement_chars_construction_type_mapping(self):
        """ext_wall codes 1/2 → frame, 3/4 → brick, 5/6/7 → masonry."""
        source = CookCountySalesDataSource()

        for code in (1, 2):
            row = {"ext_wall": str(code)}
            result = source._parse_improvement_chars(row)
            assert result["construction_type"] == ConstructionType.FRAME.value, \
                f"ext_wall={code} should map to FRAME"

        for code in (3, 4):
            row = {"ext_wall": str(code)}
            result = source._parse_improvement_chars(row)
            assert result["construction_type"] == ConstructionType.BRICK.value, \
                f"ext_wall={code} should map to BRICK"

        for code in (5, 6, 7):
            row = {"ext_wall": str(code)}
            result = source._parse_improvement_chars(row)
            assert result["construction_type"] == ConstructionType.MASONRY.value, \
                f"ext_wall={code} should map to MASONRY"

    def test_map_to_comparable_sale_date_parsing(self):
        """ISO date '2024-03-15T00:00:00.000' → '2024-03-15'."""
        source = CookCountySalesDataSource()
        sale = {
            "pin": "12345",
            "sale_date": "2024-03-15T00:00:00.000",
            "sale_price": "300000",
            "class": "202",
        }
        comp = source._map_to_comparable(sale, {}, 41.8781, -87.6298)
        assert comp["sale_date"] == "2024-03-15"

    # ------------------------------------------------------------------
    # Date filtering tests
    # ------------------------------------------------------------------

    def test_fetch_sales_for_pins_where_clause_contains_date_filter(self):
        """The $where clause sent to Socrata must contain 'sale_date >='."""
        source = CookCountySalesDataSource()
        captured_urls = []

        def fake_socrata_get(url):
            captured_urls.append(url)
            return []

        cutoff = datetime(2023, 1, 1)
        with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
            source._fetch_sales_for_pins(
                pins=["14083010190000"],
                cutoff_date=cutoff,
                target_classes=["202"],
            )

        assert len(captured_urls) == 1
        # The URL is percent-encoded; check the decoded version
        decoded = urllib.parse.unquote(captured_urls[0])
        assert "sale_date >=" in decoded

    def test_fetch_comparables_excludes_old_sales(self):
        """The $where clause includes the correct cutoff date derived from
        max_age_months so old sales are excluded server-side."""
        source = CookCountySalesDataSource()
        subject = self._make_subject()
        captured_urls = []

        def fake_socrata_get(url):
            captured_urls.append(url)
            if "pabr-t5kh" in url:
                return [self._bbox_row("14083010190000", 41.8781, -87.6298)]
            return []

        with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
            source.fetch_comparables(
                subject_facts=subject,
                max_age_months=12,
                max_distance_miles=1.0,
                max_count=10,
            )

        # Find the sales URL call
        sales_urls = [u for u in captured_urls if "wvhk-k5uv" in u]
        assert len(sales_urls) == 1
        decoded = urllib.parse.unquote(sales_urls[0])
        assert "sale_date >=" in decoded

        # Verify the cutoff year is correct (within last 12 months)
        expected_year = str((datetime.now() - timedelta(days=12 * 30)).year)
        assert expected_year in decoded

    # ------------------------------------------------------------------
    # Property type filtering tests
    # ------------------------------------------------------------------

    def test_classes_for_single_family(self):
        """_classes_for_property_type(SINGLE_FAMILY) returns ['202']."""
        result = CookCountySalesDataSource._classes_for_property_type(
            PropertyType.SINGLE_FAMILY
        )
        assert result == ["202"]

    def test_classes_for_multi_family(self):
        """_classes_for_property_type(MULTI_FAMILY) returns the multi-family codes."""
        result = CookCountySalesDataSource._classes_for_property_type(
            PropertyType.MULTI_FAMILY
        )
        expected = sorted({"203", "204", "205", "206", "207", "208", "211", "212"})
        assert result == expected

    def test_fetch_comparables_filters_by_property_type(self):
        """Only sales matching the subject's property type are returned."""
        source = CookCountySalesDataSource()
        # Subject is SINGLE_FAMILY → only class '202' should be queried
        subject = self._make_subject(property_type=PropertyType.SINGLE_FAMILY)

        captured_urls = []

        def fake_socrata_get(url):
            captured_urls.append(url)
            if "pabr-t5kh" in url:
                return [self._bbox_row("11111111111111", 41.8781, -87.6298)]
            if "wvhk-k5uv" in url:
                # Return one single-family sale and one multi-family sale
                return [
                    self._sale_row("11111111111111", "2024-01-01T00:00:00.000", 300000, "202"),
                    self._sale_row("22222222222222", "2024-01-01T00:00:00.000", 400000, "203"),
                ]
            if "bcnq-qi2z" in url:
                return [self._chars_row("11111111111111")]
            return []

        with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
            results = source.fetch_comparables(
                subject_facts=subject,
                max_age_months=12,
                max_distance_miles=1.0,
                max_count=10,
            )

        # The sales query $where clause should only include class '202'
        sales_urls = [u for u in captured_urls if "wvhk-k5uv" in u]
        assert len(sales_urls) == 1
        decoded = urllib.parse.unquote(sales_urls[0])
        assert "'202'" in decoded
        # Multi-family classes should NOT be in the query
        assert "'203'" not in decoded

    # ------------------------------------------------------------------
    # No-coordinates guard test
    # ------------------------------------------------------------------

    def test_fetch_comparables_returns_empty_when_no_coordinates(self):
        """fetch_comparables returns [] when subject_facts.latitude is None."""
        source = CookCountySalesDataSource()
        subject = self._make_subject(lat=None, lon=None)

        with patch.object(source, "_socrata_get") as mock_get:
            result = source.fetch_comparables(
                subject_facts=subject,
                max_age_months=12,
                max_distance_miles=1.0,
                max_count=10,
            )

        assert result == []
        mock_get.assert_not_called()

    # ------------------------------------------------------------------
    # Integration test
    # ------------------------------------------------------------------

    def test_find_comparables_uses_cook_county_source(self):
        """ComparableSalesFinder.find_comparables returns comparables with
        distance_miles populated when CookCountySalesDataSource returns data."""
        pin = "14083010190000"
        subject = self._make_subject(
            lat=41.8781,
            lon=-87.6298,
            property_type=PropertyType.SINGLE_FAMILY,
        )

        # Use a sale date within the last 12 months so it passes the date filter
        recent_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000")

        bbox_rows = [self._bbox_row(pin, 41.8781, -87.6298)]
        sale_rows = [self._sale_row(pin, recent_date, 320000, "202")]
        chars_rows = [self._chars_row(pin)]

        def fake_socrata_get(url):
            if "pabr-t5kh" in url:
                return bbox_rows
            elif "wvhk-k5uv" in url:
                return sale_rows
            elif "bcnq-qi2z" in url:
                return chars_rows
            return []

        with patch.object(
            CookCountySalesDataSource, "_socrata_get", side_effect=fake_socrata_get
        ):
            finder = ComparableSalesFinder()
            results = finder.find_comparables(subject, min_count=1)

        assert len(results) >= 1
        comp = results[0]
        assert "distance_miles" in comp
        assert comp["distance_miles"] >= 0.0
        assert comp["pin"] == pin
        assert comp["sale_price"] == 320000.0


# ---------------------------------------------------------------------------
# Cache-routing tests for CookCountySalesDataSource
# ---------------------------------------------------------------------------
import logging
from datetime import date
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache


class TestCookCountySalesCacheRouting:
    """Tests for cache-first routing, fallback routing, output schema
    consistency, and parameterised query style in CookCountySalesDataSource.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7
    """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    _PIN = "14083010190000"
    _CENTER_LAT = 41.8781
    _CENTER_LON = -87.6298

    def _make_subject(self, property_type=PropertyType.SINGLE_FAMILY):
        subject = PropertyFacts()
        subject.address = "123 Main St, Chicago, IL 60601"
        subject.property_type = property_type
        subject.latitude = self._CENTER_LAT
        subject.longitude = self._CENTER_LON
        return subject

    def _populate_universe_cache(self, db_session, pin=None, lat=None, lon=None):
        """Insert one row into parcel_universe_cache."""
        pin = pin or self._PIN
        lat = lat if lat is not None else self._CENTER_LAT
        lon = lon if lon is not None else self._CENTER_LON
        row = ParcelUniverseCache(pin=pin, lat=lat, lon=lon)
        db_session.add(row)
        db_session.commit()

    def _populate_sales_cache(self, db_session, pin=None):
        """Insert one qualifying sale row into parcel_sales_cache."""
        pin = pin or self._PIN
        # Use a sale date within the last 12 months so it passes the date filter
        from datetime import date, timedelta
        recent_date = (datetime.now() - timedelta(days=30)).date()
        row = ParcelSalesCache(
            pin=pin,
            sale_date=recent_date,
            sale_price=350000,
            class_="202",
            sale_type="LAND AND BUILDING",
            is_multisale=False,
            sale_filter_less_than_10k=False,
            sale_filter_deed_type=False,
        )
        db_session.add(row)
        db_session.commit()

    def _populate_improvement_cache(self, db_session, pin=None):
        """Insert one row into improvement_characteristics_cache."""
        pin = pin or self._PIN
        row = ImprovementCharacteristicsCache(
            pin=pin,
            bldg_sf=1500,
            beds=3,
            fbath=2,
            hbath=1,
            age=30,
            ext_wall=3,
            apts=1,
        )
        db_session.add(row)
        db_session.commit()

    def _populate_all_caches(self, db_session):
        """Populate all three cache tables with one row each."""
        self._populate_universe_cache(db_session)
        self._populate_sales_cache(db_session)
        self._populate_improvement_cache(db_session)

    # ------------------------------------------------------------------
    # 1. Cache-first routing: non-empty cache → zero HTTP calls
    # ------------------------------------------------------------------

    def test_cache_first_routing_no_http_calls(self, app, db_session):
        """When all three cache tables are non-empty, fetch_comparables must
        make zero calls to _socrata_get.

        Validates: Requirements 4.1, 4.2, 4.3
        """
        # db_session fixture already has an active app context — do not nest another one
        self._populate_all_caches(db_session)

        source = CookCountySalesDataSource()
        subject = self._make_subject()

        with patch.object(source, "_socrata_get") as mock_get:
            source.fetch_comparables(
                subject_facts=subject,
                max_age_months=24,
                max_distance_miles=1.0,
                max_count=10,
            )

        mock_get.assert_not_called()

    # ------------------------------------------------------------------
    # 2. Fallback routing: empty cache → HTTP calls made, warning logged
    # ------------------------------------------------------------------

    def test_fallback_routing_http_calls_made_when_cache_empty(self, app, db_session, caplog):
        """When all three cache tables are empty, fetch_comparables must fall
        back to the live Socrata API (_socrata_get is called) and log a
        warning for each empty table.

        Validates: Requirements 4.4
        """
        # Leave all cache tables empty — no rows inserted
        source = CookCountySalesDataSource()
        subject = self._make_subject()

        call_count = [0]

        def fake_socrata_get(url):
            call_count[0] += 1
            if "pabr-t5kh" in url:
                return [{"pin": self._PIN, "lat": str(self._CENTER_LAT), "lon": str(self._CENTER_LON)}]
            return []

        with caplog.at_level(logging.WARNING, logger="app.services.comparable_sales_finder"):
            with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
                source.fetch_comparables(
                    subject_facts=subject,
                    max_age_months=24,
                    max_distance_miles=1.0,
                    max_count=10,
                )

        # At least one HTTP call must have been made (bounding-box lookup)
        assert call_count[0] >= 1, "Expected _socrata_get to be called at least once"

        # A warning must have been logged for the empty parcel_universe_cache
        warning_text = caplog.text
        assert "parcel_universe_cache" in warning_text or "falling back" in warning_text.lower(), (
            f"Expected a fallback warning in logs, got: {warning_text!r}"
        )

    def test_fallback_routing_warns_for_each_empty_table(self, app, db_session, caplog):
        """When all three cache tables are empty, a warning is logged for
        each empty table that triggers a fallback.

        Validates: Requirements 4.4
        """
        source = CookCountySalesDataSource()
        subject = self._make_subject()

        def fake_socrata_get(url):
            if "pabr-t5kh" in url:
                return [{"pin": self._PIN, "lat": str(self._CENTER_LAT), "lon": str(self._CENTER_LON)}]
            if "wvhk-k5uv" in url:
                return [{"pin": self._PIN, "sale_date": "2024-03-15T00:00:00.000",
                         "sale_price": "350000", "class": "202"}]
            if "bcnq-qi2z" in url:
                return [{"pin": self._PIN, "bldg_sf": "1500", "beds": "3",
                         "fbath": "2", "hbath": "1", "age": "30", "ext_wall": "3", "apts": "1"}]
            return []

        with caplog.at_level(logging.WARNING, logger="app.services.comparable_sales_finder"):
            with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
                source.fetch_comparables(
                    subject_facts=subject,
                    max_age_months=24,
                    max_distance_miles=1.0,
                    max_count=10,
                )

        # All three fallback warnings should appear
        warning_text = caplog.text
        assert "parcel_universe_cache" in warning_text
        assert "parcel_sales_cache" in warning_text
        assert "improvement_characteristics_cache" in warning_text

    # ------------------------------------------------------------------
    # 3. Output schema consistency: same keys from cache path and API path
    # ------------------------------------------------------------------

    def test_output_schema_consistency_cache_path(self, app, db_session):
        """fetch_comparables via the cache path returns dicts with exactly
        the 16 required keys.

        Validates: Requirements 4.7
        """
        # db_session fixture already has an active app context — do not nest another one
        self._populate_all_caches(db_session)

        source = CookCountySalesDataSource()
        subject = self._make_subject()

        with patch.object(source, "_socrata_get") as mock_get:
            results = source.fetch_comparables(
                subject_facts=subject,
                max_age_months=24,
                max_distance_miles=1.0,
                max_count=10,
            )

        mock_get.assert_not_called()

        assert len(results) >= 1, "Expected at least one comparable from cache"
        for comp in results:
            assert set(comp.keys()) == set(CookCountySalesDataSource._REQUIRED_OUTPUT_KEYS), (
                f"Cache path returned unexpected keys: {set(comp.keys()) ^ set(CookCountySalesDataSource._REQUIRED_OUTPUT_KEYS)}"
            )

    def test_output_schema_consistency_api_fallback_path(self, app, db_session):
        """fetch_comparables via the API fallback path returns dicts with
        exactly the same 16 required keys as the cache path.

        Validates: Requirements 4.7
        """
        # Leave caches empty to force API fallback
        source = CookCountySalesDataSource()
        subject = self._make_subject()

        def fake_socrata_get(url):
            if "pabr-t5kh" in url:
                return [{"pin": self._PIN, "lat": str(self._CENTER_LAT), "lon": str(self._CENTER_LON)}]
            if "wvhk-k5uv" in url:
                return [{"pin": self._PIN, "sale_date": "2024-03-15T00:00:00.000",
                         "sale_price": "350000", "class": "202"}]
            if "bcnq-qi2z" in url:
                return [{"pin": self._PIN, "bldg_sf": "1500", "beds": "3",
                         "fbath": "2", "hbath": "1", "age": "30", "ext_wall": "3", "apts": "1"}]
            return []

        with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
            results = source.fetch_comparables(
                subject_facts=subject,
                max_age_months=24,
                max_distance_miles=1.0,
                max_count=10,
            )

        assert len(results) >= 1, "Expected at least one comparable from API fallback"
        for comp in results:
            assert set(comp.keys()) == set(CookCountySalesDataSource._REQUIRED_OUTPUT_KEYS), (
                f"API path returned unexpected keys: {set(comp.keys()) ^ set(CookCountySalesDataSource._REQUIRED_OUTPUT_KEYS)}"
            )

    def test_output_schema_same_keys_cache_and_api(self, app, db_session):
        """The set of keys returned from the cache path and the API fallback
        path must be identical.

        Validates: Requirements 4.7
        """
        # db_session fixture already has an active app context — do not nest another one

        # --- Cache path ---
        self._populate_all_caches(db_session)
        source_cache = CookCountySalesDataSource()
        subject = self._make_subject()

        with patch.object(source_cache, "_socrata_get"):
            cache_results = source_cache.fetch_comparables(
                subject_facts=subject,
                max_age_months=24,
                max_distance_miles=1.0,
                max_count=10,
            )

        # --- API fallback path (force cache to appear empty) ---
        source_api = CookCountySalesDataSource()

        def fake_socrata_get(url):
            if "pabr-t5kh" in url:
                return [{"pin": self._PIN, "lat": str(self._CENTER_LAT), "lon": str(self._CENTER_LON)}]
            if "wvhk-k5uv" in url:
                return [{"pin": self._PIN, "sale_date": "2024-03-15T00:00:00.000",
                         "sale_price": "350000", "class": "202"}]
            if "bcnq-qi2z" in url:
                return [{"pin": self._PIN, "bldg_sf": "1500", "beds": "3",
                         "fbath": "2", "hbath": "1", "age": "30", "ext_wall": "3", "apts": "1"}]
            return []

        # Force cache to appear empty for the API path test
        with patch.object(source_api, "_cache_has_rows", return_value=False):
            with patch.object(source_api, "_socrata_get", side_effect=fake_socrata_get):
                api_results = source_api.fetch_comparables(
                    subject_facts=subject,
                    max_age_months=24,
                    max_distance_miles=1.0,
                    max_count=10,
                )

        assert len(cache_results) >= 1
        assert len(api_results) >= 1

        cache_keys = set(cache_results[0].keys())
        api_keys = set(api_results[0].keys())
        assert cache_keys == api_keys, (
            f"Key mismatch between cache and API paths.\n"
            f"  Cache-only keys: {cache_keys - api_keys}\n"
            f"  API-only keys:   {api_keys - cache_keys}"
        )

    # ------------------------------------------------------------------
    # 4. Expanding bindparam (no batch loop) when cache is active
    # ------------------------------------------------------------------

    def test_sales_cache_uses_single_query_no_batch_loop(self, app, db_session):
        """When parcel_sales_cache is non-empty, _fetch_sales_for_pins must
        execute a single parameterised query using an expanding bindparam
        (IN :pins) rather than batching PINs in a loop.

        This is verified by calling _fetch_sales_for_pins with more than
        _PIN_BATCH_SIZE PINs and confirming only one DB round-trip is needed
        (i.e., _socrata_get is never called and the method returns without
        error for a large PIN list).

        Validates: Requirements 4.6
        """
        # db_session fixture already has an active app context — do not nest another one
        # Populate sales cache with one row so the cache path is taken
        self._populate_sales_cache(db_session)

        source = CookCountySalesDataSource()

        # Build a list larger than _PIN_BATCH_SIZE (100) to confirm no batching
        many_pins = [f"{i:014d}" for i in range(150)]
        # Include the real PIN so we get at least one result
        many_pins.append(self._PIN)

        cutoff = datetime(2020, 1, 1)
        target_classes = ["202"]

        # Should not raise and should not call _socrata_get
        with patch.object(source, "_socrata_get") as mock_get:
            results = source._fetch_sales_for_pins(
                pins=many_pins,
                cutoff_date=cutoff,
                target_classes=target_classes,
            )

        mock_get.assert_not_called()
        # Results is a list (may be empty if no matching rows, that's fine)
        assert isinstance(results, list)

    def test_sales_cache_returns_matching_pin_row(self, app, db_session):
        """When parcel_sales_cache has a matching row, _fetch_sales_for_pins
        returns it without calling _socrata_get.

        Validates: Requirements 4.2, 4.6
        """
        # db_session fixture already has an active app context — do not nest another one
        self._populate_sales_cache(db_session)

        source = CookCountySalesDataSource()
        cutoff = datetime(2020, 1, 1)

        with patch.object(source, "_socrata_get") as mock_get:
            results = source._fetch_sales_for_pins(
                pins=[self._PIN],
                cutoff_date=cutoff,
                target_classes=["202"],
            )

        mock_get.assert_not_called()
        assert len(results) == 1
        assert results[0]["pin"] == self._PIN
        assert results[0]["sale_price"] == "350000"

    # ------------------------------------------------------------------
    # 5. Per-table independence: only empty tables fall back
    # ------------------------------------------------------------------

    def test_partial_cache_universe_populated_sales_empty(self, app, db_session, caplog):
        """When only parcel_universe_cache is populated, the bounding-box
        lookup uses the cache but the sales lookup falls back to the API.

        Validates: Requirements 4.4
        """
        # db_session fixture already has an active app context — do not nest another one
        # Only populate universe cache
        self._populate_universe_cache(db_session)

        source = CookCountySalesDataSource()
        subject = self._make_subject()

        socrata_urls = []

        def fake_socrata_get(url):
            socrata_urls.append(url)
            # Return empty for sales and chars so the method exits cleanly
            return []

        with caplog.at_level(logging.WARNING, logger="app.services.comparable_sales_finder"):
            with patch.object(source, "_socrata_get", side_effect=fake_socrata_get):
                source.fetch_comparables(
                    subject_facts=subject,
                    max_age_months=24,
                    max_distance_miles=1.0,
                    max_count=10,
                )

        # The bounding-box call should NOT have gone to Socrata (cache was used)
        bbox_calls = [u for u in socrata_urls if "pabr-t5kh" in u]
        assert len(bbox_calls) == 0, (
            "parcel_universe_cache was populated; bounding-box should not hit Socrata"
        )

        # The sales call SHOULD have gone to Socrata (cache was empty)
        sales_calls = [u for u in socrata_urls if "wvhk-k5uv" in u]
        assert len(sales_calls) >= 1, (
            "parcel_sales_cache was empty; sales lookup should fall back to Socrata"
        )

        # A warning should have been logged for the empty sales cache
        assert "parcel_sales_cache" in caplog.text
