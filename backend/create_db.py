"""Database initialization script using SQLAlchemy."""
import os
import sys

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import (
    PropertyFacts,
    ComparableSale,
    AnalysisSession,
    RankedComparable,
    ValuationResult,
    ComparableValuation,
    Scenario,
    WholesaleScenario,
    FixFlipScenario,
    BuyHoldScenario
)

def init_db():
    """Initialize the database with all tables."""
    app = create_app()
    
    with app.app_context():
        print("Creating database tables...")
        
        # Create all tables
        db.create_all()
        
        print("Database tables created successfully!")
        print("\nCreated tables:")
        print("  - property_facts")
        print("  - comparable_sales")
        print("  - analysis_sessions")
        print("  - ranked_comparables")
        print("  - valuation_results")
        print("  - comparable_valuations")
        print("  - scenarios")
        print("  - wholesale_scenarios")
        print("  - fix_flip_scenarios")
        print("  - buy_hold_scenarios")

if __name__ == '__main__':
    init_db()
