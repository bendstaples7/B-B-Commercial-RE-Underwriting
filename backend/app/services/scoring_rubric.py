"""Point-based scoring rubric for residential and commercial leads.

Mostly pure functions. ``calculate_data_quality_score`` may read linked
ContactPhone / ContactEmail rows when ``lead.id`` is set.
"""
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional

from app.models.lead import Lead
from app.services.enrichment_scoring import (
    contactability_score,
    engagement_score,
    ownership_duration_score,
    property_equity_score,
    scale_subscore_to_100,
)
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOTIVATION_KEYWORDS = [
    "motivated", "distressed", "vacant", "abandoned", "probate",
    "divorce", "tax lien", "code violation", "fire damage",
    "behind on payments", "pre-foreclosure", "foreclosure",
    "estate", "inherited", "tired landlord", "out of state",
    "needs work", "deferred maintenance", "boarded up",
]

SOURCE_TYPE_DISTRESS_QUALIFYING = frozenset({"foreclosure", "tax_distress", "long_owned"})
SOURCE_TYPE_DISTRESS_BASE_POINTS = 10
SOURCE_TYPE_DISTRESS_TAX_BONUS = 5
SOURCE_TYPE_DISTRESS_COMBINED_CAP = 15

TAX_DISTRESS_FORBIDDEN_TERMS = frozenset({
    "tax_delinquency", "tax_sale", "delinquent", "tax delinquency", "tax sale",
})

# Present in score_details for UI attribution only — already counted elsewhere
# (notes_keywords ⊂ structured_motivation; do not treat as a second additive).
SCORE_ATTRIBUTION_ONLY_KEYS = frozenset({
    "notes_keywords",
})

RESIDENTIAL_MAX_POINTS = {
    "property_type_fit": 20,
    "neighborhood_fit": 15,
    "unit_count_fit": 15,
    "absentee_owner": 10,
    "owner_mailing_quality": 10,
    "years_owned": 10,
    "existing_notes_motivation": 10,
    "manual_priority": 10,
    "source_type_distress": SOURCE_TYPE_DISTRESS_COMBINED_CAP,
    "structured_motivation": 25,
    "property_heuristics": 20,
    "contactability": 20,
    "property_equity": 25,
    "ownership_duration": 15,
    "engagement": 10,
}

COMMERCIAL_MAX_POINTS = {
    "property_type_fit": 20,
    "condo_clarity": 20,
    "building_sale_possible": 15,
    "neighborhood_fit": 10,
    "owner_concentration": 10,
    "absentee_owner": 10,
    "building_size_fit": 5,
    "existing_notes_motivation": 5,
    "manual_priority": 5,
    "structured_motivation": 20,
    "contactability": 20,
    "property_equity": 25,
    "ownership_duration": 15,
    "engagement": 10,
}

# Property identity slice (max 50) + contact reachability slice (max 50) = 100.
PROPERTY_IDENTITY_MAX = 50.0
CONTACT_REACHABILITY_MAX = 50.0
BEST_PHONE_MAX_POINTS = 35.0
EMAIL_MAX_POINTS = 15.0
EMAIL_BASE_POINTS = 10.0
EMAIL_OWNER_PRIMARY_BONUS = 5.0

# Rescaled from the former 100-point property-only checklist (halved).
DATA_QUALITY_FIELDS = {
    "has_pin": 10.0,
    "has_property_address": 7.5,
    "has_normalized_address": 5.0,
    "has_owner_name": 7.5,
    "has_owner_mailing_address": 7.5,
    "has_property_type_or_assessor_class": 5.0,
    "has_estimated_unit_count_or_building_size": 5.0,
    "has_source_reference": 2.5,
}

MISSING_DATA_FIELDS = [
    "pin", "property_address", "normalized_address", "owner_name",
    "owner_mailing_address", "property_type", "assessor_class",
    "estimated_units", "building_sqft", "years_owned", "neighborhood",
    "condo_risk_status", "building_sale_possible", "violation_data",
    "permit_data", "tax_data", "skip_trace_data",
    "phone", "email",
]

TIER_A_MIN = 75
TIER_B_MIN = 60
TIER_C_MIN = 40

DESIRABLE_PROPERTY_TYPES = {
    "single_family", "single family", "sfr",
    "multi_family", "multi family", "multifamily",
    "duplex", "triplex", "fourplex",
}

_SALE_DATE_FORMATS = (
    '%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y', '%m-%d-%y',
    '%B %d, %Y', '%b %d, %Y', '%B %d %Y', '%b %d %Y',
)

SCORING_ATTRIBUTES = frozenset({
    'assessed_value', 'date_skip_traced', 'socials', 'year_built', 'lot_size',
    'mailer_history', 'has_phone', 'has_email', 'follow_up_date', 'timeline',
    'phone_5', 'phone_6', 'phone_7', 'email_4', 'email_5',
    'property_type', 'bedrooms', 'bathrooms', 'square_footage', 'property_city',
    'property_zip', 'units', 'mailing_address', 'mailing_city', 'mailing_state',
    'mailing_zip', 'property_street', 'acquisition_date', 'notes',
    'manual_priority', 'source_type', 'tax_distress_data', 'do_not_contact',
    'county_assessor_pin', 'owner_first_name', 'owner_last_name', 'source',
    'data_source', 'updated_at', 'id', 'lead_category', 'unanswered_call_count',
    'last_contact_date', 'lead_status', 'condo_risk_status', 'building_sale_possible',
    'analysis_complete', 'most_recent_sale',
    'motivation_score', 'motivation_signal_summary',
})


def get_scoring_attributes() -> frozenset:
    return SCORING_ATTRIBUTES


def parse_sale_date_string(value: Optional[str]) -> Optional[date]:
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    for fmt in _SALE_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', text)
    if match:
        month, day, year = match.groups()
        year_int = int(year)
        if year_int < 100:
            year_int += 1900 if year_int >= 50 else 2000
        try:
            return date(year_int, int(month), int(day))
        except ValueError:
            return None
    return None


def effective_acquisition_date(lead: Lead) -> Optional[date]:
    acquisition = getattr(lead, 'acquisition_date', None)
    sale_text = getattr(lead, 'most_recent_sale', None)
    imported_sale = (
        parse_sale_date_string(sale_text)
        if isinstance(sale_text, str)
        else None
    )
    candidates = [
        candidate
        for candidate in (acquisition, imported_sale)
        if isinstance(candidate, date) and candidate <= date.today()
    ]
    return max(candidates) if candidates else None


RECENT_SALE_SUPPRESSION_DAYS = 730  # 24 months


def is_recently_sold(lead: Lead, days: int = RECENT_SALE_SUPPRESSION_DAYS) -> bool:
    """True when the lead's effective sale/acquisition date is within *days*."""
    sale = effective_acquisition_date(lead)
    if sale is None or sale > date.today():
        return False
    return (date.today() - sale).days < days


def format_last_sale_at(lead: Lead) -> str | None:
    """ISO date string for the lead's most recent sale, if known."""
    sale = effective_acquisition_date(lead)
    if sale is None:
        return None
    return sale.isoformat()


def _contacts_skip_trace_before_sale(lead: Lead) -> bool:
    """True when skip-trace is missing or older than the effective sale date."""
    sale = effective_acquisition_date(lead)
    if sale is None or sale > date.today():
        return False
    skip_traced = getattr(lead, 'date_skip_traced', None)
    if skip_traced is None:
        return True
    skip_day = skip_traced.date() if hasattr(skip_traced, 'date') else skip_traced
    return skip_day < sale


def contacts_likely_prior_owner(lead: Lead) -> bool:
    """True when contacts may still describe the prior owner during a recent-sale hold.

    Only applies inside the recent-sale window (``is_recently_sold``) for UI
    gray-out. Older sales (e.g. year 2000) do not gray out contacts. Post-hold
    skip-trace handoff uses ``contacts_need_post_hold_verification`` instead.
    """
    if not is_recently_sold(lead):
        return False
    return _contacts_skip_trace_before_sale(lead)


def contacts_need_post_hold_verification(lead: Lead) -> bool:
    """True when the recent-sale hold ended but contacts are still pre-sale.

    Used for scoring (``enrich_data`` / ``recently_sold``) and post-hold heal.
    Requires a known sale outside the hold window and skip-trace missing/before
    that sale — not ancient sales with no recent-sale signal.
    """
    if is_recently_sold(lead):
        return False
    sale = effective_acquisition_date(lead)
    if sale is None or sale > date.today():
        return False
    # Only treat as post-hold stale when the sale was recently in the hold
    # window (ended within ~2x the suppression period). Year-2000 sales stay out.
    days_since = (date.today() - sale).days
    if days_since >= RECENT_SALE_SUPPRESSION_DAYS * 2:
        return False
    return _contacts_skip_trace_before_sale(lead)


def contacts_stale_since(lead: Lead) -> str | None:
    """ISO sale date that makes contacts stale, or None when not stale."""
    if not contacts_likely_prior_owner(lead):
        return None
    return format_last_sale_at(lead)


def display_most_recent_sale(lead: Lead) -> str | None:
    """Single UI display value using the newest valid sale date."""
    effective = effective_acquisition_date(lead)
    if effective is not None:
        return effective.strftime('%m/%d/%Y')
    sale_text = getattr(lead, 'most_recent_sale', None)
    if not sale_text or not str(sale_text).strip():
        return None
    return str(sale_text).strip()


def humanize_sale_date_source(changed_by: str | None) -> str | None:
    if not changed_by:
        return None
    if changed_by.startswith('enrichment:cook_county_assessor'):
        return 'Cook County records'
    if changed_by.startswith('import_job:'):
        return 'Import'
    if changed_by.startswith('enrichment:'):
        name = changed_by.removeprefix('enrichment:')
        return name.replace('_', ' ').title()
    if changed_by == 'manual':
        return 'Manual'
    return changed_by


_SALE_RETRIEVED_KEYS = frozenset({
    'acquisition_date',
    'most_recent_sale',
    'most_recent_sale_price',
})


def _retrieved_data_has_sale_fields(retrieved_data) -> bool:
    if not isinstance(retrieved_data, dict):
        return False
    for key in _SALE_RETRIEVED_KEYS:
        value = retrieved_data.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return True
    return False


def _sale_probe_status_from_enrichment(enrich, *, is_assessor: bool) -> str | None:
    """Map an enrichment row to a sale-date UI status.

    Assessor ``success`` / ``no_results`` without sale keys means the parcel
    sale probe ran empty — ``no_sale``. Commercial valuation must never claim
    ``no_sale`` (it is not the parcel-sales probe).
    """
    if enrich is None:
        return None
    raw = getattr(enrich, 'status', None)
    if raw == 'failed':
        return 'failed'
    has_sale = _retrieved_data_has_sale_fields(getattr(enrich, 'retrieved_data', None))
    if is_assessor and raw in ('success', 'no_results'):
        return 'success' if has_sale else 'no_sale'
    if raw == 'success':
        return 'success' if has_sale else 'no_results'
    if raw == 'no_results':
        return 'no_results'
    return raw


def _pick_sale_probe_enrichment(lead_id: int, source_ids_by_name: dict[str, int]):
    """Prefer assessor over commercial; return (record, is_assessor)."""
    from app.models.enrichment import EnrichmentRecord

    assessor_id = source_ids_by_name.get('cook_county_assessor')
    commercial_id = source_ids_by_name.get('cook_county_commercial_valuation')

    def _latest_for(source_id: int | None):
        if source_id is None:
            return None
        return (
            EnrichmentRecord.query
            .filter(
                EnrichmentRecord.lead_id == lead_id,
                EnrichmentRecord.data_source_id == source_id,
            )
            .order_by(EnrichmentRecord.created_at.desc())
            .first()
        )

    assessor = _latest_for(assessor_id)
    if assessor is not None:
        return assessor, True

    commercial = _latest_for(commercial_id)
    if commercial is None:
        return None, False
    return commercial, False


def resolve_sale_date_meta(lead: Lead) -> dict:
    """Audit + enrichment freshness for sale-date fields shown in Command Center."""
    null_meta = {'last_updated_at': None, 'last_checked_at': None, 'source': None}
    from flask import has_app_context

    if not has_app_context():
        return null_meta

    from app.models.enrichment import DataSource
    from app.models.lead import LeadAuditTrail

    lead_id = getattr(lead, 'id', None)
    if not isinstance(lead_id, int):
        return null_meta

    acquisition = getattr(lead, 'acquisition_date', None)
    imported_sale = parse_sale_date_string(
        str(getattr(lead, 'most_recent_sale', '') or ''),
    )
    valid_acquisition = (
        acquisition
        if isinstance(acquisition, date) and acquisition <= date.today()
        else None
    )
    valid_imported_sale = (
        imported_sale
        if imported_sale is not None and imported_sale <= date.today()
        else None
    )
    preferred_field = (
        'most_recent_sale'
        if valid_acquisition is None
        or (
            valid_imported_sale is not None
            and valid_imported_sale > valid_acquisition
        )
        else 'acquisition_date'
    )
    row = (
        LeadAuditTrail.query
        .filter(
            LeadAuditTrail.lead_id == lead_id,
            LeadAuditTrail.field_name == preferred_field,
        )
        .order_by(LeadAuditTrail.changed_at.desc())
        .first()
    )

    last_updated_at = row.changed_at.isoformat() if row and row.changed_at else None
    source = humanize_sale_date_source(row.changed_by) if row else None

    # Sale-date probe: prefer cook_county_assessor. Commercial valuation is
    # only a fallback when no assessor enrichment exists.
    source_ids_by_name = {
        name: sid
        for sid, name in (
            DataSource.query
            .with_entities(DataSource.id, DataSource.name)
            .filter(DataSource.name.in_((
                'cook_county_assessor',
                'cook_county_commercial_valuation',
            )))
            .all()
        )
    }
    last_checked_at = None
    enrichment_status = None
    enrichment_error = None
    if source_ids_by_name:
        enrich, is_assessor = _pick_sale_probe_enrichment(lead_id, source_ids_by_name)
        if enrich and enrich.created_at:
            last_checked_at = enrich.created_at.isoformat()
            enrichment_status = _sale_probe_status_from_enrichment(
                enrich, is_assessor=is_assessor,
            )
            enrichment_error = getattr(enrich, 'error_reason', None)
            if source is None:
                source = 'Cook County records'

    if last_updated_at is None and last_checked_at is None:
        return null_meta

    meta = {
        'last_updated_at': last_updated_at,
        'last_checked_at': last_checked_at,
        'source': source,
    }
    if enrichment_status is not None:
        meta['status'] = enrichment_status
    if enrichment_error is not None:
        meta['error_reason'] = enrichment_error
    return meta


def effective_acquisition_date_sql():
    """SQL expression matching effective_acquisition_date() on PostgreSQL."""
    from sqlalchemy import Date, Integer, and_, case, cast, or_
    from sqlalchemy.sql import func

    mrs = func.btrim(Lead.most_recent_sale)

    def _calendar_date(year, month, day):
        """Build a date without letting malformed input abort the query."""
        is_leap_year = or_(
            year % 400 == 0,
            and_(year % 4 == 0, year % 100 != 0),
        )
        max_day = case(
            (month.in_([1, 3, 5, 7, 8, 10, 12]), 31),
            (month.in_([4, 6, 9, 11]), 30),
            (month == 2, case((is_leap_year, 29), else_=28)),
            else_=0,
        )
        is_real_date = and_(
            year >= 1,
            month.between(1, 12),
            day >= 1,
            day <= max_day,
        )
        return case(
            (is_real_date, func.make_date(year, month, day)),
            else_=None,
        )

    numeric_month = cast(
        func.substring(mrs, r'^\s*([0-9]{1,2})[/-]'),
        Integer,
    )
    numeric_day = cast(
        func.substring(mrs, r'^\s*[0-9]{1,2}[/-]([0-9]{1,2})[/-]'),
        Integer,
    )
    numeric_year_raw = cast(
        func.substring(mrs, r'([0-9]{2,4})\s*$'),
        Integer,
    )
    numeric_year = case(
        (
            numeric_year_raw < 100,
            case(
                (numeric_year_raw >= 50, numeric_year_raw + 1900),
                else_=numeric_year_raw + 2000,
            ),
        ),
        else_=numeric_year_raw,
    )
    numeric_date = _calendar_date(
        numeric_year,
        numeric_month,
        numeric_day,
    )

    iso_year = cast(func.substring(mrs, r'^([0-9]{4})-'), Integer)
    iso_month = cast(
        func.substring(mrs, r'^[0-9]{4}-([0-9]{2})-'),
        Integer,
    )
    iso_day = cast(func.substring(mrs, r'([0-9]{2})$'), Integer)
    iso_date = _calendar_date(iso_year, iso_month, iso_day)

    month_name = func.lower(func.substring(mrs, r'^([A-Za-z]+)\s+'))
    named_month = case(
        (month_name.in_(['january', 'jan']), 1),
        (month_name.in_(['february', 'feb']), 2),
        (month_name.in_(['march', 'mar']), 3),
        (month_name.in_(['april', 'apr']), 4),
        (month_name == 'may', 5),
        (month_name.in_(['june', 'jun']), 6),
        (month_name.in_(['july', 'jul']), 7),
        (month_name.in_(['august', 'aug']), 8),
        (month_name.in_(['september', 'sep']), 9),
        (month_name.in_(['october', 'oct']), 10),
        (month_name.in_(['november', 'nov']), 11),
        (month_name.in_(['december', 'dec']), 12),
        else_=None,
    )
    named_day = cast(
        func.substring(mrs, r'^[A-Za-z]+\s+([0-9]{1,2})'),
        Integer,
    )
    named_year = cast(func.substring(mrs, r'([0-9]{4})\s*$'), Integer)
    named_date = _calendar_date(named_year, named_month, named_day)

    parsed = case(
        (
            mrs.op('~')(
                r'^[0-9]{4}-(0[1-9]|1[0-2])-'
                r'(0[1-9]|[12][0-9]|3[01])$'
            ),
            iso_date,
        ),
        (
            mrs.op('~')(
                r'^(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])/'
                r'([0-9]{2}|[0-9]{4})$'
            ),
            numeric_date,
        ),
        (
            mrs.op('~')(
                r'^(0?[1-9]|1[0-2])-(0?[1-9]|[12][0-9]|3[01])-'
                r'([0-9]{2}|[0-9]{4})$'
            ),
            numeric_date,
        ),
        (
            mrs.op('~*')(
                r'^(January|Jan|February|Feb|March|Mar|April|Apr|May|'
                r'June|Jun|July|Jul|August|Aug|September|Sep|October|Oct|'
                r'November|Nov|December|Dec)\s+'
                r'(0?[1-9]|[12][0-9]|3[01]),?\s+[0-9]{4}$'
            ),
            named_date,
        ),
        else_=None,
    )
    valid_acquisition = case(
        (Lead.acquisition_date <= date.today(), Lead.acquisition_date),
        else_=None,
    )
    valid_imported = case((parsed <= date.today(), parsed), else_=None)
    return cast(func.greatest(valid_acquisition, valid_imported), Date)


def sql_not_recently_sold(cutoff: date | None = None):
    """SQL filter: lead is outside the recent-sale suppression window."""
    from sqlalchemy import or_

    if cutoff is None:
        cutoff = date.today() - timedelta(days=RECENT_SALE_SUPPRESSION_DAYS)
    effective = effective_acquisition_date_sql()
    return or_(
        effective.is_(None),
        effective > date.today(),
        effective <= cutoff,
    )


def calculate_residential_score(lead: Lead) -> dict:
    details = {}
    details["property_type_fit"] = residential_property_type_fit(lead)
    details["neighborhood_fit"] = residential_neighborhood_fit(lead)
    details["unit_count_fit"] = residential_unit_count_fit(lead)

    source_type = getattr(lead, "source_type", None)
    if source_type == "absentee_owner":
        details["absentee_owner"] = 10.0
    else:
        details["absentee_owner"] = absentee_owner_score(lead)

    details["owner_mailing_quality"] = owner_mailing_quality(lead)
    details["years_owned"] = 0.0
    from app.services.motivation_signal_service import structured_motivation_score
    details["structured_motivation"] = structured_motivation_score(lead)
    details["property_heuristics"] = property_heuristics_bonus(lead)

    details["contactability"] = contactability_score(lead, max_points=20.0)
    details["property_equity"] = property_equity_score(lead, max_points=25.0)
    details["ownership_duration"] = ownership_duration_score(lead, max_points=15.0)
    details["engagement"] = engagement_score(lead, max_points=10.0)

    return {
        "total_score": sum(details.values()),
        "score_details": details,
        "score_version": "unified_v1_residential",
    }


def calculate_commercial_score(lead: Lead) -> dict:
    details = {}
    details["property_type_fit"] = commercial_property_type_fit(lead)
    details["condo_clarity"] = condo_clarity_score(lead)
    details["building_sale_possible"] = building_sale_possible_score(lead)
    details["neighborhood_fit"] = commercial_neighborhood_fit(lead)
    details["owner_concentration"] = owner_concentration_score(lead)
    details["absentee_owner"] = absentee_owner_score(lead)
    details["building_size_fit"] = building_size_fit_score(lead)
    from app.services.motivation_signal_service import structured_motivation_score
    details["structured_motivation"] = structured_motivation_score(lead)
    details["contactability"] = contactability_score(lead, max_points=20.0)
    details["property_equity"] = property_equity_score(lead, max_points=25.0)
    details["ownership_duration"] = ownership_duration_score(lead, max_points=15.0)
    details["engagement"] = engagement_score(lead, max_points=10.0)

    return {
        "total_score": sum(details.values()),
        "score_details": details,
        "score_version": "unified_v1_commercial",
    }


def property_heuristics_bonus(lead: Lead) -> float:
    """LSE property-characteristics heuristics ported into rubric (max 20)."""
    score = 0.0
    property_type = getattr(lead, 'property_type', None)
    if property_type and isinstance(property_type, str) and property_type.strip():
        score += 5.0
        if property_type.strip().lower() in DESIRABLE_PROPERTY_TYPES:
            score += 5.0
    bedrooms = getattr(lead, 'bedrooms', None)
    if isinstance(bedrooms, (int, float)):
        score += 3.0
        if 2 <= bedrooms <= 4:
            score += 3.0
    bathrooms = getattr(lead, 'bathrooms', None)
    if isinstance(bathrooms, (int, float)):
        score += 2.0
    sqft = getattr(lead, 'square_footage', None)
    if isinstance(sqft, (int, float)):
        score += 2.0
        if 800 <= sqft <= 3000:
            score += 2.0
    lot_size = getattr(lead, 'lot_size', None)
    if isinstance(lot_size, (int, float)):
        score += 1.0
    year_built = getattr(lead, 'year_built', None)
    if isinstance(year_built, int):
        score += 1.0
        if year_built >= 1950:
            score += 1.0
    return min(score, float(RESIDENTIAL_MAX_POINTS["property_heuristics"]))


def _safe_str(val) -> str | None:
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _safe_int(val) -> int | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val == int(val):
        return int(val)
    return None


def residential_property_type_fit(lead: Lead) -> float:
    pt = _safe_str(getattr(lead, 'property_type', None))
    if pt:
        pt_lower = pt.lower()
        multi_family_types = {
            "multi_family", "multi family", "multifamily", "multi-family",
            "duplex", "triplex", "fourplex", "2-4 unit", "2 unit", "3 unit", "4 unit",
        }
        sfr_types = {"single_family", "single family", "sfr"}
        if pt_lower in multi_family_types:
            return 20.0
        if pt_lower in sfr_types:
            return 10.0
        return 5.0
    units = _safe_int(getattr(lead, 'units', None))
    if units is not None:
        if 2 <= units <= 4:
            return 20.0
        if units >= 5:
            return 15.0
        if units == 1:
            return 10.0
    return 0.0


def residential_neighborhood_fit(lead: Lead) -> float:
    if lead.property_city or lead.property_zip:
        return 8.0
    return 0.0


def residential_unit_count_fit(lead: Lead) -> float:
    units = _safe_int(getattr(lead, 'units', None))
    if units is None:
        return 0.0
    if 2 <= units <= 4:
        return 15.0
    if units >= 5:
        return 10.0
    if units == 1:
        return 5.0
    return 0.0


def absentee_owner_score(lead: Lead) -> float:
    if not lead.mailing_address or not lead.property_street:
        return 0.0
    if lead.mailing_address.strip().lower() != lead.property_street.strip().lower():
        return 10.0
    return 0.0


def owner_mailing_quality(lead: Lead) -> float:
    has_street = bool(lead.mailing_address and lead.mailing_address.strip())
    has_city = bool(lead.mailing_city and lead.mailing_city.strip())
    has_state = bool(lead.mailing_state and lead.mailing_state.strip())
    has_zip = bool(lead.mailing_zip and lead.mailing_zip.strip())
    parts_present = sum([has_street, has_city, has_state, has_zip])
    if parts_present == 4:
        return 10.0
    if parts_present > 0:
        return 5.0
    return 0.0


def notes_motivation_score(lead: Lead, max_points: float) -> float:
    if not lead.notes:
        return 0.0
    notes_lower = lead.notes.lower()
    for keyword in MOTIVATION_KEYWORDS:
        if keyword in notes_lower:
            return max_points
    return 3.0


def manual_priority_score(lead: Lead, max_points: float) -> float:
    priority = getattr(lead, "manual_priority", None)
    if priority is None:
        return 0.0
    return max(0.0, min(float(priority), max_points))


def source_type_distress_score(lead: Lead) -> float:
    source_type = getattr(lead, "source_type", None)
    base_points = 0.0
    if source_type in SOURCE_TYPE_DISTRESS_QUALIFYING:
        base_points = float(SOURCE_TYPE_DISTRESS_BASE_POINTS)
    tax_distress_data = getattr(lead, "tax_distress_data", None)
    if isinstance(tax_distress_data, str):
        try:
            tax_distress_data = json.loads(tax_distress_data)
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "lead %s: malformed tax_distress_data JSON — treating as null",
                getattr(lead, "id", "unknown"),
            )
            tax_distress_data = None
    bonus = float(SOURCE_TYPE_DISTRESS_TAX_BONUS) if tax_distress_data is not None else 0.0
    return min(base_points + bonus, float(SOURCE_TYPE_DISTRESS_COMBINED_CAP))


def commercial_property_type_fit(lead: Lead) -> float:
    if not lead.property_type:
        return 0.0
    pt = lead.property_type.strip().lower()
    commercial_types = {
        "commercial", "mixed-use", "mixed use", "retail",
        "office", "industrial", "warehouse",
    }
    multi_family_types = {"multi_family", "multi family", "multifamily", "apartment"}
    if pt in commercial_types:
        return 20.0
    if pt in multi_family_types:
        units = getattr(lead, "units", None)
        try:
            unit_count = int(units) if units is not None else 0
        except (TypeError, ValueError):
            unit_count = 0
        if unit_count >= 5:
            return 15.0
        return 5.0
    return 5.0


def condo_clarity_score(lead: Lead) -> float:
    status = getattr(lead, "condo_risk_status", None)
    if not status:
        return 10.0
    mapping = {
        "likely_not_condo": 20.0, "unknown": 10.0,
        "partial_condo_possible": 5.0, "needs_review": 2.0, "likely_condo": 0.0,
    }
    return mapping.get(status.strip().lower(), 10.0)


def building_sale_possible_score(lead: Lead) -> float:
    value = getattr(lead, "building_sale_possible", None)
    if not value:
        return 5.0
    mapping = {"yes": 15.0, "maybe": 8.0, "no": 0.0, "unknown": 5.0}
    return mapping.get(value.strip().lower(), 5.0)


def commercial_neighborhood_fit(lead: Lead) -> float:
    if lead.property_city or lead.property_zip:
        return 5.0
    return 0.0


def owner_concentration_score(lead: Lead) -> float:
    condo_analysis = getattr(lead, "condo_analysis", None)
    if condo_analysis and hasattr(condo_analysis, "owner_count"):
        owner_count = condo_analysis.owner_count
        if owner_count is not None and owner_count > 0:
            if owner_count == 1:
                return 10.0
            if owner_count == 2:
                return 7.0
            if owner_count <= 4:
                return 4.0
            return 2.0
    return 5.0


def building_size_fit_score(lead: Lead) -> float:
    sqft = lead.square_footage
    if sqft is None:
        return 0.0
    if sqft >= 2000:
        return 5.0
    return 3.0


def _property_identity_score(lead: Lead) -> float:
    """Assessor / identity fields — max PROPERTY_IDENTITY_MAX (50)."""
    score = 0.0
    if lead.county_assessor_pin and str(lead.county_assessor_pin).strip():
        score += DATA_QUALITY_FIELDS["has_pin"]
    if lead.property_street and lead.property_street.strip():
        score += DATA_QUALITY_FIELDS["has_property_address"]
        score += DATA_QUALITY_FIELDS["has_normalized_address"]
    if (lead.owner_first_name and lead.owner_first_name.strip()) or \
       (lead.owner_last_name and lead.owner_last_name.strip()):
        score += DATA_QUALITY_FIELDS["has_owner_name"]
    if lead.mailing_address and lead.mailing_address.strip():
        score += DATA_QUALITY_FIELDS["has_owner_mailing_address"]
    if lead.property_type and lead.property_type.strip():
        score += DATA_QUALITY_FIELDS["has_property_type_or_assessor_class"]
    if lead.units is not None or lead.square_footage is not None:
        score += DATA_QUALITY_FIELDS["has_estimated_unit_count_or_building_size"]
    if (lead.source and lead.source.strip()) or (lead.data_source and lead.data_source.strip()):
        score += DATA_QUALITY_FIELDS["has_source_reference"]
    return min(PROPERTY_IDENTITY_MAX, score)


def _flat_phone_confidences(lead: Lead) -> list[int]:
    from app.services.phone_confidence_service import DEFAULT_CONFIDENCE

    scores: list[int] = []
    for slot in range(1, 8):
        raw = getattr(lead, f"phone_{slot}", None)
        if isinstance(raw, str) and raw.strip():
            scores.append(DEFAULT_CONFIDENCE)
    return scores


def _use_flat_contact_fields(lead: Lead) -> bool:
    """Use flat phone/email unless contacts are still likely prior-owner stale."""
    return not contacts_likely_prior_owner(lead)


def _relational_phone_confidences(lead_id: int) -> list[int]:
    """Best-effort DB read of ContactPhone confidence for a property lead."""
    from app.services.phone_confidence_service import DEFAULT_CONFIDENCE
    from flask import has_app_context

    if not has_app_context():
        return []

    try:
        from sqlalchemy import text
        from app import db

        rows = db.session.execute(
            text("""
                SELECT cp.confidence_score
                FROM contact_phones cp
                JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                WHERE pc.property_id = :lead_id
                  AND (pc.role IS NULL OR pc.role <> 'former_owner')
                  AND cp.value IS NOT NULL
                  AND TRIM(cp.value) <> ''
            """),
            {"lead_id": lead_id},
        ).fetchall()
    except SQLAlchemyError as exc:
        logger.warning("relational phone confidence lookup failed for lead %s: %s", lead_id, exc)
        return []

    out: list[int] = []
    for (confidence,) in rows:
        out.append(int(confidence) if confidence is not None else DEFAULT_CONFIDENCE)
    return out


def _best_phone_confidence(lead: Lead) -> int | None:
    """Highest phone confidence across relational contacts and flat slots."""
    scores: list[int] = []
    lead_id = getattr(lead, "id", None)
    if isinstance(lead_id, int):
        scores.extend(_relational_phone_confidences(lead_id))
    if _use_flat_contact_fields(lead):
        scores.extend(_flat_phone_confidences(lead))
    if not scores:
        return None
    return max(scores)


def _phone_reachability_points(best_confidence: int | None) -> float:
    from app.services.phone_confidence_service import MIN_VIABLE_CONFIDENCE

    if best_confidence is None or best_confidence < MIN_VIABLE_CONFIDENCE:
        return 0.0
    return BEST_PHONE_MAX_POINTS * (best_confidence / 100.0)


def _has_flat_email(lead: Lead) -> bool:
    for slot in range(1, 6):
        raw = getattr(lead, f"email_{slot}", None)
        if isinstance(raw, str) and raw.strip():
            return True
    return False


def _email_reachability(lead: Lead) -> tuple[float, bool, bool]:
    """Return (points, has_email, is_owner_or_primary)."""
    has_flat = _has_flat_email(lead) if _use_flat_contact_fields(lead) else False
    has_relational = False
    is_owner_or_primary = False
    lead_id = getattr(lead, "id", None)
    if isinstance(lead_id, int):
        from flask import has_app_context
        if not has_app_context():
            lead_id = None
    if isinstance(lead_id, int):
        try:
            from sqlalchemy import text
            from app import db

            rows = db.session.execute(
                text("""
                    SELECT ce.value, pc.role, pc.is_primary
                    FROM contact_emails ce
                    JOIN property_contacts pc ON pc.contact_id = ce.contact_id
                    WHERE pc.property_id = :lead_id
                      AND (pc.role IS NULL OR pc.role <> 'former_owner')
                      AND ce.value IS NOT NULL
                      AND TRIM(ce.value) <> ''
                """),
                {"lead_id": lead_id},
            ).fetchall()
            for value, role, is_primary in rows:
                if not value or not str(value).strip():
                    continue
                has_relational = True
                role_val = role.value if hasattr(role, "value") else role
                if is_primary or (isinstance(role_val, str) and role_val.lower() == "owner"):
                    is_owner_or_primary = True
        except SQLAlchemyError as exc:
            logger.warning("relational email lookup failed for lead %s: %s", lead_id, exc)

    has_email = has_flat or has_relational
    if not has_email:
        return 0.0, False, False
    points = EMAIL_BASE_POINTS
    if is_owner_or_primary:
        points += EMAIL_OWNER_PRIMARY_BONUS
    return min(EMAIL_MAX_POINTS, points), True, is_owner_or_primary


def _contact_reachability_score(lead: Lead) -> tuple[float, dict]:
    """Phones (confidence-weighted) + emails — max CONTACT_REACHABILITY_MAX (50)."""
    best_confidence = _best_phone_confidence(lead)
    phone_points = _phone_reachability_points(best_confidence)
    email_points, has_email, email_owner_primary = _email_reachability(lead)
    contact_total = min(CONTACT_REACHABILITY_MAX, phone_points + email_points)
    return contact_total, {
        "best_phone_confidence": best_confidence,
        "phone_points": round(phone_points, 2),
        "has_email": has_email,
        "email_owner_or_primary": email_owner_primary,
        "email_points": round(email_points, 2),
    }


def _contact_reachability_from_values(
    best_confidence: int | None,
    has_email: bool,
    email_owner_primary: bool,
) -> tuple[float, dict]:
    phone_points = _phone_reachability_points(best_confidence)
    email_points = 0.0
    if has_email:
        email_points = EMAIL_BASE_POINTS
        if email_owner_primary:
            email_points += EMAIL_OWNER_PRIMARY_BONUS
        email_points = min(EMAIL_MAX_POINTS, email_points)
    contact_total = min(CONTACT_REACHABILITY_MAX, phone_points + email_points)
    return contact_total, {
        "best_phone_confidence": best_confidence,
        "phone_points": round(phone_points, 2),
        "has_email": has_email,
        "email_owner_or_primary": email_owner_primary,
        "email_points": round(email_points, 2),
    }


def batch_contact_reachability_scores(leads: list[Lead]) -> dict[int, tuple[float, dict]]:
    """Compute contact reachability for a lead batch with one phone and one email query."""
    lead_ids = [lead.id for lead in leads if isinstance(getattr(lead, "id", None), int)]
    if not lead_ids:
        return {}
    from flask import has_app_context

    from app.services.phone_confidence_service import DEFAULT_CONFIDENCE

    phone_confidences: dict[int, list[int]] = {lead_id: [] for lead_id in lead_ids}
    email_meta: dict[int, tuple[bool, bool]] = {lead_id: (False, False) for lead_id in lead_ids}

    if has_app_context():
        try:
            from sqlalchemy import bindparam, text
            from app import db

            phone_stmt = text("""
                SELECT pc.property_id, cp.confidence_score
                FROM contact_phones cp
                JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                WHERE pc.property_id IN :lead_ids
                  AND (pc.role IS NULL OR pc.role <> 'former_owner')
                  AND cp.value IS NOT NULL
                  AND TRIM(cp.value) <> ''
            """).bindparams(bindparam("lead_ids", expanding=True))
            phone_rows = db.session.execute(
                phone_stmt,
                {"lead_ids": lead_ids},
            ).fetchall()
            for property_id, confidence in phone_rows:
                phone_confidences.setdefault(property_id, []).append(
                    int(confidence) if confidence is not None else DEFAULT_CONFIDENCE
                )
        except SQLAlchemyError as exc:
            logger.warning("batch relational phone confidence lookup failed: %s", exc)

        try:
            from sqlalchemy import bindparam, text
            from app import db

            email_stmt = text("""
                SELECT pc.property_id, ce.value, pc.role, pc.is_primary
                FROM contact_emails ce
                JOIN property_contacts pc ON pc.contact_id = ce.contact_id
                WHERE pc.property_id IN :lead_ids
                  AND (pc.role IS NULL OR pc.role <> 'former_owner')
                  AND ce.value IS NOT NULL
                  AND TRIM(ce.value) <> ''
            """).bindparams(bindparam("lead_ids", expanding=True))
            email_rows = db.session.execute(
                email_stmt,
                {"lead_ids": lead_ids},
            ).fetchall()
            for property_id, value, role, is_primary in email_rows:
                if not value or not str(value).strip():
                    continue
                has_email, is_owner_or_primary = email_meta.get(property_id, (False, False))
                role_val = role.value if hasattr(role, "value") else role
                email_meta[property_id] = (
                    True,
                    is_owner_or_primary
                    or bool(is_primary)
                    or (isinstance(role_val, str) and role_val.lower() == "owner"),
                )
        except SQLAlchemyError as exc:
            logger.warning("batch relational email lookup failed: %s", exc)

    out: dict[int, tuple[float, dict]] = {}
    for lead in leads:
        lead_id = getattr(lead, "id", None)
        if not isinstance(lead_id, int):
            continue
        scores = list(phone_confidences.get(lead_id, []))
        if _use_flat_contact_fields(lead):
            scores.extend(_flat_phone_confidences(lead))
        best_confidence = max(scores) if scores else None
        has_relational_email, email_owner_primary = email_meta.get(lead_id, (False, False))
        has_flat_email = _has_flat_email(lead) if _use_flat_contact_fields(lead) else False
        has_email = has_flat_email or has_relational_email
        out[lead_id] = _contact_reachability_from_values(
            best_confidence,
            has_email,
            email_owner_primary,
        )
    return out


def build_data_quality_breakdown(
    lead: Lead,
    contact_reachability: tuple[float, dict] | None = None,
) -> dict:
    """Structured completeness breakdown for scoring + command center UI."""
    property_score = _property_identity_score(lead)
    contact_score, contact_meta = contact_reachability or _contact_reachability_score(lead)
    missing = identify_missing_data(
        lead,
        best_confidence=contact_meta["best_phone_confidence"],
        has_email=contact_meta["has_email"],
    )
    total = min(100.0, round(property_score + contact_score, 2))
    return {
        "total": total,
        "property": round(property_score, 2),
        "contact": round(contact_score, 2),
        "best_phone_confidence": contact_meta["best_phone_confidence"],
        "has_email": contact_meta["has_email"],
        "email_owner_or_primary": contact_meta["email_owner_or_primary"],
        "missing": missing,
    }


def calculate_data_quality_score(
    lead: Lead,
    contact_reachability: tuple[float, dict] | None = None,
) -> tuple[float, list[str], dict]:
    """Completeness 0–100: ~50 property identity + ~50 contact reachability.

    Returns ``(total_score, missing_field_names, breakdown)``.
    """
    breakdown = build_data_quality_breakdown(lead, contact_reachability=contact_reachability)
    return breakdown["total"], breakdown["missing"], breakdown


def identify_missing_data(
    lead: Lead,
    best_confidence: int | None = None,
    has_email: bool | None = None,
) -> list[str]:
    from app.services.phone_confidence_service import MIN_VIABLE_CONFIDENCE

    if best_confidence is None:
        best_confidence = _best_phone_confidence(lead)
    has_viable_phone = (
        best_confidence is not None and best_confidence >= MIN_VIABLE_CONFIDENCE
    )
    if has_email is None:
        has_email = _email_reachability(lead)[1]

    field_checks = {
        "pin": lambda: lead.county_assessor_pin and str(lead.county_assessor_pin).strip(),
        "property_address": lambda: lead.property_street and lead.property_street.strip(),
        "normalized_address": lambda: lead.property_street and lead.property_street.strip(),
        "owner_name": lambda: (
            (lead.owner_first_name and lead.owner_first_name.strip()) or
            (lead.owner_last_name and lead.owner_last_name.strip())
        ),
        "owner_mailing_address": lambda: lead.mailing_address and lead.mailing_address.strip(),
        "property_type": lambda: lead.property_type and lead.property_type.strip(),
        "assessor_class": lambda: lead.property_type and lead.property_type.strip(),
        "estimated_units": lambda: lead.units is not None,
        "building_sqft": lambda: lead.square_footage is not None,
        "years_owned": lambda: effective_acquisition_date(lead) is not None,
        "neighborhood": lambda: (
            (lead.property_city and lead.property_city.strip()) or
            (lead.property_zip and lead.property_zip.strip())
        ),
        "condo_risk_status": lambda: (
            getattr(lead, "condo_risk_status", None) and lead.condo_risk_status.strip()
        ),
        "building_sale_possible": lambda: (
            getattr(lead, "building_sale_possible", None) and lead.building_sale_possible.strip()
        ),
        "violation_data": lambda: bool(getattr(lead, "violation_data", None)),
        "permit_data": lambda: bool(getattr(lead, "permit_data", None)),
        "tax_data": lambda: bool(getattr(lead, "tax_distress_data", None)),
        "skip_trace_data": lambda: (
            lead.date_skip_traced is not None or bool(lead.phone_1) or bool(lead.email_1)
        ),
        "phone": lambda: has_viable_phone,
        "email": lambda: has_email,
    }
    missing = []
    for field_name in MISSING_DATA_FIELDS:
        check_fn = field_checks.get(field_name)
        if check_fn and not check_fn():
            missing.append(field_name)
    return missing


def calculate_score_tier(total_score: float) -> str:
    if total_score >= TIER_A_MIN:
        return "A"
    if total_score >= TIER_B_MIN:
        return "B"
    if total_score >= TIER_C_MIN:
        return "C"
    return "D"


def extract_top_signals(score_details: dict, lead=None) -> list:
    non_zero = []
    if lead is not None:
        summary = getattr(lead, 'motivation_signal_summary', None) or []
        if isinstance(summary, list):
            for item in summary[:3]:
                pts = item.get('points', 0)
                if pts > 0:
                    non_zero.append({
                        'dimension': item.get('label', item.get('signal_type', 'motivation')),
                        'points': pts,
                    })
    for dim, pts in score_details.items():
        if dim in SCORE_ATTRIBUTION_ONLY_KEYS:
            continue
        if pts <= 0:
            continue
        dim_lower = dim.lower().replace("_", " ")
        if any(term in dim_lower for term in TAX_DISTRESS_FORBIDDEN_TERMS):
            continue
        non_zero.append({"dimension": dim, "points": pts})
    non_zero.sort(key=lambda x: x["points"], reverse=True)
    return non_zero


def bucket_scores(score_details: dict, data_quality_score: float, category: str) -> dict[str, float]:
    """Map rubric dimensions into five 0–100 weighted buckets."""
    if category == "commercial":
        prop_dims = [
            "property_type_fit", "condo_clarity", "building_sale_possible", "building_size_fit",
        ]
        prop_max = sum(COMMERCIAL_MAX_POINTS[d] for d in prop_dims)
        owner_dims = [
            "absentee_owner", "owner_concentration", "ownership_duration",
            "owner_mailing_quality", "structured_motivation",
        ]
        owner_max = (
            COMMERCIAL_MAX_POINTS["absentee_owner"]
            + COMMERCIAL_MAX_POINTS["owner_concentration"]
            + COMMERCIAL_MAX_POINTS["ownership_duration"]
            + 10  # owner_mailing_quality max (residential cap)
            + COMMERCIAL_MAX_POINTS["structured_motivation"]
        )
        loc_max = COMMERCIAL_MAX_POINTS["neighborhood_fit"]
    else:
        prop_dims = [
            "property_type_fit", "unit_count_fit", "property_heuristics",
        ]
        prop_max = (
            RESIDENTIAL_MAX_POINTS["property_type_fit"]
            + RESIDENTIAL_MAX_POINTS["unit_count_fit"]
            + RESIDENTIAL_MAX_POINTS["property_heuristics"]
        )
        owner_dims = [
            "absentee_owner", "owner_mailing_quality", "ownership_duration",
            "structured_motivation",
        ]
        owner_max = (
            RESIDENTIAL_MAX_POINTS["absentee_owner"]
            + RESIDENTIAL_MAX_POINTS["owner_mailing_quality"]
            + RESIDENTIAL_MAX_POINTS["ownership_duration"]
            + RESIDENTIAL_MAX_POINTS["structured_motivation"]
        )
        loc_max = RESIDENTIAL_MAX_POINTS["neighborhood_fit"]

    def _norm(keys: list[str], max_pts: float) -> float:
        if max_pts <= 0:
            return 0.0
        raw = sum(score_details.get(k, 0.0) for k in keys)
        return min(100.0, raw * 100.0 / max_pts)

    enrichment_dims = ["contactability", "property_equity", "ownership_duration", "engagement"]
    enrichment_max = 20 + 25 + 15 + 10
    enrichment_raw = sum(score_details.get(k, 0.0) for k in enrichment_dims)

    return {
        "property_characteristics": _norm(prop_dims, prop_max),
        "data_completeness": min(100.0, data_quality_score),
        "owner_situation": _norm(owner_dims, owner_max),
        "location_desirability": _norm(["neighborhood_fit"], loc_max),
        "data_enrichment": min(100.0, enrichment_raw * 100.0 / enrichment_max),
    }
