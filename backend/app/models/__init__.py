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

# Condo filter models
from app.models.address_group_analysis import AddressGroupAnalysis

# Lead scoring models
from app.models.lead_score import LeadScore

# Chicago Socrata local cache models
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache
from app.models.sync_log import SyncLog

# Multifamily underwriting models
from app.models.deal import Deal
from app.models.unit import Unit
from app.models.rent_roll_entry import RentRollEntry
from app.models.market_rent_assumption import MarketRentAssumption
from app.models.rent_comp import RentComp
from app.models.sale_comp import SaleComp
from app.models.rehab_plan_entry import RehabPlanEntry
from app.models.lender_profile import LenderProfile
from app.models.deal_lender_selection import DealLenderSelection
from app.models.funding_source import FundingSource
from app.models.pro_forma_result import ProFormaResult
from app.models.lead_deal_link import LeadDealLink
from app.models.deal_audit_trail import DealAuditTrail

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
    # Condo filter
    'AddressGroupAnalysis',
    # Lead scoring
    'LeadScore',
    # Multifamily underwriting
    'Deal',
    'Unit',
    'RentRollEntry',
    'MarketRentAssumption',
    'RentComp',
    'SaleComp',
    'RehabPlanEntry',
    'LenderProfile',
    'DealLenderSelection',
    'FundingSource',
    'ProFormaResult',
    'LeadDealLink',
    'DealAuditTrail',
    # Chicago Socrata local cache
    'ParcelUniverseCache',
    'ParcelSalesCache',
    'ImprovementCharacteristicsCache',
    'SyncLog',
]
