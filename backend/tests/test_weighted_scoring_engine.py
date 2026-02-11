"""Unit tests for WeightedScoringEngine service."""
import pytest
from datetime import date, timedelta
from app.services.weighted_scoring_engine import WeightedScoringEngine
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition
from app.models.comparable_sale import ComparableSale


class TestWeightedScoringEngine:
    """Test suite for WeightedScoringEngine."""
    
    @pytest.fixture
    def engine(self):
        """Create WeightedScoringEngine instance."""
        return WeightedScoringEngine()
    
    @pytest.fixture
    def subject_property(self):
        """Create a sample subject property."""
        subject = PropertyFacts()
        subject.id = 1
        subject.address = "123 Main St"
        subject.property_type = PropertyType.MULTI_FAMILY
        subject.units = 4
        subject.bedrooms = 8
        subject.bathrooms = 4.0
        subject.square_footage = 3200
        subject.lot_size = 5000
        subject.year_built = 1920
        subject.construction_type = ConstructionType.BRICK
        subject.basement = True
        subject.parking_spaces = 2
        subject.assessed_value = 400000
        subject.annual_taxes = 8000
        subject.zoning = "R4"
        subject.interior_condition = InteriorCondition.AVERAGE
        subject.latitude = 41.8781
        subject.longitude = -87.6298
        return subject
    
    @pytest.fixture
    def comparable_sale(self):
        """Create a sample comparable sale."""
        comp = ComparableSale()
        comp.id = 1
        comp.address = "456 Oak Ave"
        comp.sale_date = date.today() - timedelta(days=90)
        comp.sale_price = 420000
        comp.property_type = PropertyType.MULTI_FAMILY
        comp.units = 4
        comp.bedrooms = 8
        comp.bathrooms = 4.0
        comp.square_footage = 3100
        comp.lot_size = 4800
        comp.year_built = 1925
        comp.construction_type = ConstructionType.BRICK
        comp.interior_condition = InteriorCondition.AVERAGE
        comp.distance_miles = 0.3
        comp.latitude = 41.8800
        comp.longitude = -87.6300
        comp.session_id = 1
        return comp
    
    def test_recency_score_recent_sale(self, engine):
        """Test recency scoring for recent sale."""
        # Sale 30 days ago
        sale_date = date.today() - timedelta(days=30)
        score = engine.calculate_recency_score(sale_date)
        
        # Should be close to 100 (30/365 * 100 = 8.2% reduction)
        assert 90 < score <= 100
    
    def test_recency_score_old_sale(self, engine):
        """Test recency scoring for old sale."""
        # Sale 365 days ago
        sale_date = date.today() - timedelta(days=365)
        score = engine.calculate_recency_score(sale_date)
        
        # Should be 0 (100 - 100 = 0)
        assert score == 0
    
    def test_recency_score_very_old_sale(self, engine):
        """Test recency scoring for very old sale (clamped to 0)."""
        # Sale 730 days ago (2 years)
        sale_date = date.today() - timedelta(days=730)
        score = engine.calculate_recency_score(sale_date)
        
        # Should be clamped to 0
        assert score == 0
    
    def test_proximity_score_closest(self, engine):
        """Test proximity scoring for closest comparable."""
        score = engine.calculate_proximity_score(0.1, 1.0)
        
        # 0.1 miles out of 1.0 max = 90% score
        assert 89 < score <= 91
    
    def test_proximity_score_farthest(self, engine):
        """Test proximity scoring for farthest comparable."""
        score = engine.calculate_proximity_score(1.0, 1.0)
        
        # At max distance = 0% score
        assert score == 0
    
    def test_proximity_score_zero_max_distance(self, engine):
        """Test proximity scoring when all comparables at same location."""
        score = engine.calculate_proximity_score(0.0, 0.0)
        
        # Should return 100 when max distance is 0
        assert score == 100
    
    def test_units_score_exact_match(self, engine):
        """Test units scoring for exact match."""
        score = engine.calculate_units_score(4, 4, 10)
        
        # Exact match = 100
        assert score == 100
    
    def test_units_score_difference(self, engine):
        """Test units scoring with difference."""
        score = engine.calculate_units_score(4, 6, 10)
        
        # Difference of 2 out of max 10 = 80% score
        assert score == 80
    
    def test_units_score_zero_max(self, engine):
        """Test units scoring when max units is 0."""
        score = engine.calculate_units_score(0, 0, 0)
        
        # Should return 100 when max is 0
        assert score == 100
    
    def test_beds_baths_score_exact_match(self, engine):
        """Test beds/baths scoring for exact match."""
        score = engine.calculate_beds_baths_score(3, 2.0, 3, 2.0, 5, 3.0)
        
        # Exact match = 100
        assert score == 100
    
    def test_beds_baths_score_difference(self, engine):
        """Test beds/baths scoring with differences."""
        # 1 bed difference, 0.5 bath difference
        score = engine.calculate_beds_baths_score(3, 2.0, 4, 2.5, 5, 3.0)
        
        # Normalized: (1/5 + 0.5/3) / 2 = (0.2 + 0.167) / 2 = 0.183
        # Score: 100 - 18.3 = 81.7
        assert 80 < score < 83
    
    def test_beds_baths_score_zero_max(self, engine):
        """Test beds/baths scoring when max differences are 0."""
        score = engine.calculate_beds_baths_score(3, 2.0, 3, 2.0, 0, 0.0)
        
        # Should return 100 when max diffs are 0
        assert score == 100
    
    def test_sqft_score_exact_match(self, engine):
        """Test square footage scoring for exact match."""
        score = engine.calculate_sqft_score(3000, 3000)
        
        # Exact match = 100
        assert score == 100
    
    def test_sqft_score_small_difference(self, engine):
        """Test square footage scoring with small difference."""
        score = engine.calculate_sqft_score(3000, 3150)
        
        # 5% difference = 95 score
        assert 94 < score < 96
    
    def test_sqft_score_large_difference(self, engine):
        """Test square footage scoring with large difference."""
        score = engine.calculate_sqft_score(3000, 6000)
        
        # 100% difference = 0 score (clamped)
        assert score == 0
    
    def test_sqft_score_zero_subject(self, engine):
        """Test square footage scoring when subject has 0 sqft."""
        score = engine.calculate_sqft_score(0, 0)
        
        # Both 0 = 100
        assert score == 100
        
        score = engine.calculate_sqft_score(0, 1000)
        
        # Subject 0, comp not 0 = 0
        assert score == 0
    
    def test_construction_score_exact_match(self, engine):
        """Test construction type scoring for exact match."""
        score = engine.calculate_construction_score(
            ConstructionType.BRICK, ConstructionType.BRICK
        )
        
        # Exact match = 100
        assert score == 100
    
    def test_construction_score_similar(self, engine):
        """Test construction type scoring for similar types."""
        score = engine.calculate_construction_score(
            ConstructionType.BRICK, ConstructionType.MASONRY
        )
        
        # Similar = 50
        assert score == 50
    
    def test_construction_score_different(self, engine):
        """Test construction type scoring for different types."""
        score = engine.calculate_construction_score(
            ConstructionType.BRICK, ConstructionType.FRAME
        )
        
        # Different = 0
        assert score == 0
    
    def test_interior_score_exact_match(self, engine):
        """Test interior condition scoring for exact match."""
        score = engine.calculate_interior_score(
            InteriorCondition.AVERAGE, InteriorCondition.AVERAGE
        )
        
        # Exact match = 100
        assert score == 100
    
    def test_interior_score_one_level_apart(self, engine):
        """Test interior condition scoring for adjacent levels."""
        score = engine.calculate_interior_score(
            InteriorCondition.AVERAGE, InteriorCondition.NEW_RENO
        )
        
        # 1 level apart = 75
        assert score == 75
    
    def test_interior_score_two_levels_apart(self, engine):
        """Test interior condition scoring for 2 levels apart."""
        score = engine.calculate_interior_score(
            InteriorCondition.AVERAGE, InteriorCondition.HIGH_END
        )
        
        # 2 levels apart = 50
        assert score == 50
    
    def test_interior_score_three_levels_apart(self, engine):
        """Test interior condition scoring for 3 levels apart."""
        score = engine.calculate_interior_score(
            InteriorCondition.POOR, InteriorCondition.HIGH_END
        )
        
        # 3 levels apart = 25
        assert score == 25
    
    def test_interior_score_four_levels_apart(self, engine):
        """Test interior condition scoring for 4 levels apart."""
        score = engine.calculate_interior_score(
            InteriorCondition.NEEDS_GUT, InteriorCondition.HIGH_END
        )
        
        # 4 levels apart = 0
        assert score == 0
    
    def test_calculate_score_identical_properties(self, engine, subject_property, comparable_sale):
        """Test total score calculation for identical properties."""
        # Make comparable identical to subject
        comparable_sale.units = subject_property.units
        comparable_sale.bedrooms = subject_property.bedrooms
        comparable_sale.bathrooms = subject_property.bathrooms
        comparable_sale.square_footage = subject_property.square_footage
        comparable_sale.construction_type = subject_property.construction_type
        comparable_sale.interior_condition = subject_property.interior_condition
        comparable_sale.distance_miles = 0.0
        comparable_sale.sale_date = date.today()
        
        total_score, breakdown = engine.calculate_score(
            subject_property, comparable_sale, 1.0, 10, 5, 3.0
        )
        
        # Should be close to 100 (all components at 100)
        assert total_score > 99
        assert breakdown['units_score'] == 100
        assert breakdown['beds_baths_score'] == 100
        assert breakdown['sqft_score'] == 100
        assert breakdown['construction_score'] == 100
        assert breakdown['interior_score'] == 100
    
    def test_calculate_score_weights_sum_to_one(self, engine):
        """Test that all scoring weights sum to exactly 1.0."""
        total_weight = (
            engine.WEIGHT_RECENCY +
            engine.WEIGHT_PROXIMITY +
            engine.WEIGHT_UNITS +
            engine.WEIGHT_BEDS_BATHS +
            engine.WEIGHT_SQFT +
            engine.WEIGHT_CONSTRUCTION +
            engine.WEIGHT_INTERIOR
        )
        
        assert abs(total_weight - 1.0) < 0.0001
    
    def test_calculate_score_returns_breakdown(self, engine, subject_property, comparable_sale):
        """Test that calculate_score returns proper breakdown."""
        total_score, breakdown = engine.calculate_score(
            subject_property, comparable_sale, 1.0, 10, 5, 3.0
        )
        
        # Check all breakdown keys exist
        assert 'recency_score' in breakdown
        assert 'proximity_score' in breakdown
        assert 'units_score' in breakdown
        assert 'beds_baths_score' in breakdown
        assert 'sqft_score' in breakdown
        assert 'construction_score' in breakdown
        assert 'interior_score' in breakdown
        
        # Check all scores are in valid range
        for key, value in breakdown.items():
            assert 0 <= value <= 100
    
    def test_rank_comparables_empty_list(self, engine, subject_property):
        """Test ranking with empty comparable list."""
        ranked = engine.rank_comparables(subject_property, [])
        
        assert ranked == []
    
    def test_rank_comparables_single_comparable(self, engine, subject_property, comparable_sale):
        """Test ranking with single comparable."""
        ranked = engine.rank_comparables(subject_property, [comparable_sale])
        
        assert len(ranked) == 1
        assert ranked[0].rank == 1
        assert ranked[0].comparable_id == comparable_sale.id
        assert ranked[0].total_score > 0
    
    def test_rank_comparables_sorting_order(self, engine, subject_property):
        """Test that comparables are sorted by score descending."""
        # Create 3 comparables with different characteristics
        comp1 = ComparableSale()
        comp1.id = 1
        comp1.address = "100 First St"
        comp1.sale_date = date.today() - timedelta(days=30)
        comp1.sale_price = 400000
        comp1.property_type = PropertyType.MULTI_FAMILY
        comp1.units = 4
        comp1.bedrooms = 8
        comp1.bathrooms = 4.0
        comp1.square_footage = 3200
        comp1.lot_size = 5000
        comp1.year_built = 1920
        comp1.construction_type = ConstructionType.BRICK
        comp1.interior_condition = InteriorCondition.AVERAGE
        comp1.distance_miles = 0.2
        comp1.session_id = 1
        
        comp2 = ComparableSale()
        comp2.id = 2
        comp2.address = "200 Second St"
        comp2.sale_date = date.today() - timedelta(days=180)
        comp2.sale_price = 380000
        comp2.property_type = PropertyType.MULTI_FAMILY
        comp2.units = 3
        comp2.bedrooms = 6
        comp2.bathrooms = 3.0
        comp2.square_footage = 2800
        comp2.lot_size = 4500
        comp2.year_built = 1915
        comp2.construction_type = ConstructionType.FRAME
        comp2.interior_condition = InteriorCondition.POOR
        comp2.distance_miles = 0.8
        comp2.session_id = 1
        
        comp3 = ComparableSale()
        comp3.id = 3
        comp3.address = "300 Third St"
        comp3.sale_date = date.today() - timedelta(days=60)
        comp3.sale_price = 410000
        comp3.property_type = PropertyType.MULTI_FAMILY
        comp3.units = 4
        comp3.bedrooms = 8
        comp3.bathrooms = 4.0
        comp3.square_footage = 3100
        comp3.lot_size = 4800
        comp3.year_built = 1925
        comp3.construction_type = ConstructionType.BRICK
        comp3.interior_condition = InteriorCondition.AVERAGE
        comp3.distance_miles = 0.4
        comp3.session_id = 1
        
        ranked = engine.rank_comparables(subject_property, [comp1, comp2, comp3])
        
        # Should have 3 ranked comparables
        assert len(ranked) == 3
        
        # Ranks should be 1, 2, 3
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2
        assert ranked[2].rank == 3
        
        # Scores should be in descending order
        assert ranked[0].total_score >= ranked[1].total_score
        assert ranked[1].total_score >= ranked[2].total_score
        
        # comp1 should be highest (most similar, recent, close)
        # comp2 should be lowest (different units, old, far, poor condition)
        assert ranked[0].comparable_id == comp1.id
        assert ranked[2].comparable_id == comp2.id
    
    def test_rank_comparables_with_tied_scores(self, engine, subject_property):
        """Test ranking with tied scores maintains stable order."""
        # Create 2 identical comparables
        comp1 = ComparableSale()
        comp1.id = 1
        comp1.address = "100 First St"
        comp1.sale_date = date.today() - timedelta(days=90)
        comp1.sale_price = 400000
        comp1.property_type = PropertyType.MULTI_FAMILY
        comp1.units = 4
        comp1.bedrooms = 8
        comp1.bathrooms = 4.0
        comp1.square_footage = 3200
        comp1.lot_size = 5000
        comp1.year_built = 1920
        comp1.construction_type = ConstructionType.BRICK
        comp1.interior_condition = InteriorCondition.AVERAGE
        comp1.distance_miles = 0.5
        comp1.session_id = 1
        
        comp2 = ComparableSale()
        comp2.id = 2
        comp2.address = "200 Second St"
        comp2.sale_date = date.today() - timedelta(days=90)
        comp2.sale_price = 400000
        comp2.property_type = PropertyType.MULTI_FAMILY
        comp2.units = 4
        comp2.bedrooms = 8
        comp2.bathrooms = 4.0
        comp2.square_footage = 3200
        comp2.lot_size = 5000
        comp2.year_built = 1920
        comp2.construction_type = ConstructionType.BRICK
        comp2.interior_condition = InteriorCondition.AVERAGE
        comp2.distance_miles = 0.5
        comp2.session_id = 1
        
        ranked = engine.rank_comparables(subject_property, [comp1, comp2])
        
        # Should have 2 ranked comparables with ranks 1 and 2
        assert len(ranked) == 2
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2
        
        # Scores should be equal or very close
        assert abs(ranked[0].total_score - ranked[1].total_score) < 0.01
    
    def test_rank_comparables_sets_relationship(self, engine, subject_property, comparable_sale):
        """Test that rank_comparables sets the comparable relationship."""
        ranked = engine.rank_comparables(subject_property, [comparable_sale])
        
        assert ranked[0].comparable is not None
        assert ranked[0].comparable.id == comparable_sale.id
        assert ranked[0].comparable.address == comparable_sale.address
