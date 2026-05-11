"""Data Transfer Objects for service layer boundaries.

DTOs decouple service computation from ORM persistence.  Services return
DTOs; controllers are responsible for mapping DTOs to ORM models and
persisting them.
"""
from dataclasses import dataclass


@dataclass
class RankedComparableDTO:
    """Immutable result produced by WeightedScoringEngine.rank_comparables.

    Contains all fields needed to construct a ``RankedComparable`` ORM record
    without the scoring engine ever touching the database.

    Fields
    ------
    comparable_id : int
        Primary key of the source ``ComparableSale`` record.
    session_id : int
        Primary key of the parent ``AnalysisSession`` record.
    total_score : float
        Weighted composite score (0–100).
    rank : int
        1-based rank within the scored set (1 = best match).
    recency_score : float
        Individual criterion score for sale recency (0–100).
    proximity_score : float
        Individual criterion score for distance from subject (0–100).
    units_score : float
        Individual criterion score for unit-count similarity (0–100).
    beds_baths_score : float
        Individual criterion score for bedroom/bathroom similarity (0–100).
    sqft_score : float
        Individual criterion score for square-footage similarity (0–100).
    construction_score : float
        Individual criterion score for construction-type match (0–100).
    interior_score : float
        Individual criterion score for interior-condition match (0–100).
    """

    comparable_id: int
    session_id: int
    total_score: float
    rank: int
    recency_score: float
    proximity_score: float
    units_score: float
    beds_baths_score: float
    sqft_score: float
    construction_score: float
    interior_score: float
