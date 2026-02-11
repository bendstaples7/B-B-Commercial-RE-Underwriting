"""Unit tests for ComparableSalesFinder service."""
import pytest
from datetime import datetime, timedelta
from app.services.comparable_sales_finder import ComparableSalesFinder
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
        finder = ComparableSalesFinder()
        
        # Test single family variations
        assert finder._map_property_type('single family') == PropertyType.SINGLE_FAMILY.value
        assert finder._map_property_type('single-family') == PropertyType.SINGLE_FAMILY.value
        assert finder._map_property_type('sfr') == PropertyType.SINGLE_FAMILY.value
        
        # Test multi family variations
        assert finder._map_property_type('multi family') == PropertyType.MULTI_FAMILY.value
        assert finder._map_property_type('multi-family') == PropertyType.MULTI_FAMILY.value
        assert finder._map_property_type('multifamily') == PropertyType.MULTI_FAMILY.value
        
        # Test commercial variations
        assert finder._map_property_type('commercial') == PropertyType.COMMERCIAL.value
        assert finder._map_property_type('retail') == PropertyType.COMMERCIAL.value
        assert finder._map_property_type('office') == PropertyType.COMMERCIAL.value
        
        # Test None
        assert finder._map_property_type(None) is None
    
    def test_construction_type_mapping(self):
        """Test mapping of external construction types to internal enum."""
        finder = ComparableSalesFinder()
        
        # Test frame variations
        assert finder._map_construction_type('frame') == ConstructionType.FRAME.value
        assert finder._map_construction_type('wood') == ConstructionType.FRAME.value
        assert finder._map_construction_type('wood frame') == ConstructionType.FRAME.value
        
        # Test brick variations
        assert finder._map_construction_type('brick') == ConstructionType.BRICK.value
        assert finder._map_construction_type('brick veneer') == ConstructionType.BRICK.value
        
        # Test masonry variations
        assert finder._map_construction_type('masonry') == ConstructionType.MASONRY.value
        assert finder._map_construction_type('concrete') == ConstructionType.MASONRY.value
        assert finder._map_construction_type('stone') == ConstructionType.MASONRY.value
        
        # Test None (should return default)
        assert finder._map_construction_type(None) == ConstructionType.FRAME.value
    
    def test_interior_condition_mapping(self):
        """Test mapping of external interior conditions to internal enum."""
        finder = ComparableSalesFinder()
        
        # Test needs gut
        assert finder._map_interior_condition('needs gut') == InteriorCondition.NEEDS_GUT.value
        assert finder._map_interior_condition('needs_gut') == InteriorCondition.NEEDS_GUT.value
        
        # Test poor/fair
        assert finder._map_interior_condition('poor') == InteriorCondition.POOR.value
        assert finder._map_interior_condition('fair') == InteriorCondition.POOR.value
        
        # Test average/good
        assert finder._map_interior_condition('average') == InteriorCondition.AVERAGE.value
        assert finder._map_interior_condition('good') == InteriorCondition.AVERAGE.value
        
        # Test new renovation
        assert finder._map_interior_condition('new renovation') == InteriorCondition.NEW_RENO.value
        assert finder._map_interior_condition('renovated') == InteriorCondition.NEW_RENO.value
        
        # Test high end
        assert finder._map_interior_condition('high end') == InteriorCondition.HIGH_END.value
        assert finder._map_interior_condition('luxury') == InteriorCondition.HIGH_END.value
        
        # Test None (should return default)
        assert finder._map_interior_condition(None) == InteriorCondition.AVERAGE.value
