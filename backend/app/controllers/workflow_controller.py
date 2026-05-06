"""Workflow Controller for orchestrating the 6-step analysis workflow."""
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
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
from app.services.property_data_service import PropertyDataService
from app.services.comparable_sales_finder import ComparableSalesFinder
from app.services.weighted_scoring_engine import WeightedScoringEngine
from app.services.valuation_engine import ValuationEngine
from app.services.scenario_analysis_engine import ScenarioAnalysisEngine
from app.services.report_generator import ReportGenerator


class WorkflowController:
    """Orchestrates the 6-step analysis workflow and manages state transitions."""
    
    def __init__(self):
        """Initialize workflow controller with service dependencies."""
        self.property_service = PropertyDataService()
        self.comparable_finder = ComparableSalesFinder()
        self.scoring_engine = WeightedScoringEngine()
        self.valuation_engine = ValuationEngine()
        self.scenario_engine = ScenarioAnalysisEngine()
        self.report_generator = ReportGenerator()
    
    def start_analysis(self, address: str, user_id: str) -> Dict[str, Any]:
        """
        Initialize new analysis session with property address.

        Attempts to pre-populate property facts from the Cook County Assessor
        API.  If the lookup fails or returns no data the session is still
        created and ``property_facts`` in the response will be ``None`` so the
        frontend can show an empty form for manual entry.

        Args:
            address: Property address to analyze
            user_id: User identifier

        Returns:
            Dictionary containing session_id, initial state, and optional
            property_facts populated from the Cook County Assessor API.
        """
        session_id = str(uuid.uuid4())

        session = AnalysisSession(
            session_id=session_id,
            user_id=user_id,
            current_step=WorkflowStep.PROPERTY_FACTS,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(session)
        db.session.commit()

        # Attempt to fetch real property data; never let errors bubble up
        serialized_facts = None
        try:
            facts_data = self.property_service.fetch_property_facts(address)
            if facts_data and facts_data.get('address'):
                # Return the raw data to the frontend for review — do NOT
                # persist to DB here. The PropertyFacts record is created
                # correctly when the user confirms via PUT /step/1.
                serialized_facts = facts_data
        except Exception as exc:
            print(f"Property data fetch error for {address!r}: {exc}")

        return {
            'session_id': session_id,
            'user_id': user_id,
            'current_step': WorkflowStep.PROPERTY_FACTS.name,
            'created_at': session.created_at.isoformat(),
            'status': 'initialized',
            'property_facts': serialized_facts,
        }

    def _create_property_facts_from_data(
        self, session: AnalysisSession, data: Dict[str, Any]
    ) -> Optional['PropertyFacts']:
        """
        Persist a PropertyFacts record from raw API data.

        Only creates the record when at least one meaningful field was
        returned.  Returns None (without raising) if the data is empty or
        a required enum value is missing.
        """
        # Require at minimum an address
        address = data.get('address')
        if not address:
            return None

        # Resolve enums with safe fallbacks
        try:
            prop_type_raw = data.get('property_type') or 'SINGLE_FAMILY'
            # Try by name first (e.g. 'SINGLE_FAMILY'), then by value (e.g. 'single_family')
            try:
                property_type = PropertyType[prop_type_raw]
            except KeyError:
                property_type = PropertyType(prop_type_raw)
        except (ValueError, KeyError):
            property_type = PropertyType.SINGLE_FAMILY

        try:
            constr_raw = data.get('construction_type') or 'FRAME'
            try:
                construction_type = ConstructionType[constr_raw]
            except KeyError:
                construction_type = ConstructionType(constr_raw)
        except (ValueError, KeyError):
            construction_type = ConstructionType.FRAME

        try:
            property_facts = PropertyFacts(
                session_id=session.id,
                address=address,
                property_type=property_type,
                units=data.get('units') or 1,
                bedrooms=data.get('bedrooms') or 0,
                bathrooms=data.get('bathrooms') or 0.0,
                square_footage=data.get('square_footage') or 0,
                lot_size=data.get('lot_size') or 0,
                year_built=data.get('year_built') or 0,
                construction_type=construction_type,
                basement=data.get('basement', False),
                parking_spaces=data.get('parking_spaces', 0),
                assessed_value=data.get('assessed_value') or 0.0,
                annual_taxes=data.get('annual_taxes') or 0.0,
                zoning=data.get('zoning') or '',
                interior_condition=InteriorCondition.AVERAGE,
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                data_source=data.get('data_source', 'cook_county_assessor'),
                user_modified_fields=data.get('user_modified_fields', []),
            )
            db.session.add(property_facts)
            db.session.commit()
            return property_facts
        except Exception as exc:
            db.session.rollback()
            print(f"PropertyFacts creation error: {exc}")
            return None
    
    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """
        Retrieve current workflow state for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary containing complete session state
            
        Raises:
            ValueError: If session not found
        """
        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        state = {
            'session_id': session.session_id,
            'user_id': session.user_id,
            'current_step': session.current_step.name,
            'created_at': session.created_at.isoformat(),
            'updated_at': session.updated_at.isoformat(),
        }
        
        # Add subject property if available
        if session.subject_property:
            state['subject_property'] = self._serialize_property_facts(session.subject_property)
        
        # Add comparables if available
        comparables = session.comparables.all()
        if comparables:
            state['comparables'] = [self._serialize_comparable(c) for c in comparables]
            state['comparable_count'] = len(comparables)
        
        # Add ranked comparables if available
        ranked = session.ranked_comparables.all()
        if ranked:
            state['ranked_comparables'] = [self._serialize_ranked_comparable(r) for r in ranked]
        
        # Add valuation result if available
        if session.valuation_result:
            state['valuation_result'] = self._serialize_valuation_result(session.valuation_result)
        
        # Add scenarios if available
        scenarios = session.scenarios.all()
        if scenarios:
            state['scenarios'] = [self._serialize_scenario(s) for s in scenarios]
        
        return state
    
    def advance_to_step(self, session_id: str, target_step: WorkflowStep, approval_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Validate current step completion and advance to next step.
        
        Args:
            session_id: Session identifier
            target_step: Target workflow step to advance to
            approval_data: Optional data confirming step completion
            
        Returns:
            Dictionary containing updated session state and step results
            
        Raises:
            ValueError: If session not found or validation fails
        """
        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        # Validate step progression (can only advance one step at a time)
        current_step_value = session.current_step.value
        target_step_value = target_step.value
        
        if target_step_value != current_step_value + 1:
            raise ValueError(
                f"Cannot advance from step {session.current_step.name} to {target_step.name}. "
                f"Must advance sequentially."
            )
        
        # Validate current step is complete before advancing
        self._validate_step_completion(session, session.current_step)
        
        # Execute step-specific logic
        result = self._execute_step(session, target_step, approval_data)
        
        # Update session state
        session.current_step = target_step
        session.updated_at = datetime.utcnow()
        db.session.commit()
        
        return {
            'session_id': session_id,
            'current_step': target_step.name,
            'previous_step': WorkflowStep(current_step_value).name,
            'result': result,
            'updated_at': session.updated_at.isoformat()
        }
    
    def update_step_data(self, session_id: str, step: WorkflowStep, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle user modifications to step data and trigger recalculation.
        
        Args:
            session_id: Session identifier
            step: Workflow step being modified
            data: Updated data for the step
            
        Returns:
            Dictionary containing updated data and recalculation results
            
        Raises:
            ValueError: If session not found or data validation fails
        """
        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        # Validate data based on step
        self._validate_step_data(step, data)
        
        # Update data based on step
        result = self._update_step_data_internal(session, step, data)
        
        # Trigger recalculation cascade for downstream steps
        recalculation_results = self._recalculate_downstream(session, step)
        
        # Update session timestamp
        session.updated_at = datetime.utcnow()
        db.session.commit()
        
        return {
            'session_id': session_id,
            'step': step.name,
            'updated_data': result,
            'recalculations': recalculation_results,
            'updated_at': session.updated_at.isoformat()
        }
    
    def go_back_to_step(self, session_id: str, target_step: WorkflowStep) -> Dict[str, Any]:
        """
        Navigate backward to a previous step while preserving data.
        
        Args:
            session_id: Session identifier
            target_step: Target workflow step to return to
            
        Returns:
            Dictionary containing session state at target step
            
        Raises:
            ValueError: If session not found or invalid step
        """
        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        # Validate backward navigation
        if target_step.value >= session.current_step.value:
            raise ValueError(
                f"Cannot go back from step {session.current_step.name} to {target_step.name}. "
                f"Target step must be earlier in the workflow."
            )
        
        # Update current step
        previous_step = session.current_step
        session.current_step = target_step
        session.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Return current state at target step
        state = self.get_session_state(session_id)
        state['previous_step'] = previous_step.name
        state['navigation'] = 'backward'
        
        return state
    
    # Private helper methods
    
    def _validate_step_completion(self, session: AnalysisSession, step: WorkflowStep) -> None:
        """Validate that current step is complete before advancing."""
        if step == WorkflowStep.PROPERTY_FACTS:
            if not session.subject_property:
                raise ValueError("Property facts must be retrieved and confirmed before advancing")
        
        elif step == WorkflowStep.COMPARABLE_SEARCH:
            comparables = session.comparables.all()
            if not comparables:
                raise ValueError("Comparable sales must be found before advancing")
        
        elif step == WorkflowStep.COMPARABLE_REVIEW:
            comparables = session.comparables.all()
            if len(comparables) < 10:
                raise ValueError("At least 10 comparables required before advancing")
        
        elif step == WorkflowStep.WEIGHTED_SCORING:
            ranked = session.ranked_comparables.all()
            if not ranked:
                raise ValueError("Comparables must be scored and ranked before advancing")
        
        elif step == WorkflowStep.VALUATION_MODELS:
            if not session.valuation_result:
                raise ValueError("Valuation models must be calculated before advancing")
    
    def _execute_step(self, session: AnalysisSession, step: WorkflowStep, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Execute step-specific logic when advancing to a new step."""
        if step == WorkflowStep.COMPARABLE_SEARCH:
            return self._execute_comparable_search(session)
        
        elif step == WorkflowStep.COMPARABLE_REVIEW:
            # No automatic execution, user reviews manually
            return {'status': 'ready_for_review'}
        
        elif step == WorkflowStep.WEIGHTED_SCORING:
            return self._execute_weighted_scoring(session)
        
        elif step == WorkflowStep.VALUATION_MODELS:
            return self._execute_valuation_models(session)
        
        elif step == WorkflowStep.REPORT_GENERATION:
            return self._execute_report_generation(session)
        
        return {}

    
    def _execute_comparable_search(self, session: AnalysisSession) -> Dict[str, Any]:
        """Execute comparable sales search."""
        if not session.subject_property:
            raise ValueError("Subject property required for comparable search")
        
        # Find comparables
        comparables_data = self.comparable_finder.find_comparables(
            subject=session.subject_property,
            min_count=10,
            max_age_months=12
        )
        
        # Save comparables to database
        for comp_data in comparables_data:
            comparable = ComparableSale(
                session_id=session.id,
                address=comp_data['address'],
                sale_date=comp_data['sale_date'],
                sale_price=comp_data['sale_price'],
                property_type=comp_data['property_type'],
                units=comp_data['units'],
                bedrooms=comp_data['bedrooms'],
                bathrooms=comp_data['bathrooms'],
                square_footage=comp_data['square_footage'],
                lot_size=comp_data['lot_size'],
                year_built=comp_data['year_built'],
                construction_type=comp_data['construction_type'],
                interior_condition=comp_data['interior_condition'],
                distance_miles=comp_data['distance_miles'],
                latitude=comp_data.get('latitude'),
                longitude=comp_data.get('longitude')
            )
            db.session.add(comparable)
        
        db.session.commit()
        
        return {
            'comparable_count': len(comparables_data),
            'search_radius': comparables_data[0].get('search_radius') if comparables_data else None,
            'status': 'complete'
        }
    
    def _execute_weighted_scoring(self, session: AnalysisSession) -> Dict[str, Any]:
        """Execute weighted scoring and ranking."""
        if not session.subject_property:
            raise ValueError("Subject property required for scoring")
        
        comparables = session.comparables.all()
        if not comparables:
            raise ValueError("Comparables required for scoring")
        
        # Clear existing ranked comparables
        RankedComparable.query.filter_by(session_id=session.id).delete()
        
        # Calculate scores and rank
        ranked_data = self.scoring_engine.rank_comparables(
            subject=session.subject_property,
            comparables=comparables
        )
        
        # Save ranked comparables
        for rank_data in ranked_data:
            ranked = RankedComparable(
                session_id=session.id,
                comparable_id=rank_data['comparable_id'],
                total_score=rank_data['total_score'],
                rank=rank_data['rank'],
                recency_score=rank_data['score_breakdown']['recency_score'],
                proximity_score=rank_data['score_breakdown']['proximity_score'],
                units_score=rank_data['score_breakdown']['units_score'],
                beds_baths_score=rank_data['score_breakdown']['beds_baths_score'],
                sqft_score=rank_data['score_breakdown']['sqft_score'],
                construction_score=rank_data['score_breakdown']['construction_score'],
                interior_score=rank_data['score_breakdown']['interior_score']
            )
            db.session.add(ranked)
        
        db.session.commit()
        
        return {
            'ranked_count': len(ranked_data),
            'top_score': ranked_data[0]['total_score'] if ranked_data else None,
            'status': 'complete'
        }
    
    def _execute_valuation_models(self, session: AnalysisSession) -> Dict[str, Any]:
        """Execute valuation model calculations."""
        if not session.subject_property:
            raise ValueError("Subject property required for valuation")
        
        ranked = session.ranked_comparables.order_by(RankedComparable.rank).limit(5).all()
        if len(ranked) < 5:
            raise ValueError("At least 5 ranked comparables required for valuation")
        
        # Clear existing valuation result
        if session.valuation_result:
            db.session.delete(session.valuation_result)
            db.session.flush()
        
        # Calculate valuations - returns ValuationResult object
        valuation_result = self.valuation_engine.calculate_valuations(
            subject=session.subject_property,
            top_comparables=ranked,
            session_id=session.id
        )
        
        # Add to session
        db.session.add(valuation_result)
        db.session.commit()
        
        return {
            'arv_range': {
                'conservative': valuation_result.conservative_arv,
                'likely': valuation_result.likely_arv,
                'aggressive': valuation_result.aggressive_arv
            },
            'comparable_valuations_count': len(valuation_result.comparable_valuations.all()),
            'status': 'complete'
        }
    
    def _execute_report_generation(self, session: AnalysisSession) -> Dict[str, Any]:
        """Execute report generation."""
        # Generate report using report generator
        report = self.report_generator.generate_report(session)
        
        return {
            'report_sections': list(report.keys()),
            'status': 'complete'
        }
    
    def _validate_step_data(self, step: WorkflowStep, data: Dict[str, Any]) -> None:
        """Validate data for a specific step."""
        if step == WorkflowStep.PROPERTY_FACTS:
            required_fields = [
                'address', 'property_type', 'units', 'bedrooms', 'bathrooms',
                'square_footage', 'lot_size', 'year_built', 'construction_type',
                'assessed_value', 'annual_taxes', 'zoning', 'interior_condition'
            ]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Validate numeric ranges
            if data['units'] < 1:
                raise ValueError("Units must be at least 1")
            if data['bedrooms'] < 0:
                raise ValueError("Bedrooms cannot be negative")
            if data['bathrooms'] < 0:
                raise ValueError("Bathrooms cannot be negative")
            if data['square_footage'] < 1:
                raise ValueError("Square footage must be positive")
            if data['year_built'] < 1800 or data['year_built'] > datetime.now().year:
                raise ValueError(f"Year built must be between 1800 and {datetime.now().year}")
    
    def _update_step_data_internal(self, session: AnalysisSession, step: WorkflowStep, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update data for a specific step."""
        if step == WorkflowStep.PROPERTY_FACTS:
            return self._update_property_facts(session, data)
        
        elif step == WorkflowStep.COMPARABLE_REVIEW:
            return self._update_comparables(session, data)
        
        return {}
    
    def _update_property_facts(self, session: AnalysisSession, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update property facts data."""
        if not session.subject_property:
            # Create new property facts
            property_facts = PropertyFacts(
                session_id=session.id,
                address=data['address'],
                property_type=PropertyType[data['property_type']],
                units=data['units'],
                bedrooms=data['bedrooms'],
                bathrooms=data['bathrooms'],
                square_footage=data['square_footage'],
                lot_size=data['lot_size'],
                year_built=data['year_built'],
                construction_type=ConstructionType[data['construction_type']],
                basement=data.get('basement', False),
                parking_spaces=data.get('parking_spaces', 0),
                last_sale_price=data.get('last_sale_price'),
                last_sale_date=data.get('last_sale_date'),
                assessed_value=data['assessed_value'],
                annual_taxes=data['annual_taxes'],
                zoning=data['zoning'],
                interior_condition=InteriorCondition[data['interior_condition']],
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                data_source=data.get('data_source'),
                user_modified_fields=data.get('user_modified_fields', [])
            )
            db.session.add(property_facts)
        else:
            # Update existing property facts
            property_facts = session.subject_property
            modified_fields = property_facts.user_modified_fields or []
            
            for field, value in data.items():
                if hasattr(property_facts, field):
                    old_value = getattr(property_facts, field)
                    if old_value != value:
                        setattr(property_facts, field, value)
                        if field not in modified_fields:
                            modified_fields.append(field)
            
            property_facts.user_modified_fields = modified_fields
        
        db.session.commit()
        
        return self._serialize_property_facts(property_facts)
    
    def _update_comparables(self, session: AnalysisSession, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update comparables data (add or remove)."""
        action = data.get('action')
        
        if action == 'remove':
            comparable_id = data.get('comparable_id')
            comparable = ComparableSale.query.filter_by(
                id=comparable_id,
                session_id=session.id
            ).first()
            
            if comparable:
                db.session.delete(comparable)
                db.session.commit()
                return {'action': 'removed', 'comparable_id': comparable_id}
        
        elif action == 'add':
            # Add new comparable
            comparable = ComparableSale(
                session_id=session.id,
                address=data['address'],
                sale_date=data['sale_date'],
                sale_price=data['sale_price'],
                property_type=PropertyType[data['property_type']],
                units=data['units'],
                bedrooms=data['bedrooms'],
                bathrooms=data['bathrooms'],
                square_footage=data['square_footage'],
                lot_size=data['lot_size'],
                year_built=data['year_built'],
                construction_type=ConstructionType[data['construction_type']],
                interior_condition=InteriorCondition[data['interior_condition']],
                distance_miles=data['distance_miles'],
                latitude=data.get('latitude'),
                longitude=data.get('longitude')
            )
            db.session.add(comparable)
            db.session.commit()
            
            return {'action': 'added', 'comparable_id': comparable.id}
        
        return {}
    
    def _recalculate_downstream(self, session: AnalysisSession, modified_step: WorkflowStep) -> List[Dict[str, Any]]:
        """Trigger recalculation cascade for downstream steps."""
        results = []
        
        # If property facts modified, recalculate everything
        if modified_step == WorkflowStep.PROPERTY_FACTS:
            # Clear and recalculate comparables if they exist
            if session.comparables.count() > 0:
                results.append(self._execute_comparable_search(session))
            
            # Clear and recalculate scoring if it exists
            if session.ranked_comparables.count() > 0:
                results.append(self._execute_weighted_scoring(session))
            
            # Clear and recalculate valuation if it exists
            if session.valuation_result:
                results.append(self._execute_valuation_models(session))
        
        # If comparables modified, recalculate scoring and valuation
        elif modified_step == WorkflowStep.COMPARABLE_REVIEW:
            if session.ranked_comparables.count() > 0:
                results.append(self._execute_weighted_scoring(session))
            
            if session.valuation_result:
                results.append(self._execute_valuation_models(session))
        
        # If scoring modified, recalculate valuation
        elif modified_step == WorkflowStep.WEIGHTED_SCORING:
            if session.valuation_result:
                results.append(self._execute_valuation_models(session))
        
        return results
    
    # Serialization helpers
    
    def _serialize_property_facts(self, property_facts: PropertyFacts) -> Dict[str, Any]:
        """Serialize PropertyFacts to dictionary."""
        return {
            'id': property_facts.id,
            'address': property_facts.address,
            'property_type': property_facts.property_type.name,
            'units': property_facts.units,
            'bedrooms': property_facts.bedrooms,
            'bathrooms': property_facts.bathrooms,
            'square_footage': property_facts.square_footage,
            'lot_size': property_facts.lot_size,
            'year_built': property_facts.year_built,
            'construction_type': property_facts.construction_type.name,
            'basement': property_facts.basement,
            'parking_spaces': property_facts.parking_spaces,
            'last_sale_price': property_facts.last_sale_price,
            'last_sale_date': property_facts.last_sale_date.isoformat() if property_facts.last_sale_date else None,
            'assessed_value': property_facts.assessed_value,
            'annual_taxes': property_facts.annual_taxes,
            'zoning': property_facts.zoning,
            'interior_condition': property_facts.interior_condition.name,
            'latitude': property_facts.latitude,
            'longitude': property_facts.longitude,
            'data_source': property_facts.data_source,
            'user_modified_fields': property_facts.user_modified_fields or []
        }
    
    def _serialize_comparable(self, comparable: ComparableSale) -> Dict[str, Any]:
        """Serialize ComparableSale to dictionary."""
        return {
            'id': comparable.id,
            'address': comparable.address,
            'sale_date': comparable.sale_date.isoformat() if comparable.sale_date else None,
            'sale_price': comparable.sale_price,
            'property_type': comparable.property_type.name,
            'units': comparable.units,
            'bedrooms': comparable.bedrooms,
            'bathrooms': comparable.bathrooms,
            'square_footage': comparable.square_footage,
            'lot_size': comparable.lot_size,
            'year_built': comparable.year_built,
            'construction_type': comparable.construction_type.name,
            'interior_condition': comparable.interior_condition.name,
            'distance_miles': comparable.distance_miles,
            'latitude': comparable.latitude,
            'longitude': comparable.longitude
        }
    
    def _serialize_ranked_comparable(self, ranked: RankedComparable) -> Dict[str, Any]:
        """Serialize RankedComparable to dictionary."""
        return {
            'id': ranked.id,
            'comparable': self._serialize_comparable(ranked.comparable),
            'total_score': ranked.total_score,
            'rank': ranked.rank,
            'score_breakdown': {
                'recency_score': ranked.recency_score,
                'proximity_score': ranked.proximity_score,
                'units_score': ranked.units_score,
                'beds_baths_score': ranked.beds_baths_score,
                'sqft_score': ranked.sqft_score,
                'construction_score': ranked.construction_score,
                'interior_score': ranked.interior_score
            }
        }
    
    def _serialize_valuation_result(self, valuation: ValuationResult) -> Dict[str, Any]:
        """Serialize ValuationResult to dictionary."""
        return {
            'id': valuation.id,
            'conservative_arv': valuation.conservative_arv,
            'likely_arv': valuation.likely_arv,
            'aggressive_arv': valuation.aggressive_arv,
            'all_valuations': valuation.all_valuations,
            'key_drivers': valuation.key_drivers
        }
    
    def _serialize_scenario(self, scenario) -> Dict[str, Any]:
        """Serialize Scenario to dictionary."""
        # Basic scenario data
        data = {
            'id': scenario.id,
            'scenario_type': scenario.scenario_type.name,
            'purchase_price': scenario.purchase_price
        }
        
        # Add type-specific data
        if hasattr(scenario, 'mao'):
            data['mao'] = scenario.mao
            data['contract_price'] = scenario.contract_price
            data['assignment_fee_low'] = scenario.assignment_fee_low
            data['assignment_fee_high'] = scenario.assignment_fee_high
        
        return data
