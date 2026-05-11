"""Valuation Engine for generating property valuations using top comparables."""
from typing import List, Tuple
import statistics
from app.models.property_facts import PropertyFacts, ConstructionType, InteriorCondition, PropertyType
from app.models.comparable_sale import ComparableSale
from app.models.ranked_comparable import RankedComparable
from app.models.valuation_result import ValuationResult, ComparableValuation

# Full-confidence comparable count — at or above this number the confidence
# score is driven entirely by recency and proximity quality.
_FULL_CONFIDENCE_COMP_COUNT = 5


class ValuationEngine:
    """
    Generates valuation models using top 5 ranked comparables with adjustments.
    
    Calculates four valuation methods per comparable:
    - Residential: Price per square foot, price per unit, price per bedroom, adjusted valuation
    - Commercial: Price per square foot, income capitalization, price per unit, adjusted valuation
    
    Computes ARV range (conservative, likely, aggressive) from all valuations.
    """
    
    # Residential adjustment factors (in dollars)
    RESIDENTIAL_ADJUSTMENT_FACTORS = {
        'unit_difference': 15000,  # per unit
        'bedroom_difference': 5000,  # per bedroom
        'bathroom_difference': 3000,  # per bathroom
        'sqft_difference': 50,  # per square foot
        'construction_upgrade': 10000,  # brick vs frame
        'interior_condition': {
            'needs_gut_to_poor': -20000,
            'poor_to_average': -10000,
            'average_to_new': 15000,
            'new_to_high_end': 25000,
        },
        'basement': 8000,
        'parking': 5000,  # per space
    }
    
    # Commercial adjustment factors (in dollars)
    COMMERCIAL_ADJUSTMENT_FACTORS = {
        'unit_difference': 25000,  # per unit (higher for commercial)
        'sqft_difference': 75,  # per square foot (higher for commercial)
        'construction_upgrade': 20000,  # brick vs frame (higher for commercial)
        'interior_condition': {
            'needs_gut_to_poor': -30000,
            'poor_to_average': -15000,
            'average_to_new': 25000,
            'new_to_high_end': 40000,
        },
        'parking': 10000,  # per space (higher for commercial)
    }
    
    # Interior condition ordering for adjustment calculation
    INTERIOR_CONDITION_ORDER = {
        InteriorCondition.NEEDS_GUT: 0,
        InteriorCondition.POOR: 1,
        InteriorCondition.AVERAGE: 2,
        InteriorCondition.NEW_RENO: 3,
        InteriorCondition.HIGH_END: 4,
    }
    
    def _get_adjustment_factors(self, property_type: PropertyType) -> dict:
        """
        Get adjustment factors based on property type.
        
        Args:
            property_type: Property type (residential or commercial)
            
        Returns:
            Dictionary of adjustment factors
        """
        if property_type == PropertyType.COMMERCIAL:
            return self.COMMERCIAL_ADJUSTMENT_FACTORS
        else:
            return self.RESIDENTIAL_ADJUSTMENT_FACTORS
    
    def _is_residential(self, property_type: PropertyType) -> bool:
        """
        Check if property type is residential.
        
        Args:
            property_type: Property type
            
        Returns:
            True if residential, False otherwise
        """
        return property_type in [PropertyType.SINGLE_FAMILY, PropertyType.MULTI_FAMILY]
    
    def calculate_price_per_sqft(self, comparable: ComparableSale, subject: PropertyFacts) -> float:
        """
        Calculate price per square foot valuation.
        
        Args:
            comparable: Comparable sale
            subject: Subject property
            
        Returns:
            Estimated value based on price per square foot
        """
        if comparable.square_footage == 0:
            return 0.0
        
        price_per_sqft = comparable.sale_price / comparable.square_footage
        estimated_value = price_per_sqft * subject.square_footage
        return estimated_value
    
    def calculate_price_per_unit(self, comparable: ComparableSale, subject: PropertyFacts) -> float:
        """
        Calculate price per unit valuation.
        
        Args:
            comparable: Comparable sale
            subject: Subject property
            
        Returns:
            Estimated value based on price per unit
        """
        if comparable.units == 0:
            return 0.0
        
        price_per_unit = comparable.sale_price / comparable.units
        estimated_value = price_per_unit * subject.units
        return estimated_value
    
    def calculate_price_per_bedroom(self, comparable: ComparableSale, subject: PropertyFacts) -> float:
        """
        Calculate price per bedroom valuation.
        
        Args:
            comparable: Comparable sale
            subject: Subject property
            
        Returns:
            Estimated value based on price per bedroom
        """
        if comparable.bedrooms == 0:
            return 0.0
        
        price_per_bedroom = comparable.sale_price / comparable.bedrooms
        estimated_value = price_per_bedroom * subject.bedrooms
        return estimated_value
    
    def calculate_income_capitalization(
        self, 
        comparable: ComparableSale, 
        subject: PropertyFacts,
        market_cap_rate: float = 0.08
    ) -> float:
        """
        Calculate income capitalization valuation for commercial properties.
        
        Uses the formula: Value = Net Operating Income / Cap Rate
        Estimates NOI based on comparable's sale price and market cap rate.
        
        Args:
            comparable: Comparable sale
            subject: Subject property
            market_cap_rate: Market capitalization rate (default 8%)
            
        Returns:
            Estimated value based on income capitalization approach
        """
        # Estimate comparable's NOI from its sale price
        comp_noi = comparable.sale_price * market_cap_rate
        
        # Adjust NOI for subject property based on size difference
        if comparable.square_footage > 0:
            noi_per_sqft = comp_noi / comparable.square_footage
            subject_noi = noi_per_sqft * subject.square_footage
        else:
            subject_noi = comp_noi
        
        # Calculate subject value using income capitalization
        estimated_value = subject_noi / market_cap_rate
        return estimated_value
    
    def calculate_interior_adjustment(
        self,
        subject_interior: InteriorCondition,
        comp_interior: InteriorCondition,
        property_type: PropertyType
    ) -> Tuple[float, str]:
        """
        Calculate adjustment for interior condition difference.
        
        Args:
            subject_interior: Subject property interior condition
            comp_interior: Comparable interior condition
            property_type: Property type for selecting adjustment factors
            
        Returns:
            Tuple of (adjustment_amount, explanation)
        """
        adjustment_factors = self._get_adjustment_factors(property_type)
        subject_level = self.INTERIOR_CONDITION_ORDER[subject_interior]
        comp_level = self.INTERIOR_CONDITION_ORDER[comp_interior]
        
        level_diff = subject_level - comp_level
        
        if level_diff == 0:
            return 0.0, "No interior condition adjustment needed"
        
        # Calculate adjustment based on level differences
        adjustment = 0.0
        explanation_parts = []
        
        if level_diff > 0:
            # Subject is better than comp - add value
            for i in range(comp_level, subject_level):
                from_condition = list(self.INTERIOR_CONDITION_ORDER.keys())[i]
                to_condition = list(self.INTERIOR_CONDITION_ORDER.keys())[i + 1]
                
                key = f"{from_condition.value}_to_{to_condition.value}"
                adj_value = adjustment_factors['interior_condition'].get(key, 0)
                adjustment += adj_value
                explanation_parts.append(f"{from_condition.value} to {to_condition.value}: +${adj_value:,.0f}")
        else:
            # Subject is worse than comp - subtract value
            for i in range(subject_level, comp_level):
                from_condition = list(self.INTERIOR_CONDITION_ORDER.keys())[i]
                to_condition = list(self.INTERIOR_CONDITION_ORDER.keys())[i + 1]
                
                key = f"{from_condition.value}_to_{to_condition.value}"
                adj_value = adjustment_factors['interior_condition'].get(key, 0)
                adjustment -= adj_value
                explanation_parts.append(f"{to_condition.value} to {from_condition.value}: -${abs(adj_value):,.0f}")
        
        explanation = "Interior condition: " + ", ".join(explanation_parts)
        return adjustment, explanation
    
    def calculate_adjusted_value(
        self,
        subject: PropertyFacts,
        comparable: ComparableSale
    ) -> Tuple[float, List[dict]]:
        """
        Calculate adjusted valuation with adjustment factors.
        
        Args:
            subject: Subject property
            comparable: Comparable sale
            
        Returns:
            Tuple of (adjusted_value, list_of_adjustments)
        """
        adjustment_factors = self._get_adjustment_factors(subject.property_type)
        is_residential = self._is_residential(subject.property_type)
        
        base_value = comparable.sale_price
        adjustments = []
        total_adjustment = 0.0
        
        # Unit difference adjustment
        unit_diff = subject.units - comparable.units
        if unit_diff != 0:
            unit_adjustment = unit_diff * adjustment_factors['unit_difference']
            total_adjustment += unit_adjustment
            adjustments.append({
                'category': 'units',
                'difference': unit_diff,
                'adjustment_amount': unit_adjustment,
                'explanation': f"Unit difference ({subject.units} vs {comparable.units}): {'+' if unit_adjustment >= 0 else ''}${unit_adjustment:,.0f}"
            })
        
        # Bedroom difference adjustment (residential only)
        if is_residential and 'bedroom_difference' in adjustment_factors:
            bed_diff = subject.bedrooms - comparable.bedrooms
            if bed_diff != 0:
                bed_adjustment = bed_diff * adjustment_factors['bedroom_difference']
                total_adjustment += bed_adjustment
                adjustments.append({
                    'category': 'bedrooms',
                    'difference': bed_diff,
                    'adjustment_amount': bed_adjustment,
                    'explanation': f"Bedroom difference ({subject.bedrooms} vs {comparable.bedrooms}): {'+' if bed_adjustment >= 0 else ''}${bed_adjustment:,.0f}"
                })
        
        # Bathroom difference adjustment (residential only)
        if is_residential and 'bathroom_difference' in adjustment_factors:
            bath_diff = subject.bathrooms - comparable.bathrooms
            if bath_diff != 0:
                bath_adjustment = bath_diff * adjustment_factors['bathroom_difference']
                total_adjustment += bath_adjustment
                adjustments.append({
                    'category': 'bathrooms',
                    'difference': bath_diff,
                    'adjustment_amount': bath_adjustment,
                    'explanation': f"Bathroom difference ({subject.bathrooms} vs {comparable.bathrooms}): {'+' if bath_adjustment >= 0 else ''}${bath_adjustment:,.0f}"
                })
        
        # Square footage difference adjustment
        sqft_diff = subject.square_footage - comparable.square_footage
        if sqft_diff != 0:
            sqft_adjustment = sqft_diff * adjustment_factors['sqft_difference']
            total_adjustment += sqft_adjustment
            adjustments.append({
                'category': 'square_footage',
                'difference': sqft_diff,
                'adjustment_amount': sqft_adjustment,
                'explanation': f"Square footage difference ({subject.square_footage:,} vs {comparable.square_footage:,}): {'+' if sqft_adjustment >= 0 else ''}${sqft_adjustment:,.0f}"
            })
        
        # Construction type adjustment
        if subject.construction_type != comparable.construction_type:
            # Simplified: brick/masonry is better than frame
            construction_adjustment = 0.0
            if subject.construction_type in [ConstructionType.BRICK, ConstructionType.MASONRY] and \
               comparable.construction_type == ConstructionType.FRAME:
                construction_adjustment = adjustment_factors['construction_upgrade']
            elif subject.construction_type == ConstructionType.FRAME and \
                 comparable.construction_type in [ConstructionType.BRICK, ConstructionType.MASONRY]:
                construction_adjustment = -adjustment_factors['construction_upgrade']
            
            if construction_adjustment != 0:
                total_adjustment += construction_adjustment
                adjustments.append({
                    'category': 'construction',
                    'difference': f"{subject.construction_type.value} vs {comparable.construction_type.value}",
                    'adjustment_amount': construction_adjustment,
                    'explanation': f"Construction type ({subject.construction_type.value} vs {comparable.construction_type.value}): {'+' if construction_adjustment >= 0 else ''}${construction_adjustment:,.0f}"
                })
        
        # Interior condition adjustment
        interior_adjustment, interior_explanation = self.calculate_interior_adjustment(
            subject.interior_condition, comparable.interior_condition, subject.property_type
        )
        if interior_adjustment != 0:
            total_adjustment += interior_adjustment
            adjustments.append({
                'category': 'interior',
                'difference': f"{subject.interior_condition.value} vs {comparable.interior_condition.value}",
                'adjustment_amount': interior_adjustment,
                'explanation': interior_explanation
            })
        
        # Basement adjustment (residential only, if available)
        if is_residential and 'basement' in adjustment_factors and hasattr(comparable, 'basement'):
            if subject.basement and not comparable.basement:
                basement_adjustment = adjustment_factors['basement']
                total_adjustment += basement_adjustment
                adjustments.append({
                    'category': 'basement',
                    'difference': 'Subject has basement, comp does not',
                    'adjustment_amount': basement_adjustment,
                    'explanation': f"Basement: +${basement_adjustment:,.0f}"
                })
            elif not subject.basement and comparable.basement:
                basement_adjustment = -adjustment_factors['basement']
                total_adjustment += basement_adjustment
                adjustments.append({
                    'category': 'basement',
                    'difference': 'Comp has basement, subject does not',
                    'adjustment_amount': basement_adjustment,
                    'explanation': f"Basement: -${abs(basement_adjustment):,.0f}"
                })
        
        # Parking adjustment (if available)
        if hasattr(comparable, 'parking_spaces'):
            parking_diff = subject.parking_spaces - comparable.parking_spaces
            if parking_diff != 0:
                parking_adjustment = parking_diff * adjustment_factors['parking']
                total_adjustment += parking_adjustment
                adjustments.append({
                    'category': 'parking',
                    'difference': parking_diff,
                    'adjustment_amount': parking_adjustment,
                    'explanation': f"Parking spaces ({subject.parking_spaces} vs {comparable.parking_spaces}): {'+' if parking_adjustment >= 0 else ''}${parking_adjustment:,.0f}"
                })
        
        adjusted_value = base_value + total_adjustment
        return adjusted_value, adjustments
    
    def generate_narrative(
        self,
        comparable: ComparableSale,
        adjustments: List[dict],
        adjusted_value: float
    ) -> str:
        """
        Generate narrative summary for comparable valuation.
        
        Args:
            comparable: Comparable sale
            adjustments: List of adjustment dictionaries
            adjusted_value: Final adjusted value
            
        Returns:
            Narrative string explaining the valuation
        """
        narrative_parts = [
            f"Comparable at {comparable.address} sold for ${comparable.sale_price:,.0f} on {comparable.sale_date}."
        ]
        
        if adjustments:
            narrative_parts.append("Adjustments applied:")
            for adj in adjustments:
                narrative_parts.append(f"  - {adj['explanation']}")
            
            total_adj = sum(adj['adjustment_amount'] for adj in adjustments)
            narrative_parts.append(f"Total adjustments: {'+' if total_adj >= 0 else ''}${total_adj:,.0f}")
        else:
            narrative_parts.append("No adjustments needed - properties are very similar.")
        
        narrative_parts.append(f"Adjusted value: ${adjusted_value:,.0f}")
        
        return "\n".join(narrative_parts)
    
    def compute_arv_range(self, all_valuations: List[float]) -> Tuple[float, float, float]:
        """
        Calculate ARV range (conservative, likely, aggressive) from all valuations.
        
        Args:
            all_valuations: List of all valuation estimates
            
        Returns:
            Tuple of (conservative_arv, likely_arv, aggressive_arv)
        """
        if not all_valuations:
            return 0.0, 0.0, 0.0
        
        sorted_vals = sorted(all_valuations)
        
        # Conservative: 25th percentile
        conservative = statistics.quantiles(sorted_vals, n=4)[0] if len(sorted_vals) >= 4 else sorted_vals[0]
        
        # Likely: median (50th percentile)
        likely = statistics.median(sorted_vals)
        
        # Aggressive: 75th percentile
        aggressive = statistics.quantiles(sorted_vals, n=4)[2] if len(sorted_vals) >= 4 else sorted_vals[-1]
        
        return conservative, likely, aggressive

    def compute_confidence_score(
        self,
        comp_count: int,
        avg_recency_score: float,
        avg_proximity_score: float,
    ) -> float:
        """Compute a 0–100 confidence score for a valuation.

        The score is the product of three independent factors:

        1. **Count factor** (0–1): scales linearly from 0 at 0 comparables to
           1.0 at ``_FULL_CONFIDENCE_COMP_COUNT`` (5).  Having fewer than 5
           comparables proportionally reduces confidence.

        2. **Recency factor** (0–1): the average recency score of the
           comparables used, normalised to [0, 1].

        3. **Proximity factor** (0–1): the average proximity score of the
           comparables used, normalised to [0, 1].

        The three factors are multiplied together and scaled to [0, 100].

        Args:
            comp_count: Number of comparables actually used (≥ 1).
            avg_recency_score: Average recency score across used comparables (0–100).
            avg_proximity_score: Average proximity score across used comparables (0–100).

        Returns:
            Confidence score in the range [0, 100].
        """
        if comp_count <= 0:
            return 0.0

        count_factor = min(comp_count / _FULL_CONFIDENCE_COMP_COUNT, 1.0)
        recency_factor = max(0.0, min(avg_recency_score / 100.0, 1.0))
        proximity_factor = max(0.0, min(avg_proximity_score / 100.0, 1.0))

        raw = count_factor * recency_factor * proximity_factor
        return round(raw * 100.0, 2)

    def apply_confidence_widening(
        self,
        conservative: float,
        likely: float,
        aggressive: float,
        confidence_score: float,
    ) -> Tuple[float, float, float]:
        """Widen the ARV range proportionally when confidence is below 100.

        When confidence is 100 the range is unchanged.  As confidence falls
        toward 0 the conservative end decreases and the aggressive end
        increases, reflecting greater uncertainty.  The likely (median) value
        is never changed.

        The maximum widening at confidence = 0 is ±20 % of the likely ARV.

        Args:
            conservative: Conservative ARV estimate.
            likely: Likely (median) ARV estimate.
            aggressive: Aggressive ARV estimate.
            confidence_score: Confidence score in [0, 100].

        Returns:
            Tuple of (adjusted_conservative, likely, adjusted_aggressive).
        """
        if likely <= 0:
            return conservative, likely, aggressive

        # Fraction of maximum widening to apply (0 at full confidence, 1 at zero confidence)
        uncertainty = 1.0 - max(0.0, min(confidence_score / 100.0, 1.0))

        # Maximum widening: 20 % of the likely ARV
        max_widen = likely * 0.20

        widen_amount = uncertainty * max_widen

        adjusted_conservative = conservative - widen_amount
        adjusted_aggressive = aggressive + widen_amount

        return adjusted_conservative, likely, adjusted_aggressive
    
    def calculate_valuations(
        self,
        subject: PropertyFacts,
        top_comparables: List[RankedComparable],
        session_id: int
    ) -> ValuationResult:
        """
        Generate valuation models using up to 5 ranked comparables.

        Accepts 1–5 comparables (uses whatever is available).  When fewer than
        5 are provided the confidence score is reduced proportionally and the
        ARV range is widened to reflect the greater uncertainty.

        Selects valuation methods based on property type:
        - Residential: price per sqft, price per unit, price per bedroom, adjusted value
        - Commercial: price per sqft, income capitalization, price per unit, adjusted value
        
        Args:
            subject: Subject property facts
            top_comparables: List of ranked comparables (1–5 used)
            session_id: Analysis session ID
            
        Returns:
            ValuationResult with ARV range, confidence score, and comparable valuations
        """
        # Take up to 5 comparables — whatever is available (minimum 1)
        top_5 = top_comparables[:5]
        
        is_residential = self._is_residential(subject.property_type)
        
        all_valuations = []
        comparable_valuations = []

        # Accumulate scores for confidence calculation
        recency_scores: List[float] = []
        proximity_scores: List[float] = []
        
        for ranked_comp in top_5:
            comp = ranked_comp.comparable

            # Collect scores for confidence calculation (use 50 as neutral default
            # when the ranked comparable doesn't carry individual scores)
            recency_scores.append(getattr(ranked_comp, 'recency_score', 50.0) or 50.0)
            proximity_scores.append(getattr(ranked_comp, 'proximity_score', 50.0) or 50.0)
            
            # Calculate valuation methods based on property type
            price_per_sqft_val = self.calculate_price_per_sqft(comp, subject)
            price_per_unit_val = self.calculate_price_per_unit(comp, subject)
            adjusted_value, adjustments = self.calculate_adjusted_value(subject, comp)
            
            if is_residential:
                # Residential: use price per bedroom
                price_per_bedroom_val = self.calculate_price_per_bedroom(comp, subject)
                all_valuations.extend([
                    price_per_sqft_val,
                    price_per_unit_val,
                    price_per_bedroom_val,
                    adjusted_value
                ])
            else:
                # Commercial: use income capitalization
                income_cap_val = self.calculate_income_capitalization(comp, subject)
                all_valuations.extend([
                    price_per_sqft_val,
                    income_cap_val,
                    price_per_unit_val,
                    adjusted_value
                ])
                price_per_bedroom_val = income_cap_val  # Store income cap in bedroom field for commercial
            
            # Generate narrative
            narrative = self.generate_narrative(comp, adjustments, adjusted_value)
            
            # Create ComparableValuation object
            comp_valuation = ComparableValuation(
                comparable_id=comp.id,
                price_per_sqft=price_per_sqft_val,
                price_per_unit=price_per_unit_val,
                price_per_bedroom=price_per_bedroom_val,
                adjusted_value=adjusted_value,
                adjustments=adjustments,
                narrative=narrative
            )
            comparable_valuations.append(comp_valuation)
        
        # Compute base ARV range from all valuation estimates
        conservative, likely, aggressive = self.compute_arv_range(all_valuations)

        # Compute confidence score
        avg_recency = statistics.mean(recency_scores) if recency_scores else 50.0
        avg_proximity = statistics.mean(proximity_scores) if proximity_scores else 50.0
        confidence_score = self.compute_confidence_score(
            comp_count=len(top_5),
            avg_recency_score=avg_recency,
            avg_proximity_score=avg_proximity,
        )

        # Widen ARV range when confidence is below 100
        conservative, likely, aggressive = self.apply_confidence_widening(
            conservative, likely, aggressive, confidence_score
        )
        
        # Generate key drivers (simplified - can be enhanced)
        key_drivers = [
            f"Based on {len(top_5)} top-ranked comparable sales",
            f"Average sale price: ${statistics.mean([c.comparable.sale_price for c in top_5]):,.0f}",
            f"Price range: ${min([c.comparable.sale_price for c in top_5]):,.0f} - ${max([c.comparable.sale_price for c in top_5]):,.0f}",
            f"Confidence score: {confidence_score:.0f}/100",
        ]
        
        # Create ValuationResult
        valuation_result = ValuationResult(
            session_id=session_id,
            conservative_arv=conservative,
            likely_arv=likely,
            aggressive_arv=aggressive,
            all_valuations=all_valuations,
            key_drivers=key_drivers,
            confidence_score=confidence_score,
        )
        
        # Associate comparable valuations
        for comp_val in comparable_valuations:
            comp_val.valuation_result = valuation_result
        
        return valuation_result
