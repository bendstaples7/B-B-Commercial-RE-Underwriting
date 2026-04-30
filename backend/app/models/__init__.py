"""Data models package."""
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition
from app.models.comparable_sale import ComparableSale
from app.models.analysis_session import AnalysisSession, WorkflowStep
from app.models.ranked_comparable import RankedComparable
from app.models.valuation_result import ValuationResult, ComparableValuation
from app.models.scenario import (
    Scenario, 
    ScenarioType, 
    WholesaleScenario, 
    FixFlipScenario, 
    BuyHoldScenario
)

# Lead management models
from app.models.lead import Lead, LeadAuditTrail
from app.models.import_job import ImportJob, FieldMapping, OAuthToken
from app.models.lead_scoring import ScoringWeights
from app.models.enrichment import DataSource, EnrichmentRecord
from app.models.marketing import MarketingList, MarketingListMember

__all__ = [
    'PropertyFacts',
    'PropertyType',
    'ConstructionType',
    'InteriorCondition',
    'ComparableSale',
    'AnalysisSession',
    'WorkflowStep',
    'RankedComparable',
    'ValuationResult',
    'ComparableValuation',
    'Scenario',
    'ScenarioType',
    'WholesaleScenario',
    'FixFlipScenario',
    'BuyHoldScenario',
    # Lead management
    'Lead',
    'LeadAuditTrail',
    'ImportJob',
    'FieldMapping',
    'OAuthToken',
    'ScoringWeights',
    'DataSource',
    'EnrichmentRecord',
    'MarketingList',
    'MarketingListMember',
]
