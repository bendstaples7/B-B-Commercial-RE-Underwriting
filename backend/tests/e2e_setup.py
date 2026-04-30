"""End-to-end test environment setup."""
import os
from datetime import datetime, timedelta
from app import create_app, db
from app.models import (
    PropertyFacts, ComparableSale, AnalysisSession,
    RankedComparable, ValuationResult, Scenario
)
from app.models.property_facts import PropertyType, ConstructionType, InteriorCondition
from app.models.analysis_session import WorkflowStep


def create_test_database():
    """Create test database with schema."""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
    return app


def seed_test_data(app):
    """Seed test database with sample data.
    
    Must be called within an active app context.
    Returns a dict with plain data (not detached ORM instances) so
    the caller can use the values safely outside the session.
    """
    # Create sample property facts
    subject_property = PropertyFacts(
        address="123 Main St, Chicago, IL 60601",
        property_type=PropertyType.MULTI_FAMILY,
        units=4,
        bedrooms=8,
        bathrooms=4.0,
        square_footage=3200,
        lot_size=5000,
        year_built=1920,
        construction_type=ConstructionType.BRICK,
        basement=True,
        parking_spaces=2,
        last_sale_price=450000.0,
        last_sale_date=datetime(2022, 6, 15).date(),
        assessed_value=420000.0,
        annual_taxes=8400.0,
        zoning="R-4",
        interior_condition=InteriorCondition.AVERAGE,
        latitude=41.8781,
        longitude=-87.6298,
        data_source="MLS",
        user_modified_fields=[]
    )
    db.session.add(subject_property)
    
    # Create sample comparable sales
    comparables = []
    base_date = datetime.now().date()
    
    # Create sample analysis session first
    session = AnalysisSession(
        session_id="test-session-001",
        user_id="test-user-001",
        created_at=datetime.now(),
        current_step=WorkflowStep.PROPERTY_FACTS
    )
    db.session.add(session)
    db.session.commit()
    
    # Now create comparables linked to session
    for i in range(12):
        comp = ComparableSale(
            address=f"{100 + i * 10} Oak St, Chicago, IL 6060{i % 10}",
            sale_date=base_date - timedelta(days=30 * (i + 1)),
            sale_price=440000 + (i * 5000),
            property_type=PropertyType.MULTI_FAMILY,
            units=4,
            bedrooms=8,
            bathrooms=4.0,
            square_footage=3100 + (i * 50),
            lot_size=4800 + (i * 100),
            year_built=1915 + i,
            construction_type=ConstructionType.BRICK,
            interior_condition=InteriorCondition.AVERAGE,
            distance_miles=0.2 + (i * 0.05),
            latitude=41.8781 + (i * 0.001),
            longitude=-87.6298 + (i * 0.001),
            session_id=session.id
        )
        comparables.append(comp)
        db.session.add(comp)
    
    # Link property to session
    subject_property.session_id = session.id
    db.session.commit()
    
    # Return plain data dict so callers don't hit DetachedInstanceError
    return {
        'session_id': session.session_id,
        'user_id': session.user_id,
        'session_db_id': session.id,
        'subject_property_id': subject_property.id,
        'comparable_count': len(comparables),
        # Keep ORM objects for backward compat (usable within app context)
        'subject_property': subject_property,
        'comparables': comparables,
        'session': session,
    }


def cleanup_test_database(app):
    """Clean up test database."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
