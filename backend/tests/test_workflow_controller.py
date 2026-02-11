"""Unit tests for WorkflowController."""
import pytest
from datetime import datetime, date
from app import db
from app.models import (
    AnalysisSession,
    WorkflowStep,
    PropertyFacts,
    PropertyType,
    ConstructionType,
    InteriorCondition,
    ComparableSale,
    RankedComparable,
    ValuationResult,
)
from app.controllers.workflow_controller import WorkflowController


@pytest.fixture
def controller(app):
    """Create WorkflowController instance."""
    with app.app_context():
        return WorkflowController()


class TestWorkflowController:
    """Test suite for WorkflowController."""
    
    def test_start_analysis(self, app, controller):
        """Test starting a new analysis session."""
        with app.app_context():
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            
            assert 'session_id' in result
            assert result['user_id'] == "user123"
            assert result['current_step'] == WorkflowStep.PROPERTY_FACTS.name
            assert result['status'] == 'initialized'
            
            # Verify session was created in database
            session = AnalysisSession.query.filter_by(session_id=result['session_id']).first()
            assert session is not None
            assert session.user_id == "user123"
            assert session.current_step == WorkflowStep.PROPERTY_FACTS
    
    def test_get_session_state_not_found(self, app, controller):
        """Test getting session state for non-existent session."""
        with app.app_context():
            with pytest.raises(ValueError, match="Session .* not found"):
                controller.get_session_state("nonexistent-session-id")
    
    def test_get_session_state_basic(self, app, controller):
        """Test getting session state for new session."""
        with app.app_context():
            # Create session
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            # Get state
            state = controller.get_session_state(session_id)
            
            assert state['session_id'] == session_id
            assert state['user_id'] == "user123"
            assert state['current_step'] == WorkflowStep.PROPERTY_FACTS.name
            assert 'created_at' in state
            assert 'updated_at' in state
    
    def test_get_session_state_with_property_facts(self, app, controller):
        """Test getting session state with property facts."""
        with app.app_context():
            # Create session
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            # Add property facts
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            property_facts = PropertyFacts(
                session_id=session.id,
                address="123 Main St, Chicago, IL",
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
                assessed_value=250000,
                annual_taxes=5000,
                zoning="R-4",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298
            )
            db.session.add(property_facts)
            db.session.commit()
            
            # Get state
            state = controller.get_session_state(session_id)
            
            assert 'subject_property' in state
            assert state['subject_property']['address'] == "123 Main St, Chicago, IL"
            assert state['subject_property']['units'] == 4
            assert state['subject_property']['property_type'] == PropertyType.MULTI_FAMILY.name
    
    def test_advance_to_step_validation_failure(self, app, controller):
        """Test advancing to step without completing current step."""
        with app.app_context():
            # Create session
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            # Try to advance without property facts
            with pytest.raises(ValueError, match="Property facts must be retrieved"):
                controller.advance_to_step(
                    session_id=session_id,
                    target_step=WorkflowStep.COMPARABLE_SEARCH
                )
    
    def test_advance_to_step_skip_validation(self, app, controller):
        """Test that you cannot skip steps."""
        with app.app_context():
            # Create session with property facts
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            property_facts = PropertyFacts(
                session_id=session.id,
                address="123 Main St, Chicago, IL",
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
                assessed_value=250000,
                annual_taxes=5000,
                zoning="R-4",
                interior_condition=InteriorCondition.AVERAGE
            )
            db.session.add(property_facts)
            db.session.commit()
            
            # Try to skip to step 3
            with pytest.raises(ValueError, match="Must advance sequentially"):
                controller.advance_to_step(
                    session_id=session_id,
                    target_step=WorkflowStep.COMPARABLE_REVIEW
                )
    
    def test_update_step_data_property_facts(self, app, controller):
        """Test updating property facts data."""
        with app.app_context():
            # Create session
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            # Update property facts
            property_data = {
                'address': "123 Main St, Chicago, IL",
                'property_type': 'MULTI_FAMILY',
                'units': 4,
                'bedrooms': 8,
                'bathrooms': 4.0,
                'square_footage': 3200,
                'lot_size': 5000,
                'year_built': 1920,
                'construction_type': 'BRICK',
                'basement': True,
                'parking_spaces': 2,
                'assessed_value': 250000,
                'annual_taxes': 5000,
                'zoning': 'R-4',
                'interior_condition': 'AVERAGE',
                'latitude': 41.8781,
                'longitude': -87.6298
            }
            
            result = controller.update_step_data(
                session_id=session_id,
                step=WorkflowStep.PROPERTY_FACTS,
                data=property_data
            )
            
            assert result['step'] == WorkflowStep.PROPERTY_FACTS.name
            assert 'updated_data' in result
            assert result['updated_data']['units'] == 4
    
    def test_update_step_data_validation_error(self, app, controller):
        """Test validation error when updating step data."""
        with app.app_context():
            # Create session
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            # Try to update with invalid data
            invalid_data = {
                'address': "123 Main St, Chicago, IL",
                'property_type': 'MULTI_FAMILY',
                'units': -1,  # Invalid: negative units
                'bedrooms': 8,
                'bathrooms': 4.0,
                'square_footage': 3200,
                'lot_size': 5000,
                'year_built': 1920,
                'construction_type': 'BRICK',
                'assessed_value': 250000,
                'annual_taxes': 5000,
                'zoning': 'R-4',
                'interior_condition': 'AVERAGE'
            }
            
            with pytest.raises(ValueError, match="Units must be at least 1"):
                controller.update_step_data(
                    session_id=session_id,
                    step=WorkflowStep.PROPERTY_FACTS,
                    data=invalid_data
                )
    
    def test_go_back_to_step(self, app, controller):
        """Test navigating backward to a previous step."""
        with app.app_context():
            # Create session and advance to step 2
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            session.current_step = WorkflowStep.COMPARABLE_REVIEW
            db.session.commit()
            
            # Go back to step 1
            result = controller.go_back_to_step(
                session_id=session_id,
                target_step=WorkflowStep.PROPERTY_FACTS
            )
            
            assert result['current_step'] == WorkflowStep.PROPERTY_FACTS.name
            assert result['previous_step'] == WorkflowStep.COMPARABLE_REVIEW.name
            assert result['navigation'] == 'backward'
            
            # Verify session was updated
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.current_step == WorkflowStep.PROPERTY_FACTS
    
    def test_go_back_to_step_invalid(self, app, controller):
        """Test that you cannot go back to a later step."""
        with app.app_context():
            # Create session
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            # Try to go "back" to a later step
            with pytest.raises(ValueError, match="Target step must be earlier"):
                controller.go_back_to_step(
                    session_id=session_id,
                    target_step=WorkflowStep.COMPARABLE_SEARCH
                )
    
    def test_session_state_persistence(self, app, controller):
        """Test that session state persists across operations."""
        with app.app_context():
            # Create session
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123"
            )
            session_id = result['session_id']
            
            # Add property facts
            property_data = {
                'address': "123 Main St, Chicago, IL",
                'property_type': 'MULTI_FAMILY',
                'units': 4,
                'bedrooms': 8,
                'bathrooms': 4.0,
                'square_footage': 3200,
                'lot_size': 5000,
                'year_built': 1920,
                'construction_type': 'BRICK',
                'basement': True,
                'parking_spaces': 2,
                'assessed_value': 250000,
                'annual_taxes': 5000,
                'zoning': 'R-4',
                'interior_condition': 'AVERAGE'
            }
            
            controller.update_step_data(
                session_id=session_id,
                step=WorkflowStep.PROPERTY_FACTS,
                data=property_data
            )
            
            # Get state and verify persistence
            state = controller.get_session_state(session_id)
            
            assert 'subject_property' in state
            assert state['subject_property']['units'] == 4
            assert state['subject_property']['bedrooms'] == 8
            
            # Modify property facts
            property_data['units'] = 6
            controller.update_step_data(
                session_id=session_id,
                step=WorkflowStep.PROPERTY_FACTS,
                data=property_data
            )
            
            # Verify modification persisted
            state = controller.get_session_state(session_id)
            assert state['subject_property']['units'] == 6
            assert 'units' in state['subject_property']['user_modified_fields']
