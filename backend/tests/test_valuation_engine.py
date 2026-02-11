"""Unit tests for ValuationEngine."""
import pytest
from datetime import date, timedelta
from app.services.valuation_engine import ValuationEngine
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition
from app.models.comparable_sale import ComparableSale
from app.models.ranked_comparable import RankedComparable


class TestValuationEngine:
    """Test suite for ValuationEngine class."""
    
    @pytest.fixture
    def engine(self):
        """Create ValuationEngine instance."""
        return ValuationEngine()
    
    @pytest.fixture
    def subject_property(self):
        """Create sample subject property."""
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
        """Create sample comparable sale."""
        comp = ComparableSale()
        comp.id = 1
        comp.address = "456 Oak Ave"
        comp.sale_date = date.today() - timedelta(days=60)
        comp.sale_price = 420000
        comp.property_type = PropertyType.MULTI_FAMILY
        comp.units = 4
        comp.bedrooms = 8
        comp.bathrooms = 4.0
        comp.square_footage = 3000
        comp.lot_size = 4800
        comp.year_built = 1925
        comp.construction_type = ConstructionType.BRICK
        comp.interior_condition = InteriorCondition.AVERAGE
        comp.distance_miles = 0.3
        comp.latitude = 41.8800
        comp.longitude = -87.6300
        # Add optional fields for testing
        comp.basement = True
        comp.parking_spaces = 2
        return comp
    
    @pytest.fixture
    def ranked_comparable(self, comparable_sale):
        """Create sample ranked comparable."""
        ranked = RankedComparable()
        ranked.id = 1
        ranked.comparable_id = comparable_sale.id
        ranked.session_id = 1
        ranked.rank = 1
        ranked.total_score = 95.5
        ranked.recency_score = 98.0
        ranked.proximity_score = 90.0
        ranked.units_score = 100.0
        ranked.beds_baths_score = 100.0
        ranked.sqft_score = 93.75
        ranked.construction_score = 100.0
        ranked.interior_score = 100.0
        ranked.comparable = comparable_sale
        return ranked
    
    def test_calculate_price_per_sqft(self, engine, subject_property, comparable_sale):
        """Test price per square foot calculation."""
        result = engine.calculate_price_per_sqft(comparable_sale, subject_property)
        
        # Expected: (420000 / 3000) * 3200 = 140 * 3200 = 448000
        assert result == pytest.approx(448000, rel=0.01)
    
    def test_calculate_price_per_sqft_zero_sqft(self, engine, subject_property, comparable_sale):
        """Test price per square foot with zero square footage."""
        comparable_sale.square_footage = 0
        result = engine.calculate_price_per_sqft(comparable_sale, subject_property)
        assert result == 0.0
    
    def test_calculate_price_per_unit(self, engine, subject_property, comparable_sale):
        """Test price per unit calculation."""
        result = engine.calculate_price_per_unit(comparable_sale, subject_property)
        
        # Expected: (420000 / 4) * 4 = 105000 * 4 = 420000
        assert result == pytest.approx(420000, rel=0.01)
    
    def test_calculate_price_per_unit_zero_units(self, engine, subject_property, comparable_sale):
        """Test price per unit with zero units."""
        comparable_sale.units = 0
        result = engine.calculate_price_per_unit(comparable_sale, subject_property)
        assert result == 0.0
    
    def test_calculate_price_per_bedroom(self, engine, subject_property, comparable_sale):
        """Test price per bedroom calculation."""
        result = engine.calculate_price_per_bedroom(comparable_sale, subject_property)
        
        # Expected: (420000 / 8) * 8 = 52500 * 8 = 420000
        assert result == pytest.approx(420000, rel=0.01)
    
    def test_calculate_price_per_bedroom_zero_bedrooms(self, engine, subject_property, comparable_sale):
        """Test price per bedroom with zero bedrooms."""
        comparable_sale.bedrooms = 0
        result = engine.calculate_price_per_bedroom(comparable_sale, subject_property)
        assert result == 0.0
    
    def test_calculate_adjusted_value_no_adjustments(self, engine, subject_property, comparable_sale):
        """Test adjusted value when properties are identical."""
        # Make properties identical
        subject_property.square_footage = comparable_sale.square_footage
        
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Should equal sale price with no adjustments
        assert adjusted_value == comparable_sale.sale_price
        assert len(adjustments) == 0
    
    def test_calculate_adjusted_value_with_sqft_difference(self, engine, subject_property, comparable_sale):
        """Test adjusted value with square footage difference."""
        # Subject has 3200 sqft, comp has 3000 sqft
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Expected adjustment: (3200 - 3000) * 50 = 200 * 50 = 10000
        # Adjusted value: 420000 + 10000 = 430000
        assert adjusted_value == pytest.approx(430000, rel=0.01)
        
        # Check adjustments list
        sqft_adj = next((a for a in adjustments if a['category'] == 'square_footage'), None)
        assert sqft_adj is not None
        assert sqft_adj['adjustment_amount'] == 10000
    
    def test_calculate_adjusted_value_with_unit_difference(self, engine, subject_property, comparable_sale):
        """Test adjusted value with unit difference."""
        subject_property.units = 6
        comparable_sale.units = 4
        subject_property.square_footage = comparable_sale.square_footage  # Remove sqft adjustment
        
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Expected adjustment: (6 - 4) * 15000 = 2 * 15000 = 30000
        # Adjusted value: 420000 + 30000 = 450000
        assert adjusted_value == pytest.approx(450000, rel=0.01)
        
        unit_adj = next((a for a in adjustments if a['category'] == 'units'), None)
        assert unit_adj is not None
        assert unit_adj['adjustment_amount'] == 30000
    
    def test_calculate_adjusted_value_with_bedroom_difference(self, engine, subject_property, comparable_sale):
        """Test adjusted value with bedroom difference."""
        subject_property.bedrooms = 10
        comparable_sale.bedrooms = 8
        subject_property.square_footage = comparable_sale.square_footage
        
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Expected adjustment: (10 - 8) * 5000 = 2 * 5000 = 10000
        assert adjusted_value == pytest.approx(430000, rel=0.01)
        
        bed_adj = next((a for a in adjustments if a['category'] == 'bedrooms'), None)
        assert bed_adj is not None
        assert bed_adj['adjustment_amount'] == 10000
    
    def test_calculate_adjusted_value_with_bathroom_difference(self, engine, subject_property, comparable_sale):
        """Test adjusted value with bathroom difference."""
        subject_property.bathrooms = 5.0
        comparable_sale.bathrooms = 4.0
        subject_property.square_footage = comparable_sale.square_footage
        
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Expected adjustment: (5.0 - 4.0) * 3000 = 1.0 * 3000 = 3000
        assert adjusted_value == pytest.approx(423000, rel=0.01)
        
        bath_adj = next((a for a in adjustments if a['category'] == 'bathrooms'), None)
        assert bath_adj is not None
        assert bath_adj['adjustment_amount'] == 3000
    
    def test_calculate_adjusted_value_with_construction_difference(self, engine, subject_property, comparable_sale):
        """Test adjusted value with construction type difference."""
        subject_property.construction_type = ConstructionType.BRICK
        comparable_sale.construction_type = ConstructionType.FRAME
        subject_property.square_footage = comparable_sale.square_footage
        
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Expected adjustment: +10000 (brick is better than frame)
        assert adjusted_value == pytest.approx(430000, rel=0.01)
        
        const_adj = next((a for a in adjustments if a['category'] == 'construction'), None)
        assert const_adj is not None
        assert const_adj['adjustment_amount'] == 10000
    
    def test_calculate_adjusted_value_with_basement_difference(self, engine, subject_property, comparable_sale):
        """Test adjusted value with basement difference."""
        subject_property.basement = True
        comparable_sale.basement = False
        subject_property.square_footage = comparable_sale.square_footage
        
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Expected adjustment: +8000 (subject has basement)
        assert adjusted_value == pytest.approx(428000, rel=0.01)
        
        basement_adj = next((a for a in adjustments if a['category'] == 'basement'), None)
        assert basement_adj is not None
        assert basement_adj['adjustment_amount'] == 8000
    
    def test_calculate_adjusted_value_with_parking_difference(self, engine, subject_property, comparable_sale):
        """Test adjusted value with parking difference."""
        subject_property.parking_spaces = 3
        comparable_sale.parking_spaces = 1
        subject_property.square_footage = comparable_sale.square_footage
        
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject_property, comparable_sale)
        
        # Expected adjustment: (3 - 1) * 5000 = 2 * 5000 = 10000
        assert adjusted_value == pytest.approx(430000, rel=0.01)
        
        parking_adj = next((a for a in adjustments if a['category'] == 'parking'), None)
        assert parking_adj is not None
        assert parking_adj['adjustment_amount'] == 10000
    
    def test_generate_narrative(self, engine, comparable_sale):
        """Test narrative generation."""
        adjustments = [
            {
                'category': 'square_footage',
                'difference': 200,
                'adjustment_amount': 10000,
                'explanation': 'Square footage difference (3200 vs 3000): +$10,000'
            }
        ]
        
        narrative = engine.generate_narrative(comparable_sale, adjustments, 430000)
        
        assert "456 Oak Ave" in narrative
        assert "$420,000" in narrative
        assert "Adjustments applied:" in narrative
        assert "Square footage difference" in narrative
        assert "$430,000" in narrative
    
    def test_generate_narrative_no_adjustments(self, engine, comparable_sale):
        """Test narrative generation with no adjustments."""
        narrative = engine.generate_narrative(comparable_sale, [], 420000)
        
        assert "456 Oak Ave" in narrative
        assert "No adjustments needed" in narrative
    
    def test_compute_arv_range(self, engine):
        """Test ARV range calculation."""
        valuations = [400000, 420000, 430000, 440000, 450000, 460000, 470000, 480000]
        
        conservative, likely, aggressive = engine.compute_arv_range(valuations)
        
        # Conservative: 25th percentile
        assert conservative == pytest.approx(425000, rel=0.01)
        
        # Likely: median
        assert likely == pytest.approx(445000, rel=0.01)
        
        # Aggressive: 75th percentile
        assert aggressive == pytest.approx(465000, rel=0.01)
    
    def test_compute_arv_range_small_dataset(self, engine):
        """Test ARV range with small dataset."""
        valuations = [400000, 450000]
        
        conservative, likely, aggressive = engine.compute_arv_range(valuations)
        
        # With only 2 values, should use min and max
        assert conservative == 400000
        assert likely == 425000  # median
        assert aggressive == 450000
    
    def test_compute_arv_range_empty_list(self, engine):
        """Test ARV range with empty list."""
        conservative, likely, aggressive = engine.compute_arv_range([])
        
        assert conservative == 0.0
        assert likely == 0.0
        assert aggressive == 0.0
    
    def test_calculate_valuations_with_top_5(self, engine, subject_property, ranked_comparable):
        """Test calculate_valuations with top 5 comparables."""
        # Create 5 ranked comparables
        ranked_comps = []
        for i in range(5):
            comp = ComparableSale()
            comp.id = i + 1
            comp.address = f"{100 + i} Test St"
            comp.sale_date = date.today() - timedelta(days=30 * (i + 1))
            comp.sale_price = 400000 + (i * 10000)
            comp.property_type = PropertyType.MULTI_FAMILY
            comp.units = 4
            comp.bedrooms = 8
            comp.bathrooms = 4.0
            comp.square_footage = 3000 + (i * 100)
            comp.lot_size = 5000
            comp.year_built = 1920
            comp.construction_type = ConstructionType.BRICK
            comp.interior_condition = InteriorCondition.AVERAGE
            comp.distance_miles = 0.2 + (i * 0.1)
            # Add optional fields
            comp.basement = True
            comp.parking_spaces = 2
            
            ranked = RankedComparable()
            ranked.id = i + 1
            ranked.comparable_id = comp.id
            ranked.session_id = 1
            ranked.rank = i + 1
            ranked.total_score = 95.0 - (i * 2)
            ranked.comparable = comp
            
            ranked_comps.append(ranked)
        
        result = engine.calculate_valuations(subject_property, ranked_comps, session_id=1)
        
        # Verify result structure
        assert result.session_id == 1
        assert result.conservative_arv > 0
        assert result.likely_arv > 0
        assert result.aggressive_arv > 0
        assert result.conservative_arv <= result.likely_arv <= result.aggressive_arv
        
        # Should have 20 valuations (5 comps × 4 methods)
        assert len(result.all_valuations) == 20
        
        # Should have key drivers
        assert len(result.key_drivers) > 0
    
    def test_calculate_valuations_uses_only_top_5(self, engine, subject_property):
        """Test that calculate_valuations uses only top 5 comparables."""
        # Create 10 ranked comparables
        ranked_comps = []
        for i in range(10):
            comp = ComparableSale()
            comp.id = i + 1
            comp.address = f"{100 + i} Test St"
            comp.sale_date = date.today() - timedelta(days=30)
            comp.sale_price = 400000
            comp.property_type = PropertyType.MULTI_FAMILY
            comp.units = 4
            comp.bedrooms = 8
            comp.bathrooms = 4.0
            comp.square_footage = 3000
            comp.lot_size = 5000
            comp.year_built = 1920
            comp.construction_type = ConstructionType.BRICK
            comp.interior_condition = InteriorCondition.AVERAGE
            comp.distance_miles = 0.3
            # Add optional fields
            comp.basement = True
            comp.parking_spaces = 2
            
            ranked = RankedComparable()
            ranked.id = i + 1
            ranked.comparable_id = comp.id
            ranked.session_id = 1
            ranked.rank = i + 1
            ranked.total_score = 95.0 - i
            ranked.comparable = comp
            
            ranked_comps.append(ranked)
        
        result = engine.calculate_valuations(subject_property, ranked_comps, session_id=1)
        
        # Should still have only 20 valuations (5 comps × 4 methods)
        assert len(result.all_valuations) == 20


    def test_commercial_property_uses_income_capitalization(self, engine):
        """Test that commercial properties use income capitalization method."""
        # Create commercial subject property
        subject = PropertyFacts()
        subject.property_type = PropertyType.COMMERCIAL
        subject.units = 1
        subject.bedrooms = 0
        subject.bathrooms = 2.0
        subject.square_footage = 5000
        subject.construction_type = ConstructionType.BRICK
        subject.interior_condition = InteriorCondition.AVERAGE
        subject.basement = False
        subject.parking_spaces = 10
        
        # Create commercial comparable
        comp = ComparableSale()
        comp.id = 1
        comp.sale_price = 500000
        comp.square_footage = 4800
        comp.units = 1
        comp.bedrooms = 0
        comp.bathrooms = 2.0
        comp.construction_type = ConstructionType.BRICK
        comp.interior_condition = InteriorCondition.AVERAGE
        comp.parking_spaces = 10
        
        # Calculate income capitalization
        income_cap_value = engine.calculate_income_capitalization(comp, subject)
        
        # Verify it returns a reasonable value
        assert income_cap_value > 0
        # Should be close to subject's proportional value
        expected_value = 500000 * (5000 / 4800)
        assert abs(income_cap_value - expected_value) < 10000
    
    def test_commercial_property_uses_different_adjustment_factors(self, engine):
        """Test that commercial properties use higher adjustment factors."""
        # Create commercial subject property
        subject = PropertyFacts()
        subject.property_type = PropertyType.COMMERCIAL
        subject.units = 2
        subject.bedrooms = 0
        subject.bathrooms = 2.0
        subject.square_footage = 5000
        subject.construction_type = ConstructionType.BRICK
        subject.interior_condition = InteriorCondition.AVERAGE
        subject.basement = False
        subject.parking_spaces = 10
        
        # Create commercial comparable with differences
        comp = ComparableSale()
        comp.id = 1
        comp.sale_price = 500000
        comp.square_footage = 4000
        comp.units = 1
        comp.bedrooms = 0
        comp.bathrooms = 2.0
        comp.construction_type = ConstructionType.FRAME
        comp.interior_condition = InteriorCondition.AVERAGE
        comp.parking_spaces = 5
        
        # Calculate adjusted value
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject, comp)
        
        # Verify commercial adjustment factors are used
        # Unit difference: 1 unit * $25,000 = $25,000
        # Sqft difference: 1000 sqft * $75 = $75,000
        # Construction: brick vs frame = $20,000
        # Parking: 5 spaces * $10,000 = $50,000
        # Total adjustment should be around $170,000
        total_adjustment = sum(adj['adjustment_amount'] for adj in adjustments)
        assert total_adjustment > 150000  # Should be significantly higher than residential
    
    def test_residential_property_excludes_bedroom_bathroom_for_commercial(self, engine):
        """Test that commercial properties don't use bedroom/bathroom adjustments."""
        # Create commercial subject property
        subject = PropertyFacts()
        subject.property_type = PropertyType.COMMERCIAL
        subject.units = 1
        subject.bedrooms = 0
        subject.bathrooms = 2.0
        subject.square_footage = 5000
        subject.construction_type = ConstructionType.BRICK
        subject.interior_condition = InteriorCondition.AVERAGE
        subject.basement = False
        subject.parking_spaces = 10
        
        # Create commercial comparable
        comp = ComparableSale()
        comp.id = 1
        comp.sale_price = 500000
        comp.square_footage = 5000
        comp.units = 1
        comp.bedrooms = 0
        comp.bathrooms = 2.0
        comp.construction_type = ConstructionType.BRICK
        comp.interior_condition = InteriorCondition.AVERAGE
        comp.parking_spaces = 10
        
        # Calculate adjusted value
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject, comp)
        
        # Verify no bedroom or bathroom adjustments
        adjustment_categories = [adj['category'] for adj in adjustments]
        assert 'bedrooms' not in adjustment_categories
        assert 'bathrooms' not in adjustment_categories
    
    def test_residential_property_includes_bedroom_bathroom_adjustments(self, engine):
        """Test that residential properties include bedroom/bathroom adjustments."""
        # Create residential subject property
        subject = PropertyFacts()
        subject.property_type = PropertyType.SINGLE_FAMILY
        subject.units = 1
        subject.bedrooms = 4
        subject.bathrooms = 2.5
        subject.square_footage = 2000
        subject.construction_type = ConstructionType.BRICK
        subject.interior_condition = InteriorCondition.AVERAGE
        subject.basement = True
        subject.parking_spaces = 2
        
        # Create residential comparable with differences
        comp = ComparableSale()
        comp.id = 1
        comp.sale_price = 300000
        comp.square_footage = 2000
        comp.units = 1
        comp.bedrooms = 3
        comp.bathrooms = 2.0
        comp.construction_type = ConstructionType.BRICK
        comp.interior_condition = InteriorCondition.AVERAGE
        comp.parking_spaces = 2
        comp.basement = True
        
        # Calculate adjusted value
        adjusted_value, adjustments = engine.calculate_adjusted_value(subject, comp)
        
        # Verify bedroom and bathroom adjustments are present
        adjustment_categories = [adj['category'] for adj in adjustments]
        assert 'bedrooms' in adjustment_categories
        assert 'bathrooms' in adjustment_categories
