"""Data models package."""
# Authentication
from app.models.user import User

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

# Contact model
from app.models.contact import Contact
from app.models.contact_phone import ContactPhone
from app.models.contact_email import ContactEmail
from app.models.property_contact import PropertyContact

# Lead management models
from app.models.lead import Property, Lead, LeadAuditTrail
from app.models.import_job import ImportJob, FieldMapping, OAuthToken
from app.models.lead_scoring import ScoringWeights
from app.models.enrichment import DataSource, EnrichmentRecord
from app.models.motivation_signal import (
    MotivationSignal,
    ProspectAreaFilter,
    ProspectCandidate,
    ProspectFeedState,
)
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

# Commercial OM PDF intake models
from app.models.om_intake_job import OMIntakeJob, OMFieldOverride

# RentCast cache
from app.models.rentcast_cache import RentCastCache

# HubSpot CRM migration — Organization models
from app.models.organization import Organization
from app.models.organization_audit_log import OrganizationAuditLog
from app.models.property_organization_link import PropertyOrganizationLink
from app.models.owner_organization_link import OwnerOrganizationLink

# HubSpot CRM migration — Interaction models
from app.models.interaction import Interaction
from app.models.interaction_association import InteractionAssociation

# HubSpot CRM migration — Task models
from app.models.task import Task
from app.models.task_association import TaskAssociation

# HubSpot CRM migration — raw HubSpot object models
from app.models.hubspot_company import HubSpotCompany
from app.models.hubspot_contact import HubSpotContact

# HubSpot CRM migration — Config model
from app.models.hubspot_config import HubSpotConfig

# HubSpot CRM migration — Import run tracking
from app.models.hubspot_import_run import HubSpotImportRun

# HubSpot CRM migration — Match tracking
from app.models.hubspot_match import HubSpotMatch

# HubSpot CRM migration — Engagement records
from app.models.hubspot_engagement import HubSpotEngagement

# HubSpot CRM migration — Deal records
from app.models.hubspot_deal import HubSpotDeal

# HubSpot CRM migration — Signal extraction
from app.models.hubspot_signal import HubSpotSignal

# HubSpot CRM migration — Signal dictionary
from app.models.hubspot_signal_dictionary import HubSpotSignalDictionary

# Actionable Lead Command Center models
from app.models.lead_task import LeadTask
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.lead_crm_flags_view import LeadCRMFlagsView

# HubSpot webhook sync models
from app.models.hubspot_webhook_log import HubSpotWebhookLog
from app.models.hubspot_sync_run import HubSpotSyncRun
from app.models.hubspot_platform_write import HubSpotPlatformWrite

# Open Letter Connect / direct mail
from app.models.open_letter_config import OpenLetterConfig
from app.models.mail_queue_item import MailQueueItem
from app.models.mail_campaign import MailCampaign

__all__ = [
    # Authentication
    'User',
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
    # Contact model
    'Contact',
    'ContactPhone',
    'ContactEmail',
    'PropertyContact',
    # Lead management
    'Property',
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
    # Commercial OM PDF intake
    'OMIntakeJob',
    'OMFieldOverride',
    # RentCast cache
    'RentCastCache',
    # HubSpot CRM migration — Organization
    'Organization',
    'OrganizationAuditLog',
    'PropertyOrganizationLink',
    'OwnerOrganizationLink',
    # HubSpot CRM migration — Interaction
    'Interaction',
    'InteractionAssociation',
    # HubSpot CRM migration — Task
    'Task',
    'TaskAssociation',
    # HubSpot CRM migration — Import run tracking
    'HubSpotImportRun',
    # HubSpot CRM migration — Config
    'HubSpotConfig',
    # HubSpot CRM migration — Engagement records
    'HubSpotEngagement',
    # HubSpot CRM migration — raw HubSpot objects
    'HubSpotCompany',
    'HubSpotDeal',
    'HubSpotContact',
    'HubSpotMatch',
    # HubSpot CRM migration — Signal extraction
    'HubSpotSignal',
    # HubSpot CRM migration — Signal dictionary
    'HubSpotSignalDictionary',
    # Actionable Lead Command Center
    'LeadTask',
    'LeadTimelineEntry',
    'LeadCRMFlagsView',
    # HubSpot webhook sync
    'HubSpotWebhookLog',
    'HubSpotSyncRun',
    'HubSpotPlatformWrite',
    # Open Letter Connect
    'OpenLetterConfig',
    'MailQueueItem',
    'MailCampaign',
]
