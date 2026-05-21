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
    ScoringWeights,
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

    def test_start_analysis_places_coords_fallback_when_cook_county_null(self, app, controller):
        """Places coordinates are stored when Cook County returns null lat/lng."""
        from unittest.mock import patch

        mock_facts_no_coords = {
            'address': '456 Oak Ave, Chicago, IL 60602',
            'property_type': 'SINGLE_FAMILY',
            'units': 1,
            'bedrooms': 3,
            'bathrooms': 2.0,
            'square_footage': 1500,
            'lot_size': 3000,
            'year_built': 1960,
            'construction_type': 'FRAME',
            'basement': False,
            'parking_spaces': 1,
            'assessed_value': 200000.0,
            'annual_taxes': None,
            'zoning': None,
            'latitude': None,
            'longitude': None,
            'data_source': 'cook_county_assessor',
            'user_modified_fields': [],
        }

        with app.app_context():
            with patch(
                'app.services.property_data_service.PropertyDataService.fetch_property_facts',
                return_value=mock_facts_no_coords,
            ):
                result = controller.start_analysis(
                    address='456 Oak Ave, Chicago, IL 60602',
                    user_id='user123',
                    latitude=41.9000,
                    longitude=-87.7000,
                )

            # Places coordinates should be surfaced in property_facts
            facts = result.get('property_facts', {})
            assert facts.get('latitude') == 41.9000
            assert facts.get('longitude') == -87.7000

    def test_start_analysis_cook_county_coords_take_precedence(self, app, controller):
        """Cook County coordinates take precedence over Places coordinates."""
        from unittest.mock import patch

        mock_facts_with_coords = {
            'address': '789 Elm St, Chicago, IL 60603',
            'property_type': 'SINGLE_FAMILY',
            'units': 1,
            'bedrooms': 2,
            'bathrooms': 1.0,
            'square_footage': 1200,
            'lot_size': 2500,
            'year_built': 1950,
            'construction_type': 'BRICK',
            'basement': True,
            'parking_spaces': 0,
            'assessed_value': 150000.0,
            'annual_taxes': None,
            'zoning': None,
            'latitude': 41.8500,
            'longitude': -87.6500,
            'data_source': 'cook_county_assessor',
            'user_modified_fields': [],
        }

        with app.app_context():
            with patch(
                'app.services.property_data_service.PropertyDataService.fetch_property_facts',
                return_value=mock_facts_with_coords,
            ):
                result = controller.start_analysis(
                    address='789 Elm St, Chicago, IL 60603',
                    user_id='user123',
                    latitude=41.9999,
                    longitude=-87.9999,
                )

            facts = result.get('property_facts', {})
            # Cook County wins
            assert facts.get('latitude') == 41.8500
            assert facts.get('longitude') == -87.6500

    def test_start_analysis_places_coords_used_when_cook_county_unavailable(self, app, controller):
        """When Cook County returns nothing, Places coordinates appear in property_facts."""
        from unittest.mock import patch

        with app.app_context():
            with patch(
                'app.services.property_data_service.PropertyDataService.fetch_property_facts',
                return_value=None,
            ):
                result = controller.start_analysis(
                    address='999 Unknown Rd, Chicago, IL 60699',
                    user_id='user123',
                    latitude=41.8000,
                    longitude=-87.6000,
                )

            facts = result.get('property_facts', {})
            assert facts is not None
            assert facts.get('latitude') == 41.8000
            assert facts.get('longitude') == -87.6000
            assert facts.get('data_source') == 'google_places'

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


class TestValidateStepCompletionWarnings:
    """Tests for the refactored _validate_step_completion warning behaviour."""

    def _make_session_with_facts(self, app, controller):
        """Helper: create a session and add confirmed property facts."""
        with app.app_context():
            result = controller.start_analysis(
                address="123 Main St, Chicago, IL",
                user_id="user123",
            )
            session_id = result['session_id']
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            property_facts = PropertyFacts(
                session_id=session.id,
                address="123 Main St, Chicago, IL",
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.5,
                square_footage=1400,
                lot_size=4500,
                year_built=1955,
                construction_type=ConstructionType.FRAME,
                basement=True,
                parking_spaces=1,
                assessed_value=180000.0,
                annual_taxes=4200.0,
                zoning="RS-3",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
            )
            db.session.add(property_facts)
            db.session.commit()
            return session_id

    def test_validate_returns_empty_list_when_no_warnings(self, app, controller):
        """_validate_step_completion returns [] when step is fully satisfied."""
        with app.app_context():
            session_id = self._make_session_with_facts(app, controller)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            warnings = controller._validate_step_completion(
                session, WorkflowStep.PROPERTY_FACTS
            )
            assert warnings == []

    def test_validate_comparable_review_below_threshold_returns_warning(self, app, controller):
        """Fewer comparables than MIN_COMPARABLES produces a warning, not an error."""
        with app.app_context():
            session_id = self._make_session_with_facts(app, controller)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Add a single comparable (below the default threshold of 1 in testing,
            # but we can verify the warning logic by temporarily raising the threshold)
            comparable = ComparableSale(
                session_id=session.id,
                address="456 Oak Ave, Chicago, IL",
                sale_date=datetime(2025, 1, 15).date(),
                sale_price=210000.0,
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.0,
                square_footage=1350,
                lot_size=4000,
                year_built=1950,
                construction_type=ConstructionType.FRAME,
                interior_condition=InteriorCondition.AVERAGE,
                distance_miles=0.3,
            )
            db.session.add(comparable)
            db.session.commit()

            # Temporarily raise the threshold above the number of comparables we have
            from flask import current_app
            original = app.config['MIN_COMPARABLES']
            app.config['MIN_COMPARABLES'] = 5  # we only have 1

            try:
                warnings = controller._validate_step_completion(
                    session, WorkflowStep.COMPARABLE_REVIEW
                )
            finally:
                app.config['MIN_COMPARABLES'] = original

            assert len(warnings) == 1
            assert "1 comparable(s) available" in warnings[0]
            assert "5 recommended" in warnings[0]

    def test_validate_comparable_review_does_not_raise_below_threshold(self, app, controller):
        """The comparable count check must NOT raise ValueError — it's a soft warning."""
        with app.app_context():
            session_id = self._make_session_with_facts(app, controller)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Add one comparable but set threshold to 10
            comparable = ComparableSale(
                session_id=session.id,
                address="456 Oak Ave, Chicago, IL",
                sale_date=datetime(2025, 1, 15).date(),
                sale_price=210000.0,
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.0,
                square_footage=1350,
                lot_size=4000,
                year_built=1950,
                construction_type=ConstructionType.FRAME,
                interior_condition=InteriorCondition.AVERAGE,
                distance_miles=0.3,
            )
            db.session.add(comparable)
            db.session.commit()

            app.config['MIN_COMPARABLES'] = 10
            try:
                # Must not raise — should return a warning list instead
                result = controller._validate_step_completion(
                    session, WorkflowStep.COMPARABLE_REVIEW
                )
                assert isinstance(result, list)
            finally:
                app.config['MIN_COMPARABLES'] = 1

    def test_advance_to_step_includes_warnings_in_response(self, app, controller):
        """advance_to_step threads warnings from _validate_step_completion into the response."""
        from unittest.mock import patch
        from app.services.weighted_scoring_engine import WeightedScoringEngine

        with app.app_context():
            session_id = self._make_session_with_facts(app, controller)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Put session at COMPARABLE_REVIEW step
            session.current_step = WorkflowStep.COMPARABLE_REVIEW
            db.session.commit()

            # Add one comparable
            comparable = ComparableSale(
                session_id=session.id,
                address="456 Oak Ave, Chicago, IL",
                sale_date=datetime(2025, 1, 15).date(),
                sale_price=210000.0,
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.0,
                square_footage=1350,
                lot_size=4000,
                year_built=1950,
                construction_type=ConstructionType.FRAME,
                interior_condition=InteriorCondition.AVERAGE,
                distance_miles=0.3,
            )
            db.session.add(comparable)
            db.session.commit()

            # Raise threshold so we get a warning
            app.config['MIN_COMPARABLES'] = 10

            # Mock the scoring engine so we don't need real data for step execution
            mock_ranked = []
            with patch.object(WeightedScoringEngine, 'rank_comparables', return_value=mock_ranked):
                try:
                    result = controller.advance_to_step(
                        session_id=session_id,
                        target_step=WorkflowStep.WEIGHTED_SCORING,
                    )
                    # Warnings should appear at the top level of the response
                    assert 'warnings' in result
                    assert len(result['warnings']) == 1
                    assert "1 comparable(s) available" in result['warnings'][0]
                    # Warnings should also be in the step result dict
                    assert 'warnings' in result['result']
                except Exception:
                    # If scoring fails for other reasons (no ranked data), that's OK —
                    # the important thing is that the warning path was exercised.
                    # Re-raise only if it's not a scoring-related error.
                    raise
                finally:
                    app.config['MIN_COMPARABLES'] = 1

    def test_advance_to_step_warnings_empty_when_above_threshold(self, app, controller):
        """advance_to_step returns an empty warnings list when comparables meet the threshold."""
        from app.models.comparable_sale import ComparableSale
        from app.models.analysis_session import AnalysisSession, WorkflowStep

        with app.app_context():
            session_id = self._make_session_with_facts(app, controller)

            # Step 2 (COMPARABLE_SEARCH) is now async via Celery/GeminiComparableSearchService.
            # Simulate the Celery task completing by directly setting up session state
            # and inserting a comparable record (as the task would do).
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            session.current_step = WorkflowStep.COMPARABLE_SEARCH
            completed = list(session.completed_steps or [])
            if WorkflowStep.PROPERTY_FACTS.name not in completed:
                completed.append(WorkflowStep.PROPERTY_FACTS.name)
            session.completed_steps = completed
            session.step_results = {
                **(session.step_results or {}),
                'COMPARABLE_SEARCH': {
                    'comparable_count': 1,
                    'narrative': 'Test narrative',
                    'status': 'complete',
                },
            }
            session.loading = False

            comparable = ComparableSale(
                session_id=session.id,
                address='456 Oak Ave, Chicago, IL',
                sale_date=datetime(2025, 1, 15).date(),
                sale_price=210000.0,
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.0,
                square_footage=1350,
                lot_size=4000,
                year_built=1950,
                construction_type=ConstructionType.FRAME,
                interior_condition=InteriorCondition.AVERAGE,
                distance_miles=0.3,
                latitude=41.879,
                longitude=-87.631,
            )
            db.session.add(comparable)
            db.session.commit()

            # Now advance to COMPARABLE_REVIEW (step 2 → 3)
            # MIN_COMPARABLES is 1 in testing, and we have 1 comparable — no warning expected
            review_result = controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.COMPARABLE_REVIEW,
            )
            assert review_result['current_step'] == 'COMPARABLE_REVIEW'
            assert review_result['warnings'] == []


class TestComparableThresholds:
    """Tests for task 3.4: comparable threshold behaviour in dev/test mode and with user config."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_session_at_comparable_review(self, app, controller, user_id="threshold_user"):
        """Create a session that is sitting at the COMPARABLE_REVIEW step."""
        with app.app_context():
            result = controller.start_analysis(
                address="100 Threshold Ave, Chicago, IL",
                user_id=user_id,
            )
            session_id = result["session_id"]
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Confirm property facts
            property_facts = PropertyFacts(
                session_id=session.id,
                address="100 Threshold Ave, Chicago, IL",
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.5,
                square_footage=1400,
                lot_size=4500,
                year_built=1955,
                construction_type=ConstructionType.FRAME,
                basement=True,
                parking_spaces=1,
                assessed_value=180000.0,
                annual_taxes=4200.0,
                zoning="RS-3",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
            )
            db.session.add(property_facts)

            # Move session to COMPARABLE_REVIEW
            session.current_step = WorkflowStep.COMPARABLE_REVIEW
            db.session.commit()
            return session_id

    def _add_comparables(self, app, session_id, count):
        """Add *count* ComparableSale rows to the session."""
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            for i in range(count):
                comp = ComparableSale(
                    session_id=session.id,
                    address=f"{200 + i} Comp St, Chicago, IL",
                    sale_date=datetime(2025, 1, 15).date(),
                    sale_price=200000.0 + i * 1000,
                    property_type=PropertyType.SINGLE_FAMILY,
                    units=1,
                    bedrooms=3,
                    bathrooms=1.0,
                    square_footage=1350,
                    lot_size=4000,
                    year_built=1950,
                    construction_type=ConstructionType.FRAME,
                    interior_condition=InteriorCondition.AVERAGE,
                    distance_miles=0.3 + i * 0.1,
                )
                db.session.add(comp)
            db.session.commit()

    # ------------------------------------------------------------------
    # Test 1: Advancement allowed with fewer than 10 comparables in dev/test mode
    # ------------------------------------------------------------------

    def test_advance_allowed_with_fewer_than_10_comparables_in_test_mode(self, app, controller):
        """In test mode (MIN_COMPARABLES=1), advancing with 1 comparable must succeed.

        The test config sets MIN_COMPARABLES=1, so a single comparable should
        be enough to advance from COMPARABLE_REVIEW without raising an error.
        No user ScoringWeights record exists, so the app-level config is used.
        """
        from unittest.mock import patch
        from app.services.weighted_scoring_engine import WeightedScoringEngine

        with app.app_context():
            # Confirm the test config is in effect
            assert app.config["MIN_COMPARABLES"] == 1, (
                "This test requires MIN_COMPARABLES=1 (testing config)"
            )

            session_id = self._make_session_at_comparable_review(app, controller)
            self._add_comparables(app, session_id, 1)  # only 1 comparable

            # Mock scoring engine so we don't need real ranked data
            with patch.object(WeightedScoringEngine, "rank_comparables", return_value=[]):
                result = controller.advance_to_step(
                    session_id=session_id,
                    target_step=WorkflowStep.WEIGHTED_SCORING,
                )

            # Advancement must succeed — no ValueError raised
            assert result["current_step"] == WorkflowStep.WEIGHTED_SCORING.name
            # With 1 comparable meeting the threshold of 1, no warnings expected
            assert result["warnings"] == []

    # ------------------------------------------------------------------
    # Test 2: Warnings returned when below user-configured threshold
    # ------------------------------------------------------------------

    def test_warnings_returned_when_below_user_configured_threshold(self, app, controller):
        """When ScoringWeights.min_comparables=5 and only 3 comparables exist, a warning is returned.

        The warning must appear in both the top-level 'warnings' key and
        inside 'result' of the advance_to_step response.
        """
        from unittest.mock import patch
        from app.services.weighted_scoring_engine import WeightedScoringEngine

        user_id = "user_with_custom_min"

        with app.app_context():
            # Create a ScoringWeights record with min_comparables=5
            weights = ScoringWeights(
                user_id=user_id,
                property_characteristics_weight=0.30,
                data_completeness_weight=0.20,
                owner_situation_weight=0.30,
                location_desirability_weight=0.20,
                min_comparables=5,
            )
            db.session.add(weights)
            db.session.commit()

            session_id = self._make_session_at_comparable_review(
                app, controller, user_id=user_id
            )
            self._add_comparables(app, session_id, 3)  # 3 < 5 → should warn

            with patch.object(WeightedScoringEngine, "rank_comparables", return_value=[]):
                result = controller.advance_to_step(
                    session_id=session_id,
                    target_step=WorkflowStep.WEIGHTED_SCORING,
                )

            # A warning must be present
            assert len(result["warnings"]) == 1
            warning_text = result["warnings"][0]
            assert "3 comparable(s) available" in warning_text
            assert "5 recommended" in warning_text

            # Warning must also be threaded into the step result
            assert "warnings" in result["result"]
            assert len(result["result"]["warnings"]) == 1

    # ------------------------------------------------------------------
    # Test 3: User-configured minimum respected (both sides of the threshold)
    # ------------------------------------------------------------------

    def test_user_configured_minimum_no_warning_when_met(self, app, controller):
        """When ScoringWeights.min_comparables=3 and exactly 3 comparables exist, no warning."""
        from unittest.mock import patch
        from app.services.weighted_scoring_engine import WeightedScoringEngine

        user_id = "user_min3_met"

        with app.app_context():
            weights = ScoringWeights(
                user_id=user_id,
                property_characteristics_weight=0.30,
                data_completeness_weight=0.20,
                owner_situation_weight=0.30,
                location_desirability_weight=0.20,
                min_comparables=3,
            )
            db.session.add(weights)
            db.session.commit()

            session_id = self._make_session_at_comparable_review(
                app, controller, user_id=user_id
            )
            self._add_comparables(app, session_id, 3)  # exactly 3 — threshold met

            with patch.object(WeightedScoringEngine, "rank_comparables", return_value=[]):
                result = controller.advance_to_step(
                    session_id=session_id,
                    target_step=WorkflowStep.WEIGHTED_SCORING,
                )

            # No warnings — threshold is exactly met
            assert result["warnings"] == []

    def test_user_configured_minimum_warning_when_below(self, app, controller):
        """When ScoringWeights.min_comparables=3 and only 2 comparables exist, a warning is returned."""
        from unittest.mock import patch
        from app.services.weighted_scoring_engine import WeightedScoringEngine

        user_id = "user_min3_below"

        with app.app_context():
            weights = ScoringWeights(
                user_id=user_id,
                property_characteristics_weight=0.30,
                data_completeness_weight=0.20,
                owner_situation_weight=0.30,
                location_desirability_weight=0.20,
                min_comparables=3,
            )
            db.session.add(weights)
            db.session.commit()

            session_id = self._make_session_at_comparable_review(
                app, controller, user_id=user_id
            )
            self._add_comparables(app, session_id, 2)  # 2 < 3 → should warn

            with patch.object(WeightedScoringEngine, "rank_comparables", return_value=[]):
                result = controller.advance_to_step(
                    session_id=session_id,
                    target_step=WorkflowStep.WEIGHTED_SCORING,
                )

            assert len(result["warnings"]) == 1
            warning_text = result["warnings"][0]
            assert "2 comparable(s) available" in warning_text
            assert "3 recommended" in warning_text


class TestExecuteWeightedScoringEndToEnd:
    """Task 4.4 — end-to-end tests for _execute_weighted_scoring.

    Verifies that:
    - Ranked comparables are saved to the DB after the method runs.
    - The saved records have the correct field values (attribute access, not dict access).
    - The method returns the expected summary dict.
    - Re-running the method replaces existing ranked comparables (idempotent).
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_session_with_facts_and_comparables(self, app, controller, n_comps=3):
        """Create a session with confirmed property facts and *n_comps* comparable sales."""
        with app.app_context():
            result = controller.start_analysis(
                address="500 Scoring Ave, Chicago, IL",
                user_id="scoring_user",
            )
            session_id = result["session_id"]
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Confirmed property facts
            facts = PropertyFacts(
                session_id=session.id,
                address="500 Scoring Ave, Chicago, IL",
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
                assessed_value=400000.0,
                annual_taxes=8000.0,
                zoning="R-4",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
            )
            db.session.add(facts)

            # Comparable sales
            for i in range(n_comps):
                comp = ComparableSale(
                    session_id=session.id,
                    address=f"{600 + i} Comp Blvd, Chicago, IL",
                    sale_date=datetime(2024, 6 - i, 15).date(),
                    sale_price=380000.0 + i * 5000,
                    property_type=PropertyType.MULTI_FAMILY,
                    units=4,
                    bedrooms=8,
                    bathrooms=4.0,
                    square_footage=3100 + i * 50,
                    lot_size=4800,
                    year_built=1922,
                    construction_type=ConstructionType.BRICK,
                    interior_condition=InteriorCondition.AVERAGE,
                    distance_miles=0.2 + i * 0.15,
                )
                db.session.add(comp)

            db.session.commit()
            return session_id

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_ranked_comparables_saved_to_db(self, app, controller):
        """_execute_weighted_scoring persists RankedComparable rows to the database."""
        with app.app_context():
            session_id = self._make_session_with_facts_and_comparables(app, controller, n_comps=3)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            controller._execute_weighted_scoring(session)

            saved = RankedComparable.query.filter_by(session_id=session.id).all()
            assert len(saved) == 3

    def test_ranked_comparables_have_correct_fields(self, app, controller):
        """Saved RankedComparable records have valid scores and sequential ranks."""
        with app.app_context():
            session_id = self._make_session_with_facts_and_comparables(app, controller, n_comps=3)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            controller._execute_weighted_scoring(session)

            saved = (
                RankedComparable.query
                .filter_by(session_id=session.id)
                .order_by(RankedComparable.rank)
                .all()
            )

            # Ranks are sequential starting from 1
            assert [r.rank for r in saved] == [1, 2, 3]

            for record in saved:
                # All scores are in the valid 0–100 range
                assert 0 <= record.total_score <= 100
                assert 0 <= record.recency_score <= 100
                assert 0 <= record.proximity_score <= 100
                assert 0 <= record.units_score <= 100
                assert 0 <= record.beds_baths_score <= 100
                assert 0 <= record.sqft_score <= 100
                assert 0 <= record.construction_score <= 100
                assert 0 <= record.interior_score <= 100

                # comparable_id must reference an existing ComparableSale
                assert record.comparable_id is not None
                assert record.comparable is not None

    def test_ranked_comparables_sorted_by_score_descending(self, app, controller):
        """Saved RankedComparable records are ordered by total_score descending."""
        with app.app_context():
            session_id = self._make_session_with_facts_and_comparables(app, controller, n_comps=3)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            controller._execute_weighted_scoring(session)

            saved = (
                RankedComparable.query
                .filter_by(session_id=session.id)
                .order_by(RankedComparable.rank)
                .all()
            )

            scores = [r.total_score for r in saved]
            assert scores == sorted(scores, reverse=True), (
                f"Scores should be descending by rank, got: {scores}"
            )

    def test_execute_weighted_scoring_returns_summary_dict(self, app, controller):
        """_execute_weighted_scoring returns the expected summary dictionary."""
        with app.app_context():
            session_id = self._make_session_with_facts_and_comparables(app, controller, n_comps=2)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            result = controller._execute_weighted_scoring(session)

            assert result["status"] == "complete"
            assert result["ranked_count"] == 2
            assert result["top_score"] is not None
            assert 0 <= result["top_score"] <= 100

    def test_execute_weighted_scoring_is_idempotent(self, app, controller):
        """Running _execute_weighted_scoring twice replaces, not duplicates, ranked records."""
        with app.app_context():
            session_id = self._make_session_with_facts_and_comparables(app, controller, n_comps=3)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            controller._execute_weighted_scoring(session)
            controller._execute_weighted_scoring(session)  # run again

            saved = RankedComparable.query.filter_by(session_id=session.id).all()
            # Should still be exactly 3, not 6
            assert len(saved) == 3

    def test_execute_weighted_scoring_via_advance_to_step(self, app, controller):
        """advance_to_step(WEIGHTED_SCORING) saves ranked comparables end-to-end."""
        with app.app_context():
            session_id = self._make_session_with_facts_and_comparables(app, controller, n_comps=2)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Move session to COMPARABLE_REVIEW (the step before WEIGHTED_SCORING)
            session.current_step = WorkflowStep.COMPARABLE_REVIEW
            db.session.commit()

            result = controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            assert result["current_step"] == WorkflowStep.WEIGHTED_SCORING.name
            assert result["result"]["status"] == "complete"
            assert result["result"]["ranked_count"] == 2

            # Verify records are in the DB
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            saved = RankedComparable.query.filter_by(session_id=session.id).all()
            assert len(saved) == 2


class TestExecuteValuationModels:
    """Task 5 — tests for _execute_valuation_models with adaptive comparables."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_session_with_ranked_comps(self, app, controller, n_ranked=3):
        """Create a session with property facts and *n_ranked* RankedComparable rows."""
        with app.app_context():
            result = controller.start_analysis(
                address="700 Valuation Blvd, Chicago, IL",
                user_id="valuation_user",
            )
            session_id = result["session_id"]
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Confirmed property facts
            facts = PropertyFacts(
                session_id=session.id,
                address="700 Valuation Blvd, Chicago, IL",
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
                assessed_value=400000.0,
                annual_taxes=8000.0,
                zoning="R-4",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
            )
            db.session.add(facts)

            # Comparable sales (needed for the FK on RankedComparable)
            for i in range(n_ranked):
                comp = ComparableSale(
                    session_id=session.id,
                    address=f"{800 + i} Comp Ln, Chicago, IL",
                    sale_date=datetime(2024, 6, 15).date(),
                    sale_price=390000.0 + i * 5000,
                    property_type=PropertyType.MULTI_FAMILY,
                    units=4,
                    bedrooms=8,
                    bathrooms=4.0,
                    square_footage=3100,
                    lot_size=4800,
                    year_built=1922,
                    construction_type=ConstructionType.BRICK,
                    interior_condition=InteriorCondition.AVERAGE,
                    distance_miles=0.2 + i * 0.1,
                )
                db.session.add(comp)
            db.session.flush()

            # Ranked comparables
            comps = ComparableSale.query.filter_by(session_id=session.id).all()
            for idx, comp in enumerate(comps):
                ranked = RankedComparable(
                    session_id=session.id,
                    comparable_id=comp.id,
                    total_score=90.0 - idx * 2,
                    rank=idx + 1,
                    recency_score=85.0,
                    proximity_score=80.0,
                    units_score=100.0,
                    beds_baths_score=100.0,
                    sqft_score=95.0,
                    construction_score=100.0,
                    interior_score=100.0,
                )
                db.session.add(ranked)

            db.session.commit()
            return session_id

    # ------------------------------------------------------------------
    # 5.1 — No hard block; succeeds with fewer than 5 comparables
    # ------------------------------------------------------------------

    def test_valuation_succeeds_with_1_ranked_comparable(self, app, controller):
        """_execute_valuation_models succeeds with only 1 ranked comparable."""
        with app.app_context():
            session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=1)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            result = controller._execute_valuation_models(session)

            assert result["status"] == "complete"
            assert result["arv_range"]["conservative"] > 0
            assert result["arv_range"]["likely"] > 0
            assert result["arv_range"]["aggressive"] > 0

    def test_valuation_succeeds_with_3_ranked_comparables(self, app, controller):
        """_execute_valuation_models succeeds with 3 ranked comparables."""
        with app.app_context():
            session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=3)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            result = controller._execute_valuation_models(session)

            assert result["status"] == "complete"
            arv = result["arv_range"]
            assert arv["conservative"] <= arv["likely"] <= arv["aggressive"]

    def test_valuation_raises_when_no_ranked_comparables(self, app, controller):
        """_execute_valuation_models raises ValueError when there are no ranked comparables at all."""
        with app.app_context():
            session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=0)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            with pytest.raises(ValueError, match="At least 1 ranked comparable"):
                controller._execute_valuation_models(session)

    # ------------------------------------------------------------------
    # 5.1 — Warnings returned when below MIN_VALUATION_COMPARABLES
    # ------------------------------------------------------------------

    def test_warnings_returned_when_below_min_valuation_comparables(self, app, controller):
        """A warning is included in the result when fewer than MIN_VALUATION_COMPARABLES are used."""
        with app.app_context():
            # In testing config MIN_VALUATION_COMPARABLES=1, so raise it temporarily
            original = app.config["MIN_VALUATION_COMPARABLES"]
            app.config["MIN_VALUATION_COMPARABLES"] = 5

            try:
                session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=2)
                session = AnalysisSession.query.filter_by(session_id=session_id).first()

                result = controller._execute_valuation_models(session)
            finally:
                app.config["MIN_VALUATION_COMPARABLES"] = original

            assert "warnings" in result
            assert len(result["warnings"]) == 1
            warning_text = result["warnings"][0]
            assert "2 ranked comparable(s) available" in warning_text
            assert "5 recommended" in warning_text

    def test_no_warnings_when_at_or_above_threshold(self, app, controller):
        """No warnings when the number of ranked comparables meets MIN_VALUATION_COMPARABLES."""
        with app.app_context():
            # MIN_VALUATION_COMPARABLES=1 in testing; use 1 comparable → no warning
            assert app.config["MIN_VALUATION_COMPARABLES"] == 1
            session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=1)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            result = controller._execute_valuation_models(session)

            assert "warnings" not in result or result.get("warnings") == []

    # ------------------------------------------------------------------
    # 5.2 — Confidence score in result
    # ------------------------------------------------------------------

    def test_confidence_score_present_in_step_result(self, app, controller):
        """_execute_valuation_models includes confidence_score in the step result."""
        with app.app_context():
            session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=3)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            result = controller._execute_valuation_models(session)

            assert "confidence_score" in result
            assert result["confidence_score"] is not None
            assert 0.0 <= result["confidence_score"] <= 100.0

    def test_confidence_score_lower_with_fewer_comparables(self, app, controller):
        """Confidence score is lower when fewer ranked comparables are used."""
        with app.app_context():
            session_id_5 = self._make_session_with_ranked_comps(app, controller, n_ranked=5)
            session_5 = AnalysisSession.query.filter_by(session_id=session_id_5).first()
            result_5 = controller._execute_valuation_models(session_5)

            session_id_1 = self._make_session_with_ranked_comps(app, controller, n_ranked=1)
            session_1 = AnalysisSession.query.filter_by(session_id=session_id_1).first()
            result_1 = controller._execute_valuation_models(session_1)

            assert result_5["confidence_score"] > result_1["confidence_score"]

    def test_confidence_score_persisted_on_valuation_result(self, app, controller):
        """confidence_score is persisted on the ValuationResult ORM record."""
        with app.app_context():
            session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=3)
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            controller._execute_valuation_models(session)

            # Reload from DB
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.valuation_result is not None
            assert session.valuation_result.confidence_score is not None
            assert 0.0 <= session.valuation_result.confidence_score <= 100.0

    # ------------------------------------------------------------------
    # 5.2 — ARV range is wider when confidence is lower
    # ------------------------------------------------------------------

    def test_arv_range_wider_with_fewer_comparables(self, app, controller):
        """ARV range (aggressive - conservative) is wider when fewer comparables are used."""
        with app.app_context():
            session_id_5 = self._make_session_with_ranked_comps(app, controller, n_ranked=5)
            session_5 = AnalysisSession.query.filter_by(session_id=session_id_5).first()
            result_5 = controller._execute_valuation_models(session_5)

            session_id_1 = self._make_session_with_ranked_comps(app, controller, n_ranked=1)
            session_1 = AnalysisSession.query.filter_by(session_id=session_id_1).first()
            result_1 = controller._execute_valuation_models(session_1)

            range_5 = result_5["arv_range"]["aggressive"] - result_5["arv_range"]["conservative"]
            range_1 = result_1["arv_range"]["aggressive"] - result_1["arv_range"]["conservative"]

            assert range_1 > range_5, (
                f"Expected wider range with 1 comp ({range_1:.0f}) than with 5 comps ({range_5:.0f})"
            )

    # ------------------------------------------------------------------
    # 5.3 — MIN_VALUATION_COMPARABLES config is used
    # ------------------------------------------------------------------

    def test_min_valuation_comparables_config_controls_warning_threshold(self, app, controller):
        """MIN_VALUATION_COMPARABLES config value controls when warnings are emitted."""
        with app.app_context():
            # With threshold=3 and 2 comps → warning
            app.config["MIN_VALUATION_COMPARABLES"] = 3
            try:
                session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=2)
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                result = controller._execute_valuation_models(session)
                assert "warnings" in result
                assert "2 ranked comparable(s) available" in result["warnings"][0]
                assert "3 recommended" in result["warnings"][0]
            finally:
                app.config["MIN_VALUATION_COMPARABLES"] = 1

    def test_min_valuation_comparables_no_warning_when_met(self, app, controller):
        """No warning when ranked comparable count equals MIN_VALUATION_COMPARABLES."""
        with app.app_context():
            app.config["MIN_VALUATION_COMPARABLES"] = 3
            try:
                session_id = self._make_session_with_ranked_comps(app, controller, n_ranked=3)
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                result = controller._execute_valuation_models(session)
                assert "warnings" not in result or result.get("warnings") == []
            finally:
                app.config["MIN_VALUATION_COMPARABLES"] = 1


class TestStep3To4Transition:
    """Task 6.1 — regression tests for the step 3→4 (COMPARABLE_REVIEW → WEIGHTED_SCORING) transition.

    Verifies that:
    - The transition succeeds after weighted scoring runs (Task 4 fix in place).
    - completed_steps is updated correctly after each step (Task 6.2).
    - step_results contains the correct result for each completed step (Task 6.3).
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_session_at_comparable_review_with_comps(self, app, controller, n_comps=2):
        """Create a session at COMPARABLE_REVIEW with property facts and comparable sales."""
        with app.app_context():
            result = controller.start_analysis(
                address="900 Transition Ave, Chicago, IL",
                user_id="transition_user",
            )
            session_id = result["session_id"]
            session = AnalysisSession.query.filter_by(session_id=session_id).first()

            # Confirmed property facts
            facts = PropertyFacts(
                session_id=session.id,
                address="900 Transition Ave, Chicago, IL",
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
                assessed_value=400000.0,
                annual_taxes=8000.0,
                zoning="R-4",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
            )
            db.session.add(facts)

            # Comparable sales
            for i in range(n_comps):
                comp = ComparableSale(
                    session_id=session.id,
                    address=f"{1000 + i} Comp Way, Chicago, IL",
                    sale_date=datetime(2024, 6, 15).date(),
                    sale_price=380000.0 + i * 5000,
                    property_type=PropertyType.MULTI_FAMILY,
                    units=4,
                    bedrooms=8,
                    bathrooms=4.0,
                    square_footage=3100,
                    lot_size=4800,
                    year_built=1922,
                    construction_type=ConstructionType.BRICK,
                    interior_condition=InteriorCondition.AVERAGE,
                    distance_miles=0.2 + i * 0.1,
                )
                db.session.add(comp)

            session.current_step = WorkflowStep.COMPARABLE_REVIEW
            db.session.commit()
            return session_id

    # ------------------------------------------------------------------
    # 6.1 — Step 3→4 transition succeeds after Task 4 fix
    # ------------------------------------------------------------------

    def test_step_3_to_4_transition_succeeds(self, app, controller):
        """advance_to_step(WEIGHTED_SCORING) succeeds and saves ranked comparables."""
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=2)

            result = controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            assert result["current_step"] == WorkflowStep.WEIGHTED_SCORING.name
            assert result["result"]["status"] == "complete"
            assert result["result"]["ranked_count"] == 2

            # Ranked comparables must be persisted
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            saved = RankedComparable.query.filter_by(session_id=session.id).all()
            assert len(saved) == 2

    def test_step_3_to_4_ranked_comparables_queryable_after_advance(self, app, controller):
        """session.ranked_comparables.all() returns saved records after WEIGHTED_SCORING step."""
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=3)

            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            ranked = session.ranked_comparables.all()
            assert len(ranked) == 3
            # All records have valid ranks
            assert sorted(r.rank for r in ranked) == [1, 2, 3]

    # ------------------------------------------------------------------
    # 6.2 — completed_steps updated correctly after each step
    # ------------------------------------------------------------------

    def test_completed_steps_updated_after_advance(self, app, controller):
        """completed_steps contains the previous step name after advance_to_step."""
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=2)

            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            # COMPARABLE_REVIEW was the step being completed when we advanced to WEIGHTED_SCORING
            assert "COMPARABLE_REVIEW" in session.completed_steps

    def test_completed_steps_accumulates_across_multiple_advances(self, app, controller):
        """completed_steps accumulates step names as the workflow progresses."""
        with app.app_context():
            result = controller.start_analysis(
                address="950 Multi Step Rd, Chicago, IL",
                user_id="multi_step_user",
            )
            session_id = result["session_id"]

            # Confirm property facts so validation passes for step 1 → 2
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            facts = PropertyFacts(
                session_id=session.id,
                address="950 Multi Step Rd, Chicago, IL",
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
                assessed_value=400000.0,
                annual_taxes=8000.0,
                zoning="R-4",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
            )
            db.session.add(facts)
            db.session.commit()

            # Step 1 → 2: COMPARABLE_SEARCH is now async via Celery/GeminiComparableSearchService.
            # Simulate the Celery task completing by directly setting session state.
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            session.current_step = WorkflowStep.COMPARABLE_SEARCH
            completed = list(session.completed_steps or [])
            if WorkflowStep.PROPERTY_FACTS.name not in completed:
                completed.append(WorkflowStep.PROPERTY_FACTS.name)
            session.completed_steps = completed
            session.step_results = {
                **(session.step_results or {}),
                'COMPARABLE_SEARCH': {'comparable_count': 1, 'narrative': '', 'status': 'complete'},
            }
            session.loading = False
            comparable = ComparableSale(
                session_id=session.id,
                address='456 Oak Ave, Chicago, IL',
                sale_date=datetime(2025, 1, 15).date(),
                sale_price=210000.0,
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.0,
                square_footage=1350,
                lot_size=4000,
                year_built=1950,
                construction_type=ConstructionType.FRAME,
                interior_condition=InteriorCondition.AVERAGE,
                distance_miles=0.3,
                latitude=41.879,
                longitude=-87.631,
            )
            db.session.add(comparable)
            db.session.commit()

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert "PROPERTY_FACTS" in session.completed_steps

            # Step 2 → 3: advance to COMPARABLE_REVIEW
            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.COMPARABLE_REVIEW,
            )

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert "PROPERTY_FACTS" in session.completed_steps
            assert "COMPARABLE_SEARCH" in session.completed_steps

    def test_completed_steps_no_duplicates(self, app, controller):
        """completed_steps does not accumulate duplicate entries."""
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=2)

            # Advance once
            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            completed = session.completed_steps
            # No duplicates
            assert len(completed) == len(set(completed))

    def test_completed_steps_present_in_session_state(self, app, controller):
        """get_session_state exposes completed_steps."""
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=2)

            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            state = controller.get_session_state(session_id)
            assert "completed_steps" in state
            assert "COMPARABLE_REVIEW" in state["completed_steps"]

    # ------------------------------------------------------------------
    # 6.3 — step_results contains the correct result for each completed step
    # ------------------------------------------------------------------

    def test_step_results_populated_after_advance(self, app, controller):
        """step_results contains the WEIGHTED_SCORING result after advancing to that step."""
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=2)

            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert "WEIGHTED_SCORING" in session.step_results
            step_result = session.step_results["WEIGHTED_SCORING"]
            assert step_result["status"] == "complete"
            assert step_result["ranked_count"] == 2

    def test_step_results_accumulates_across_multiple_advances(self, app, controller):
        """step_results accumulates entries as the workflow progresses."""
        with app.app_context():
            result = controller.start_analysis(
                address="975 Results Blvd, Chicago, IL",
                user_id="results_user",
            )
            session_id = result["session_id"]

            # Confirm property facts so validation passes for step 1 → 2
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            facts = PropertyFacts(
                session_id=session.id,
                address="975 Results Blvd, Chicago, IL",
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
                assessed_value=400000.0,
                annual_taxes=8000.0,
                zoning="R-4",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
            )
            db.session.add(facts)
            db.session.commit()

            # Step 1 → 2: COMPARABLE_SEARCH is now async via Celery/GeminiComparableSearchService.
            # Simulate the Celery task completing by directly setting session state.
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            session.current_step = WorkflowStep.COMPARABLE_SEARCH
            completed = list(session.completed_steps or [])
            if WorkflowStep.PROPERTY_FACTS.name not in completed:
                completed.append(WorkflowStep.PROPERTY_FACTS.name)
            session.completed_steps = completed
            session.step_results = {
                **(session.step_results or {}),
                'COMPARABLE_SEARCH': {'comparable_count': 1, 'narrative': '', 'status': 'complete'},
            }
            session.loading = False
            comparable = ComparableSale(
                session_id=session.id,
                address='456 Oak Ave, Chicago, IL',
                sale_date=datetime(2025, 1, 15).date(),
                sale_price=210000.0,
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.0,
                square_footage=1350,
                lot_size=4000,
                year_built=1950,
                construction_type=ConstructionType.FRAME,
                interior_condition=InteriorCondition.AVERAGE,
                distance_miles=0.3,
                latitude=41.879,
                longitude=-87.631,
            )
            db.session.add(comparable)
            db.session.commit()

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert "COMPARABLE_SEARCH" in session.step_results
            assert session.step_results["COMPARABLE_SEARCH"]["status"] == "complete"

            # Step 2 → 3
            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.COMPARABLE_REVIEW,
            )

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert "COMPARABLE_SEARCH" in session.step_results
            assert "COMPARABLE_REVIEW" in session.step_results
            assert session.step_results["COMPARABLE_REVIEW"]["status"] == "ready_for_review"

    def test_step_results_present_in_session_state(self, app, controller):
        """get_session_state exposes step_results."""
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=2)

            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            state = controller.get_session_state(session_id)
            assert "step_results" in state
            assert "WEIGHTED_SCORING" in state["step_results"]

    # ------------------------------------------------------------------
    # 6.2 — completed_steps as secondary validation signal
    # ------------------------------------------------------------------

    def test_completed_steps_allows_advance_even_if_child_records_deleted(self, app, controller):
        """If completed_steps records a step, validation passes even if child records are gone.

        This tests the secondary-signal behaviour: once a step is recorded in
        completed_steps, the hard-error child-record check is bypassed.
        """
        with app.app_context():
            session_id = self._make_session_at_comparable_review_with_comps(app, controller, n_comps=2)

            # Advance to WEIGHTED_SCORING (records COMPARABLE_REVIEW in completed_steps)
            controller.advance_to_step(
                session_id=session_id,
                target_step=WorkflowStep.WEIGHTED_SCORING,
            )

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert "COMPARABLE_REVIEW" in session.completed_steps

            # Now delete all ranked comparables to simulate an edge case
            RankedComparable.query.filter_by(session_id=session.id).delete()
            db.session.commit()

            # _validate_step_completion for WEIGHTED_SCORING should NOT raise because
            # WEIGHTED_SCORING is in completed_steps
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            # Manually mark session as being at WEIGHTED_SCORING step
            session.current_step = WorkflowStep.WEIGHTED_SCORING
            # Manually add WEIGHTED_SCORING to completed_steps
            completed = list(session.completed_steps or [])
            if "WEIGHTED_SCORING" not in completed:
                completed.append("WEIGHTED_SCORING")
            session.completed_steps = completed
            db.session.commit()

            # Validation should pass (no ValueError) because completed_steps has the entry
            warnings = controller._validate_step_completion(session, WorkflowStep.WEIGHTED_SCORING)
            assert isinstance(warnings, list)  # no exception raised
