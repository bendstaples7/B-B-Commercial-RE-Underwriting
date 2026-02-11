"""Test data model structure and relationships."""
import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_property_facts_model_attributes():
    """Test PropertyFacts model has all required attributes."""
    from app.models import PropertyFacts
    
    # Check all required fields exist
    required_fields = [
        'id', 'address', 'property_type', 'units', 'bedrooms', 'bathrooms',
        'square_footage', 'lot_size', 'year_built', 'construction_type',
        'basement', 'parking_spaces', 'last_sale_price', 'last_sale_date',
        'assessed_value', 'annual_taxes', 'zoning', 'interior_condition',
        'latitude', 'longitude', 'data_source', 'user_modified_fields',
        'session_id'
    ]
    
    for field in required_fields:
        assert hasattr(PropertyFacts, field), f"PropertyFacts missing field: {field}"

def test_comparable_sale_model_attributes():
    """Test ComparableSale model has all required attributes."""
    from app.models import ComparableSale
    
    required_fields = [
        'id', 'address', 'sale_date', 'sale_price', 'property_type',
        'units', 'bedrooms', 'bathrooms', 'square_footage', 'lot_size',
        'year_built', 'construction_type', 'interior_condition',
        'distance_miles', 'latitude', 'longitude', 'similarity_notes',
        'session_id'
    ]
    
    for field in required_fields:
        assert hasattr(ComparableSale, field), f"ComparableSale missing field: {field}"

def test_analysis_session_model_attributes():
    """Test AnalysisSession model has all required attributes."""
    from app.models import AnalysisSession
    
    required_fields = [
        'id', 'session_id', 'user_id', 'created_at', 'updated_at',
        'current_step'
    ]
    
    for field in required_fields:
        assert hasattr(AnalysisSession, field), f"AnalysisSession missing field: {field}"

def test_ranked_comparable_model_attributes():
    """Test RankedComparable model has all required attributes."""
    from app.models import RankedComparable
    
    required_fields = [
        'id', 'comparable_id', 'session_id', 'rank', 'total_score',
        'recency_score', 'proximity_score', 'units_score',
        'beds_baths_score', 'sqft_score', 'construction_score',
        'interior_score'
    ]
    
    for field in required_fields:
        assert hasattr(RankedComparable, field), f"RankedComparable missing field: {field}"

def test_valuation_result_model_attributes():
    """Test ValuationResult model has all required attributes."""
    from app.models import ValuationResult
    
    required_fields = [
        'id', 'session_id', 'conservative_arv', 'likely_arv',
        'aggressive_arv', 'all_valuations', 'key_drivers'
    ]
    
    for field in required_fields:
        assert hasattr(ValuationResult, field), f"ValuationResult missing field: {field}"

def test_scenario_models_exist():
    """Test all scenario models exist."""
    from app.models import (
        Scenario, WholesaleScenario, FixFlipScenario, BuyHoldScenario
    )
    
    # Just verify they can be imported
    assert Scenario is not None
    assert WholesaleScenario is not None
    assert FixFlipScenario is not None
    assert BuyHoldScenario is not None

def test_enums_exist():
    """Test all enum types exist."""
    from app.models import (
        PropertyType, ConstructionType, InteriorCondition,
        WorkflowStep, ScenarioType
    )
    
    # Verify enums have expected values
    assert hasattr(PropertyType, 'SINGLE_FAMILY')
    assert hasattr(PropertyType, 'MULTI_FAMILY')
    assert hasattr(PropertyType, 'COMMERCIAL')
    
    assert hasattr(ConstructionType, 'FRAME')
    assert hasattr(ConstructionType, 'BRICK')
    assert hasattr(ConstructionType, 'MASONRY')
    
    assert hasattr(InteriorCondition, 'NEEDS_GUT')
    assert hasattr(InteriorCondition, 'POOR')
    assert hasattr(InteriorCondition, 'AVERAGE')
    assert hasattr(InteriorCondition, 'NEW_RENO')
    assert hasattr(InteriorCondition, 'HIGH_END')
    
    assert hasattr(WorkflowStep, 'PROPERTY_FACTS')
    assert hasattr(WorkflowStep, 'COMPARABLE_SEARCH')
    assert hasattr(WorkflowStep, 'COMPARABLE_REVIEW')
    assert hasattr(WorkflowStep, 'WEIGHTED_SCORING')
    assert hasattr(WorkflowStep, 'VALUATION_MODELS')
    assert hasattr(WorkflowStep, 'REPORT_GENERATION')
    
    assert hasattr(ScenarioType, 'WHOLESALE')
    assert hasattr(ScenarioType, 'FIX_FLIP')
    assert hasattr(ScenarioType, 'BUY_HOLD')

def test_model_table_names():
    """Test models have correct table names."""
    from app.models import (
        PropertyFacts, ComparableSale, AnalysisSession,
        RankedComparable, ValuationResult
    )
    
    assert PropertyFacts.__tablename__ == 'property_facts'
    assert ComparableSale.__tablename__ == 'comparable_sales'
    assert AnalysisSession.__tablename__ == 'analysis_sessions'
    assert RankedComparable.__tablename__ == 'ranked_comparables'
    assert ValuationResult.__tablename__ == 'valuation_results'
