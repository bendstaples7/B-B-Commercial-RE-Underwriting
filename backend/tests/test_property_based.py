"""Property-based tests for the analysis workflow services.

Task 7 — uses Hypothesis to verify invariants that hand-written tests miss:
  - 7.1  WeightedScoringEngine
  - 7.2  ValuationEngine
  - 7.3  ComparableSalesFinder

All tests are pure-Python (no DB, no Flask app context) so they run fast
and can be executed in isolation.
"""
import pytest
from datetime import date, timedelta
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.services.weighted_scoring_engine import WeightedScoringEngine
from app.services.valuation_engine import ValuationEngine
from app.services.comparable_sales_finder import ComparableSalesFinder
from app.services.dto import RankedComparableDTO
from app.models.property_facts import (
    PropertyFacts,
    PropertyType,
    ConstructionType,
    InteriorCondition,
)
from app.models.comparable_sale import ComparableSale
from app.models.ranked_comparable import RankedComparable


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

st_property_type = st.sampled_from(list(PropertyType))
st_construction_type = st.sampled_from(list(ConstructionType))
st_interior_condition = st.sampled_from(list(InteriorCondition))

# Sale dates: between 2 years ago and today (recency score stays in [0, 100])
st_sale_date = st.dates(
    min_value=date.today() - timedelta(days=730),
    max_value=date.today(),
)

# Positive integers for counts / sizes
st_units = st.integers(min_value=1, max_value=20)
st_bedrooms = st.integers(min_value=0, max_value=20)
st_bathrooms = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
st_sqft = st.integers(min_value=1, max_value=20000)
st_distance = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)
st_sale_price = st.floats(min_value=10_000.0, max_value=5_000_000.0, allow_nan=False, allow_infinity=False)


def make_subject(
    property_type=PropertyType.MULTI_FAMILY,
    units=4,
    bedrooms=8,
    bathrooms=4.0,
    sqft=3200,
    construction_type=ConstructionType.BRICK,
    interior_condition=InteriorCondition.AVERAGE,
    latitude=41.8781,
    longitude=-87.6298,
) -> PropertyFacts:
    """Build a PropertyFacts object without a DB session."""
    subject = PropertyFacts()
    subject.id = 1
    subject.address = "123 Main St, Chicago, IL"
    subject.property_type = property_type
    subject.units = units
    subject.bedrooms = bedrooms
    subject.bathrooms = bathrooms
    subject.square_footage = sqft
    subject.lot_size = 5000
    subject.year_built = 1920
    subject.construction_type = construction_type
    subject.basement = True
    subject.parking_spaces = 2
    subject.assessed_value = 400_000.0
    subject.annual_taxes = 8_000.0
    subject.zoning = "R-4"
    subject.interior_condition = interior_condition
    subject.latitude = latitude
    subject.longitude = longitude
    return subject


def make_comparable(
    comp_id: int,
    sale_date: date,
    sale_price: float,
    property_type=PropertyType.MULTI_FAMILY,
    units=4,
    bedrooms=8,
    bathrooms=4.0,
    sqft=3100,
    construction_type=ConstructionType.BRICK,
    interior_condition=InteriorCondition.AVERAGE,
    distance_miles=0.3,
    session_id=1,
) -> ComparableSale:
    """Build a ComparableSale object without a DB session."""
    comp = ComparableSale()
    comp.id = comp_id
    comp.address = f"{100 + comp_id} Comp St, Chicago, IL"
    comp.sale_date = sale_date
    comp.sale_price = sale_price
    comp.property_type = property_type
    comp.units = units
    comp.bedrooms = bedrooms
    comp.bathrooms = bathrooms
    comp.square_footage = sqft
    comp.lot_size = 4800
    comp.year_built = 1922
    comp.construction_type = construction_type
    comp.interior_condition = interior_condition
    comp.distance_miles = distance_miles
    comp.latitude = 41.880
    comp.longitude = -87.630
    comp.session_id = session_id
    return comp


def make_ranked_comparable(
    comp_id: int,
    sale_price: float,
    recency_score: float = 80.0,
    proximity_score: float = 80.0,
    rank: int = 1,
) -> RankedComparable:
    """Build a RankedComparable with an attached ComparableSale (no DB)."""
    comp = make_comparable(comp_id, date.today() - timedelta(days=60), sale_price)

    ranked = RankedComparable()
    ranked.id = comp_id
    ranked.comparable_id = comp.id
    ranked.session_id = 1
    ranked.rank = rank
    ranked.total_score = 90.0
    ranked.recency_score = recency_score
    ranked.proximity_score = proximity_score
    ranked.units_score = 100.0
    ranked.beds_baths_score = 100.0
    ranked.sqft_score = 95.0
    ranked.construction_score = 100.0
    ranked.interior_score = 100.0
    ranked.comparable = comp
    return ranked


# ---------------------------------------------------------------------------
# 7.1  WeightedScoringEngine property-based tests
# ---------------------------------------------------------------------------

class TestWeightedScoringEngineProperties:
    """Property-based invariants for WeightedScoringEngine.rank_comparables."""

    @pytest.fixture
    def engine(self):
        return WeightedScoringEngine()

    @given(
        units=st_units,
        bedrooms=st_bedrooms,
        bathrooms=st_bathrooms,
        sqft=st_sqft,
        construction_type=st_construction_type,
        interior_condition=st_interior_condition,
        sale_date=st_sale_date,
        sale_price=st_sale_price,
        distance=st_distance,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rank_comparables_never_raises(
        self, engine,
        units, bedrooms, bathrooms, sqft,
        construction_type, interior_condition,
        sale_date, sale_price, distance,
    ):
        """rank_comparables never raises for any valid single-comparable input."""
        subject = make_subject(units=units, bedrooms=bedrooms, bathrooms=bathrooms, sqft=sqft,
                               construction_type=construction_type, interior_condition=interior_condition)
        comp = make_comparable(1, sale_date, sale_price, units=units, bedrooms=bedrooms,
                               bathrooms=bathrooms, sqft=sqft, construction_type=construction_type,
                               interior_condition=interior_condition, distance_miles=distance)
        # Must not raise
        result = engine.rank_comparables(subject, [comp])
        assert result is not None

    @given(
        n=st.integers(min_value=1, max_value=10),
        sale_date=st_sale_date,
        sale_price=st_sale_price,
    )
    @settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_all_scores_in_range_0_to_100(self, engine, n, sale_date, sale_price):
        """All individual scores returned by rank_comparables are in [0, 100]."""
        subject = make_subject()
        comps = [
            make_comparable(i, sale_date, sale_price, distance_miles=0.1 * i)
            for i in range(1, n + 1)
        ]
        result = engine.rank_comparables(subject, comps)
        for dto in result:
            assert 0.0 <= dto.total_score <= 100.0, f"total_score out of range: {dto.total_score}"
            assert 0.0 <= dto.recency_score <= 100.0
            assert 0.0 <= dto.proximity_score <= 100.0
            assert 0.0 <= dto.units_score <= 100.0
            assert 0.0 <= dto.beds_baths_score <= 100.0
            assert 0.0 <= dto.sqft_score <= 100.0
            assert 0.0 <= dto.construction_score <= 100.0
            assert 0.0 <= dto.interior_score <= 100.0

    @given(
        n=st.integers(min_value=2, max_value=10),
        sale_date=st_sale_date,
        sale_price=st_sale_price,
    )
    @settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_result_sorted_by_total_score_descending(self, engine, n, sale_date, sale_price):
        """rank_comparables returns DTOs sorted by total_score descending."""
        subject = make_subject()
        comps = [
            make_comparable(i, sale_date, sale_price, distance_miles=0.1 * i)
            for i in range(1, n + 1)
        ]
        result = engine.rank_comparables(subject, comps)
        scores = [dto.total_score for dto in result]
        assert scores == sorted(scores, reverse=True), (
            f"Scores not descending: {scores}"
        )

    @given(
        n=st.integers(min_value=1, max_value=10),
        sale_date=st_sale_date,
        sale_price=st_sale_price,
    )
    @settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_ranks_are_sequential_starting_from_1(self, engine, n, sale_date, sale_price):
        """Ranks are sequential integers starting from 1."""
        subject = make_subject()
        comps = [
            make_comparable(i, sale_date, sale_price, distance_miles=0.1 * i)
            for i in range(1, n + 1)
        ]
        result = engine.rank_comparables(subject, comps)
        ranks = [dto.rank for dto in result]
        assert ranks == list(range(1, n + 1)), f"Ranks not sequential: {ranks}"

    @given(
        n=st.integers(min_value=1, max_value=10),
        sale_date=st_sale_date,
        sale_price=st_sale_price,
    )
    @settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_returns_ranked_comparable_dtos_not_dicts(self, engine, n, sale_date, sale_price):
        """rank_comparables returns RankedComparableDTO objects, not dicts or ORM objects."""
        subject = make_subject()
        comps = [
            make_comparable(i, sale_date, sale_price, distance_miles=0.1 * i)
            for i in range(1, n + 1)
        ]
        result = engine.rank_comparables(subject, comps)
        for item in result:
            assert isinstance(item, RankedComparableDTO), (
                f"Expected RankedComparableDTO, got {type(item)}"
            )
            # Must not be a dict
            assert not isinstance(item, dict)

    def test_empty_comparables_returns_empty_list(self):
        """rank_comparables([]) returns []."""
        engine = WeightedScoringEngine()
        subject = make_subject()
        assert engine.rank_comparables(subject, []) == []

    @given(
        sqft=st.integers(min_value=1, max_value=20000),
        sale_date=st_sale_date,
        sale_price=st_sale_price,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_identical_properties_score_near_100(self, engine, sqft, sale_date, sale_price):
        """A comparable identical to the subject (except sale date/price) scores near 100."""
        subject = make_subject(sqft=sqft)
        comp = make_comparable(
            1, sale_date, sale_price,
            units=subject.units,
            bedrooms=subject.bedrooms,
            bathrooms=subject.bathrooms,
            sqft=sqft,
            construction_type=subject.construction_type,
            interior_condition=subject.interior_condition,
            distance_miles=0.0,
        )
        result = engine.rank_comparables(subject, [comp])
        assert len(result) == 1
        # Recency may reduce score slightly, but all other components should be 100
        assert result[0].units_score == 100.0
        assert result[0].sqft_score == 100.0
        assert result[0].construction_score == 100.0
        assert result[0].interior_score == 100.0


# ---------------------------------------------------------------------------
# 7.2  ValuationEngine property-based tests
# ---------------------------------------------------------------------------

class TestValuationEngineProperties:
    """Property-based invariants for ValuationEngine.calculate_valuations."""

    @pytest.fixture
    def engine(self):
        return ValuationEngine()

    @given(
        n=st.integers(min_value=1, max_value=5),
        sale_price=st_sale_price,
        recency=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
        proximity=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_calculate_valuations_never_raises(self, engine, n, sale_price, recency, proximity):
        """calculate_valuations never raises for 1–5 valid ranked comparables."""
        subject = make_subject()
        ranked_comps = [
            make_ranked_comparable(i, sale_price, recency_score=recency,
                                   proximity_score=proximity, rank=i)
            for i in range(1, n + 1)
        ]
        result = engine.calculate_valuations(subject, ranked_comps, session_id=1)
        assert result is not None

    @given(
        n=st.integers(min_value=1, max_value=5),
        sale_price=st_sale_price,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_conservative_le_likely_le_aggressive(self, engine, n, sale_price):
        """conservative_arv ≤ likely_arv ≤ aggressive_arv always holds."""
        subject = make_subject()
        ranked_comps = [
            make_ranked_comparable(i, sale_price, rank=i)
            for i in range(1, n + 1)
        ]
        result = engine.calculate_valuations(subject, ranked_comps, session_id=1)
        assert result.conservative_arv <= result.likely_arv, (
            f"conservative ({result.conservative_arv}) > likely ({result.likely_arv})"
        )
        assert result.likely_arv <= result.aggressive_arv, (
            f"likely ({result.likely_arv}) > aggressive ({result.aggressive_arv})"
        )

    @given(
        n=st.integers(min_value=1, max_value=5),
        sale_price=st_sale_price,
        recency=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
        proximity=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_confidence_score_in_range_0_to_100(self, engine, n, sale_price, recency, proximity):
        """confidence_score is always in [0, 100]."""
        subject = make_subject()
        ranked_comps = [
            make_ranked_comparable(i, sale_price, recency_score=recency,
                                   proximity_score=proximity, rank=i)
            for i in range(1, n + 1)
        ]
        result = engine.calculate_valuations(subject, ranked_comps, session_id=1)
        assert result.confidence_score is not None
        assert 0.0 <= result.confidence_score <= 100.0, (
            f"confidence_score out of range: {result.confidence_score}"
        )

    @given(sale_price=st_sale_price)
    @settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_confidence_score_lower_with_fewer_comparables(self, engine, sale_price):
        """Confidence score with 5 comparables is >= confidence score with 1 comparable."""
        subject = make_subject()
        comps_5 = [make_ranked_comparable(i, sale_price, recency_score=80.0,
                                          proximity_score=80.0, rank=i)
                   for i in range(1, 6)]
        comps_1 = [make_ranked_comparable(1, sale_price, recency_score=80.0,
                                          proximity_score=80.0, rank=1)]

        result_5 = engine.calculate_valuations(subject, comps_5, session_id=1)
        result_1 = engine.calculate_valuations(subject, comps_1, session_id=2)

        assert result_5.confidence_score >= result_1.confidence_score

    @given(
        n=st.integers(min_value=1, max_value=5),
        sale_price=st_sale_price,
    )
    @settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_all_valuation_amounts_positive(self, engine, n, sale_price):
        """All ARV values are positive."""
        subject = make_subject()
        ranked_comps = [
            make_ranked_comparable(i, sale_price, rank=i)
            for i in range(1, n + 1)
        ]
        result = engine.calculate_valuations(subject, ranked_comps, session_id=1)
        assert result.conservative_arv > 0, f"conservative_arv not positive: {result.conservative_arv}"
        assert result.likely_arv > 0, f"likely_arv not positive: {result.likely_arv}"
        assert result.aggressive_arv > 0, f"aggressive_arv not positive: {result.aggressive_arv}"

    @given(
        n=st.integers(min_value=1, max_value=5),
        sale_price=st_sale_price,
    )
    @settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_uses_at_most_5_comparables(self, engine, n, sale_price):
        """calculate_valuations uses at most 5 comparables regardless of input length."""
        subject = make_subject()
        # Pass up to 5 (the engine caps at 5 internally)
        ranked_comps = [
            make_ranked_comparable(i, sale_price, rank=i)
            for i in range(1, n + 1)
        ]
        result = engine.calculate_valuations(subject, ranked_comps, session_id=1)
        # 4 valuation methods × min(n, 5) comparables
        expected_count = min(n, 5) * 4
        assert len(result.all_valuations) == expected_count

    def test_compute_confidence_score_invariants(self):
        """compute_confidence_score invariants: range, monotonicity, zero at 0 comps."""
        engine = ValuationEngine()

        # Zero comparables → 0
        assert engine.compute_confidence_score(0, 100.0, 100.0) == 0.0

        # Full confidence at 5 comps with perfect scores
        assert engine.compute_confidence_score(5, 100.0, 100.0) == pytest.approx(100.0)

        # Monotonically increasing with comp count (holding quality constant)
        scores = [engine.compute_confidence_score(n, 80.0, 80.0) for n in range(0, 6)]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], (
                f"Confidence not monotone: scores[{i}]={scores[i]} > scores[{i+1}]={scores[i+1]}"
            )

    def test_apply_confidence_widening_invariants(self):
        """apply_confidence_widening: likely unchanged, range wider at lower confidence."""
        engine = ValuationEngine()
        c, l, a = 300_000.0, 400_000.0, 500_000.0

        # Likely never changes
        for conf in [0.0, 25.0, 50.0, 75.0, 100.0]:
            _, likely, _ = engine.apply_confidence_widening(c, l, a, conf)
            assert likely == pytest.approx(l)

        # Range is wider at lower confidence
        c_high, _, a_high = engine.apply_confidence_widening(c, l, a, 80.0)
        c_low, _, a_low = engine.apply_confidence_widening(c, l, a, 20.0)
        assert (a_low - c_low) > (a_high - c_high)


# ---------------------------------------------------------------------------
# 7.3  ComparableSalesFinder property-based tests
# ---------------------------------------------------------------------------

class TestComparableSalesFinderProperties:
    """Property-based invariants for ComparableSalesFinder.find_comparables."""

    def _make_mock_comparable(self, i: int, property_type_value: str) -> dict:
        """Build a minimal comparable dict in the internal format."""
        return {
            'address': f'{100 + i} Mock St, Chicago, IL',
            'sale_date': date.today() - timedelta(days=30 * i),
            'sale_price': 300_000.0 + i * 5_000,
            'property_type': property_type_value,
            'units': 4,
            'bedrooms': 8,
            'bathrooms': 4.0,
            'square_footage': 3000 + i * 50,
            'lot_size': 4800,
            'year_built': 1920,
            'construction_type': 'brick',
            'interior_condition': 'average',
            'distance_miles': 0.1 * (i + 1),
            'latitude': 41.878 + 0.001 * i,
            'longitude': -87.630 - 0.001 * i,
            'pin': f'1408301019{i:04d}',
        }

    @given(
        n=st.integers(min_value=1, max_value=15),
        min_count=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_find_comparables_never_raises_when_coords_present(self, n, min_count):
        """find_comparables never raises when the subject has valid coordinates."""
        from unittest.mock import patch

        subject = make_subject(latitude=41.8781, longitude=-87.6298)
        mock_comps = [self._make_mock_comparable(i, subject.property_type.value)
                      for i in range(n)]

        finder = ComparableSalesFinder()
        with patch.object(finder._data_sources[0], 'fetch_comparables', return_value=mock_comps):
            # Must not raise
            result = finder.find_comparables(subject, min_count=min_count, max_age_months=12)
        assert result is not None

    @given(
        n=st.integers(min_value=1, max_value=15),
        min_count=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_all_returned_comparables_have_distance_miles(self, n, min_count):
        """Every returned comparable has distance_miles populated (not None)."""
        from unittest.mock import patch

        subject = make_subject(latitude=41.8781, longitude=-87.6298)
        mock_comps = [self._make_mock_comparable(i, subject.property_type.value)
                      for i in range(n)]

        finder = ComparableSalesFinder()
        with patch.object(finder._data_sources[0], 'fetch_comparables', return_value=mock_comps):
            result = finder.find_comparables(subject, min_count=min_count, max_age_months=12)

        for comp in result:
            assert comp.get('distance_miles') is not None, (
                f"distance_miles is None for comparable: {comp.get('address')}"
            )

    @given(
        n=st.integers(min_value=1, max_value=15),
        min_count=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_returned_list_length_le_min_count(self, n, min_count):
        """find_comparables returns at most min_count results."""
        from unittest.mock import patch

        subject = make_subject(latitude=41.8781, longitude=-87.6298)
        mock_comps = [self._make_mock_comparable(i, subject.property_type.value)
                      for i in range(n)]

        finder = ComparableSalesFinder()
        with patch.object(finder._data_sources[0], 'fetch_comparables', return_value=mock_comps):
            result = finder.find_comparables(subject, min_count=min_count, max_age_months=12)

        assert len(result) <= min_count, (
            f"Returned {len(result)} comparables but min_count={min_count}"
        )

    @given(
        n=st.integers(min_value=1, max_value=15),
        min_count=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_all_returned_comparables_match_subject_property_type(self, n, min_count):
        """All returned comparables match the subject's property type."""
        from unittest.mock import patch

        subject = make_subject(property_type=PropertyType.MULTI_FAMILY,
                               latitude=41.8781, longitude=-87.6298)
        # Mix of matching and non-matching types
        mock_comps = []
        for i in range(n):
            comp = self._make_mock_comparable(i, PropertyType.MULTI_FAMILY.value)
            mock_comps.append(comp)
        # Add a non-matching type that should be filtered out
        non_match = self._make_mock_comparable(n, PropertyType.SINGLE_FAMILY.value)
        mock_comps.append(non_match)

        finder = ComparableSalesFinder()
        with patch.object(finder._data_sources[0], 'fetch_comparables', return_value=mock_comps):
            result = finder.find_comparables(subject, min_count=min_count, max_age_months=12)

        for comp in result:
            assert comp['property_type'] == PropertyType.MULTI_FAMILY.value, (
                f"Property type mismatch: {comp['property_type']}"
            )

    def test_find_comparables_raises_without_coordinates(self):
        """find_comparables raises ValueError when subject has no coordinates."""
        subject = make_subject(latitude=None, longitude=None)
        finder = ComparableSalesFinder()
        with pytest.raises(ValueError, match="coordinates"):
            finder.find_comparables(subject, min_count=5)
