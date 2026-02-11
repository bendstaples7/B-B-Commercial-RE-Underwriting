"""Verify model structure without database connection."""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def verify_models():
    """Verify all models can be imported and have correct structure."""
    print("Verifying model structure...")
    
    try:
        # Import all models
        from app.models import (
            PropertyFacts, PropertyType, ConstructionType, InteriorCondition,
            ComparableSale,
            AnalysisSession, WorkflowStep,
            RankedComparable,
            ValuationResult, ComparableValuation,
            Scenario, ScenarioType,
            WholesaleScenario, FixFlipScenario, BuyHoldScenario
        )
        print("✓ All models imported successfully")
        
        # Verify PropertyFacts fields
        pf_fields = ['address', 'property_type', 'units', 'bedrooms', 'bathrooms',
                     'square_footage', 'lot_size', 'year_built', 'construction_type',
                     'basement', 'parking_spaces', 'assessed_value', 'annual_taxes',
                     'zoning', 'interior_condition', 'latitude', 'longitude']
        for field in pf_fields:
            assert hasattr(PropertyFacts, field), f"Missing field: {field}"
        print("✓ PropertyFacts has all required fields")
        
        # Verify enums
        assert PropertyType.SINGLE_FAMILY.value == 'single_family'
        assert PropertyType.MULTI_FAMILY.value == 'multi_family'
        assert PropertyType.COMMERCIAL.value == 'commercial'
        print("✓ PropertyType enum is correct")
        
        assert ConstructionType.FRAME.value == 'frame'
        assert ConstructionType.BRICK.value == 'brick'
        assert ConstructionType.MASONRY.value == 'masonry'
        print("✓ ConstructionType enum is correct")
        
        assert InteriorCondition.NEEDS_GUT.value == 'needs_gut'
        assert InteriorCondition.POOR.value == 'poor'
        assert InteriorCondition.AVERAGE.value == 'average'
        assert InteriorCondition.NEW_RENO.value == 'new_reno'
        assert InteriorCondition.HIGH_END.value == 'high_end'
        print("✓ InteriorCondition enum is correct")
        
        assert WorkflowStep.PROPERTY_FACTS.value == 1
        assert WorkflowStep.COMPARABLE_SEARCH.value == 2
        assert WorkflowStep.COMPARABLE_REVIEW.value == 3
        assert WorkflowStep.WEIGHTED_SCORING.value == 4
        assert WorkflowStep.VALUATION_MODELS.value == 5
        assert WorkflowStep.REPORT_GENERATION.value == 6
        print("✓ WorkflowStep enum is correct")
        
        assert ScenarioType.WHOLESALE.value == 'wholesale'
        assert ScenarioType.FIX_FLIP.value == 'fix_flip'
        assert ScenarioType.BUY_HOLD.value == 'buy_hold'
        print("✓ ScenarioType enum is correct")
        
        # Verify ComparableSale fields
        cs_fields = ['address', 'sale_date', 'sale_price', 'property_type',
                     'units', 'bedrooms', 'bathrooms', 'square_footage',
                     'distance_miles', 'session_id']
        for field in cs_fields:
            assert hasattr(ComparableSale, field), f"Missing field: {field}"
        print("✓ ComparableSale has all required fields")
        
        # Verify AnalysisSession fields
        as_fields = ['session_id', 'user_id', 'created_at', 'updated_at', 'current_step']
        for field in as_fields:
            assert hasattr(AnalysisSession, field), f"Missing field: {field}"
        print("✓ AnalysisSession has all required fields")
        
        # Verify RankedComparable fields
        rc_fields = ['comparable_id', 'session_id', 'rank', 'total_score',
                     'recency_score', 'proximity_score', 'units_score',
                     'beds_baths_score', 'sqft_score', 'construction_score',
                     'interior_score']
        for field in rc_fields:
            assert hasattr(RankedComparable, field), f"Missing field: {field}"
        print("✓ RankedComparable has all required fields")
        
        # Verify ValuationResult fields
        vr_fields = ['session_id', 'conservative_arv', 'likely_arv',
                     'aggressive_arv', 'all_valuations', 'key_drivers']
        for field in vr_fields:
            assert hasattr(ValuationResult, field), f"Missing field: {field}"
        print("✓ ValuationResult has all required fields")
        
        # Verify scenario models exist
        assert WholesaleScenario is not None
        assert FixFlipScenario is not None
        assert BuyHoldScenario is not None
        print("✓ All scenario models exist")
        
        # Verify table names
        assert PropertyFacts.__tablename__ == 'property_facts'
        assert ComparableSale.__tablename__ == 'comparable_sales'
        assert AnalysisSession.__tablename__ == 'analysis_sessions'
        assert RankedComparable.__tablename__ == 'ranked_comparables'
        assert ValuationResult.__tablename__ == 'valuation_results'
        print("✓ All table names are correct")
        
        print("\n✅ All model verifications passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = verify_models()
    sys.exit(0 if success else 1)
