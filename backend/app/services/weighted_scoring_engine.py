"""Weighted Scoring Engine for ranking comparable sales."""
from typing import List, Tuple
from datetime import date, datetime
from app.models.property_facts import PropertyFacts, ConstructionType, InteriorCondition
from app.models.comparable_sale import ComparableSale
from app.services.dto import RankedComparableDTO


class WeightedScoringEngine:
    """
    Calculates similarity scores for comparable properties using weighted criteria.
    
    Scoring weights:
    - Recency: 16%
    - Proximity: 15%
    - Units: 15%
    - Beds/Baths: 15%
    - Square Footage: 15%
    - Construction Type: 12%
    - Interior Condition: 12%
    Total: 100%
    """
    
    # Scoring weights
    WEIGHT_RECENCY = 0.16
    WEIGHT_PROXIMITY = 0.15
    WEIGHT_UNITS = 0.15
    WEIGHT_BEDS_BATHS = 0.15
    WEIGHT_SQFT = 0.15
    WEIGHT_CONSTRUCTION = 0.12
    WEIGHT_INTERIOR = 0.12
    
    # Construction type similarity matrix
    CONSTRUCTION_SIMILARITY = {
        (ConstructionType.BRICK, ConstructionType.BRICK): 100,
        (ConstructionType.BRICK, ConstructionType.MASONRY): 50,
        (ConstructionType.BRICK, ConstructionType.FRAME): 0,
        (ConstructionType.MASONRY, ConstructionType.MASONRY): 100,
        (ConstructionType.MASONRY, ConstructionType.BRICK): 50,
        (ConstructionType.MASONRY, ConstructionType.FRAME): 0,
        (ConstructionType.FRAME, ConstructionType.FRAME): 100,
        (ConstructionType.FRAME, ConstructionType.BRICK): 0,
        (ConstructionType.FRAME, ConstructionType.MASONRY): 0,
    }
    
    # Interior condition ordering (for gradation calculation)
    INTERIOR_CONDITION_ORDER = {
        InteriorCondition.NEEDS_GUT: 0,
        InteriorCondition.POOR: 1,
        InteriorCondition.AVERAGE: 2,
        InteriorCondition.NEW_RENO: 3,
        InteriorCondition.HIGH_END: 4,
    }
    
    def calculate_recency_score(self, sale_date: date) -> float:
        """
        Calculate recency score based on sale date.
        Formula: 100 - (days_old / 365 × 100)
        
        Args:
            sale_date: Date of the comparable sale
            
        Returns:
            Score from 0-100, where 100 is most recent
        """
        today = date.today()
        days_old = (today - sale_date).days
        score = 100 - (days_old / 365 * 100)
        return max(0, min(100, score))  # Clamp between 0 and 100
    
    def calculate_proximity_score(self, distance_miles: float, max_distance: float) -> float:
        """
        Calculate proximity score based on distance from subject property.
        Formula: 100 - (distance_miles / max_distance × 100)
        
        Args:
            distance_miles: Distance from subject property in miles
            max_distance: Maximum distance in the comparable set
            
        Returns:
            Score from 0-100, where 100 is closest
        """
        if max_distance == 0:
            return 100.0
        score = 100 - (distance_miles / max_distance * 100)
        return max(0, min(100, score))
    
    def calculate_units_score(self, subject_units: int, comp_units: int, max_units: int) -> float:
        """
        Calculate units score based on unit count difference.
        Formula: 100 - (|subject_units - comp_units| / max_units × 100)
        
        Args:
            subject_units: Number of units in subject property
            comp_units: Number of units in comparable
            max_units: Maximum unit count in the comparable set
            
        Returns:
            Score from 0-100, where 100 is exact match
        """
        if max_units == 0:
            return 100.0
        difference = abs(subject_units - comp_units)
        score = 100 - (difference / max_units * 100)
        return max(0, min(100, score))
    
    def calculate_beds_baths_score(
        self, 
        subject_beds: int, 
        subject_baths: float,
        comp_beds: int,
        comp_baths: float,
        max_bed_diff: int,
        max_bath_diff: float
    ) -> float:
        """
        Calculate beds/baths score based on combined difference normalized.
        
        Args:
            subject_beds: Bedrooms in subject property
            subject_baths: Bathrooms in subject property
            comp_beds: Bedrooms in comparable
            comp_baths: Bathrooms in comparable
            max_bed_diff: Maximum bedroom difference in comparable set
            max_bath_diff: Maximum bathroom difference in comparable set
            
        Returns:
            Score from 0-100, where 100 is exact match
        """
        bed_diff = abs(subject_beds - comp_beds)
        bath_diff = abs(subject_baths - comp_baths)
        
        # Normalize each difference
        normalized_bed = (bed_diff / max_bed_diff) if max_bed_diff > 0 else 0
        normalized_bath = (bath_diff / max_bath_diff) if max_bath_diff > 0 else 0
        
        # Combined normalized difference (average)
        combined_diff = (normalized_bed + normalized_bath) / 2
        
        score = 100 - (combined_diff * 100)
        return max(0, min(100, score))
    
    def calculate_sqft_score(self, subject_sqft: int, comp_sqft: int) -> float:
        """
        Calculate square footage score based on percentage difference.
        Formula: 100 - (|subject_sqft - comp_sqft| / subject_sqft × 100)
        
        Args:
            subject_sqft: Square footage of subject property
            comp_sqft: Square footage of comparable
            
        Returns:
            Score from 0-100, where 100 is exact match
        """
        if subject_sqft == 0:
            return 100.0 if comp_sqft == 0 else 0.0
        
        percentage_diff = abs(subject_sqft - comp_sqft) / subject_sqft * 100
        score = 100 - percentage_diff
        return max(0, min(100, score))
    
    def calculate_construction_score(
        self, 
        subject_construction: ConstructionType,
        comp_construction: ConstructionType
    ) -> float:
        """
        Calculate construction type score using categorical match.
        Returns 100 for exact match, 50 for similar, 0 for different.
        
        Args:
            subject_construction: Construction type of subject property
            comp_construction: Construction type of comparable
            
        Returns:
            Score: 100 (exact match), 50 (similar), or 0 (different)
        """
        key = (subject_construction, comp_construction)
        return float(self.CONSTRUCTION_SIMILARITY.get(key, 0))
    
    def calculate_interior_score(
        self,
        subject_interior: InteriorCondition,
        comp_interior: InteriorCondition
    ) -> float:
        """
        Calculate interior condition score with gradations.
        Exact match = 100, adjacent levels = 75, 2 levels apart = 50, 
        3 levels = 25, 4 levels = 0.
        
        Args:
            subject_interior: Interior condition of subject property
            comp_interior: Interior condition of comparable
            
        Returns:
            Score from 0-100 based on condition gap
        """
        subject_level = self.INTERIOR_CONDITION_ORDER[subject_interior]
        comp_level = self.INTERIOR_CONDITION_ORDER[comp_interior]
        
        level_diff = abs(subject_level - comp_level)
        
        if level_diff == 0:
            return 100.0
        elif level_diff == 1:
            return 75.0
        elif level_diff == 2:
            return 50.0
        elif level_diff == 3:
            return 25.0
        else:
            return 0.0
    
    def calculate_score(
        self,
        subject: PropertyFacts,
        comparable: ComparableSale,
        max_distance: float,
        max_units: int,
        max_bed_diff: int,
        max_bath_diff: float
    ) -> Tuple[float, dict]:
        """
        Calculate total weighted score for a comparable property.
        
        Args:
            subject: Subject property facts
            comparable: Comparable sale to score
            max_distance: Maximum distance in comparable set
            max_units: Maximum unit count in comparable set
            max_bed_diff: Maximum bedroom difference in comparable set
            max_bath_diff: Maximum bathroom difference in comparable set
            
        Returns:
            Tuple of (total_score, score_breakdown_dict)
        """
        # Calculate individual component scores
        recency_score = self.calculate_recency_score(comparable.sale_date)
        proximity_score = self.calculate_proximity_score(comparable.distance_miles, max_distance)
        units_score = self.calculate_units_score(subject.units, comparable.units, max_units)
        beds_baths_score = self.calculate_beds_baths_score(
            subject.bedrooms, subject.bathrooms,
            comparable.bedrooms, comparable.bathrooms,
            max_bed_diff, max_bath_diff
        )
        sqft_score = self.calculate_sqft_score(subject.square_footage, comparable.square_footage)
        construction_score = self.calculate_construction_score(
            subject.construction_type, comparable.construction_type
        )
        interior_score = self.calculate_interior_score(
            subject.interior_condition, comparable.interior_condition
        )
        
        # Calculate weighted total score
        total_score = (
            recency_score * self.WEIGHT_RECENCY +
            proximity_score * self.WEIGHT_PROXIMITY +
            units_score * self.WEIGHT_UNITS +
            beds_baths_score * self.WEIGHT_BEDS_BATHS +
            sqft_score * self.WEIGHT_SQFT +
            construction_score * self.WEIGHT_CONSTRUCTION +
            interior_score * self.WEIGHT_INTERIOR
        )
        
        # Score breakdown
        breakdown = {
            'recency_score': recency_score,
            'proximity_score': proximity_score,
            'units_score': units_score,
            'beds_baths_score': beds_baths_score,
            'sqft_score': sqft_score,
            'construction_score': construction_score,
            'interior_score': interior_score,
        }
        
        return total_score, breakdown
    
    def rank_comparables(
        self,
        subject: PropertyFacts,
        comparables: List[ComparableSale]
    ) -> List[RankedComparableDTO]:
        """
        Rank all comparables by calculating scores and sorting by total score descending.

        This is a pure computation method — it does not touch the database.
        The caller is responsible for persisting the returned DTOs as ORM records.

        Args:
            subject: Subject property facts
            comparables: List of comparable sales to rank

        Returns:
            List of RankedComparableDTO objects sorted by score (highest first),
            with sequential 1-based ranks assigned.
        """
        if not comparables:
            return []
        
        # Calculate max values for normalization
        max_distance = max(comp.distance_miles for comp in comparables)
        max_units = max(max(comp.units for comp in comparables), subject.units)
        
        max_bed_diff = max(
            abs(subject.bedrooms - comp.bedrooms) for comp in comparables
        )
        max_bath_diff = max(
            abs(subject.bathrooms - comp.bathrooms) for comp in comparables
        )
        
        # Calculate scores for all comparables
        scored_comparables: List[RankedComparableDTO] = []
        for comp in comparables:
            total_score, breakdown = self.calculate_score(
                subject, comp, max_distance, max_units, max_bed_diff, max_bath_diff
            )
            
            dto = RankedComparableDTO(
                comparable_id=comp.id,
                session_id=comp.session_id,
                total_score=total_score,
                rank=0,  # Will be set after sorting
                recency_score=breakdown['recency_score'],
                proximity_score=breakdown['proximity_score'],
                units_score=breakdown['units_score'],
                beds_baths_score=breakdown['beds_baths_score'],
                sqft_score=breakdown['sqft_score'],
                construction_score=breakdown['construction_score'],
                interior_score=breakdown['interior_score'],
            )
            scored_comparables.append(dto)
        
        # Sort by total score descending
        scored_comparables.sort(key=lambda x: x.total_score, reverse=True)
        
        # Assign ranks (dataclasses are mutable by default)
        for i, dto in enumerate(scored_comparables, start=1):
            dto.rank = i
        
        return scored_comparables
