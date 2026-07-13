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
    match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', text)
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
    if isinstance(acquisition, date):
        return acquisition
    sale_text = getattr(lead, 'most_recent_sale', None)
    if isinstance(sale_text, str):
        return parse_sale_date_string(sale_text)
    return None


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


def display_most_recent_sale(lead: Lead) -> str | None:
    """Single UI display value: prefer acquisition_date, else import most_recent_sale."""
    acquisition = getattr(lead, 'acquisition_date', None)
    if isinstance(acquisition, date):
        return acquisition.strftime('%m/%d/%Y')
    sale_text = getattr(lead, 'most_recent_sale', None)
    if not sale_text or not str(sale_text).strip():
        return None
    parsed = parse_sale_date_string(str(sale_text))
    if parsed:
        return parsed.strftime('%m/%d/%Y')
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


def resolve_sale_date_meta(lead: Lead) -> dict:
    """Latest audit metadata for sale-date fields shown in Command Center."""
    null_meta = {'last_updated_at': None, 'source': None}
    from flask import has_app_context

    if not has_app_context():
        return null_meta

    from app.models.lead import LeadAuditTrail

    lead_id = getattr(lead, 'id', None)
    if not isinstance(lead_id, int):
        return null_meta

    preferred_field = (
        'acquisition_date'
        if isinstance(getattr(lead, 'acquisition_date', None), date)
        else 'most_recent_sale'
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
    if row is None:
        return null_meta

    return {
        'last_updated_at': row.changed_at.isoformat() if row.changed_at else None,
        'source': humanize_sale_date_source(row.changed_by),
    }


def effective_acquisition_date_sql():
    """SQL expression matching effective_acquisition_date() on PostgreSQL."""
    from sqlalchemy import Date, Integer, and_, case, cast
    from sqlalchemy.sql import func

    mrs = Lead.most_recent_sale
    parts = func.regexp_match(mrs, r'(\d{1,2})/(\d{1,2})/(\d{2,4})')
    month = cast(parts[1], Integer)
    day = cast(parts[2], Integer)
    year_raw = cast(parts[3], Integer)
    year = case(
        (year_raw < 100, case((year_raw >= 50, year_raw + 1900), else_=year_raw + 2000)),
        else_=year_raw,
    )
    valid_us = and_(month >= 1, month <= 12, day >= 1, day <= 31)
    us_date = case((valid_us, func.make_date(year, month, day)), else_=None)

    dash_parts = func.regexp_match(mrs, r'(\d{1,2})-(\d{1,2})-(\d{2,4})')
    dash_month = cast(dash_parts[1], Integer)
    dash_day = cast(dash_parts[2], Integer)
    dash_year_raw = cast(dash_parts[3], Integer)
    dash_year = case(
        (dash_year_raw < 100, case((dash_year_raw >= 50, dash_year_raw + 1900), else_=dash_year_raw + 2000)),
        else_=dash_year_raw,
    )
    valid_dash = and_(dash_month >= 1, dash_month <= 12, dash_day >= 1, dash_day <= 31)
    dash_date = case((valid_dash, func.make_date(dash_year, dash_month, dash_day)), else_=None)

    parsed = case(
        (mrs.op('~')(r'^\d{4}-\d{2}-\d{2}'), cast(func.substring(mrs, 1, 10), Date)),
        (mrs.op('~')(r'\d{1,2}/\d{1,2}/\d{2,4}'), us_date),
        (mrs.op('~')(r'\d{1,2}-\d{1,2}-\d{2,4}'), dash_date),
        else_=None,
    )
    return func.coalesce(Lead.acquisition_date, parsed)


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


def _relational_phone_confidences(lead_id: int) -> list[int]:
    """Best-effort DB read of ContactPhone confidence for a property lead."""
    from app.services.phone_confidence_service import DEFAULT_CONFIDENCE

    try:
        from sqlalchemy import text
        from app import db

        rows = db.session.execute(
            text("""
                SELECT cp.confidence_score
                FROM contact_phones cp
                JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                WHERE pc.property_id = :lead_id
                  AND cp.value IS NOT NULL
                  AND TRIM(cp.value) <> ''
            """),
            {"lead_id": lead_id},
        ).fetchall()
    except Exception as exc:
        logger.debug("relational phone confidence lookup failed for lead %s: %s", lead_id, exc)
        return []

    out: list[int] = []
    for (confidence,) in rows:
        out.append(int(confidence) if confidence is not None else DEFAULT_CONFIDENCE)
    return out


def _best_phone_confidence(lead: Lead) -> int | None:
    """Highest phone confidence across relational contacts and flat slots."""
    scores = list(_flat_phone_confidences(lead))
    lead_id = getattr(lead, "id", None)
    if isinstance(lead_id, int):
        scores.extend(_relational_phone_confidences(lead_id))
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
    has_flat = _has_flat_email(lead)
    has_relational = False
    is_owner_or_primary = False
    lead_id = getattr(lead, "id", None)
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
        except Exception as exc:
            logger.debug("relational email lookup failed for lead %s: %s", lead_id, exc)

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


def build_data_quality_breakdown(lead: Lead) -> dict:
    """Structured completeness breakdown for scoring + command center UI."""
    property_score = _property_identity_score(lead)
    contact_score, contact_meta = _contact_reachability_score(lead)
    missing = identify_missing_data(lead)
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


def calculate_data_quality_score(lead: Lead) -> tuple[float, list[str], dict]:
    """Completeness 0–100: ~50 property identity + ~50 contact reachability.

    Returns ``(total_score, missing_field_names, breakdown)``.
    """
    breakdown = build_data_quality_breakdown(lead)
    return breakdown["total"], breakdown["missing"], breakdown


def identify_missing_data(lead: Lead) -> list[str]:
    best_confidence = _best_phone_confidence(lead)
    from app.services.phone_confidence_service import MIN_VIABLE_CONFIDENCE

    has_viable_phone = (
        best_confidence is not None and best_confidence >= MIN_VIABLE_CONFIDENCE
    )
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
