"""Point-based scoring rubric for residential and commercial leads.

Pure functions — no DB access. Used by LeadScoringEngine for dimension breakdowns.
"""
import json
import logging
import re
from datetime import date, datetime
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
    "contactability": 20,
    "property_equity": 25,
    "ownership_duration": 15,
    "engagement": 10,
}

DATA_QUALITY_FIELDS = {
    "has_pin": 20,
    "has_property_address": 15,
    "has_normalized_address": 10,
    "has_owner_name": 15,
    "has_owner_mailing_address": 15,
    "has_property_type_or_assessor_class": 10,
    "has_estimated_unit_count_or_building_size": 10,
    "has_source_reference": 5,
}

MISSING_DATA_FIELDS = [
    "pin", "property_address", "normalized_address", "owner_name",
    "owner_mailing_address", "property_type", "assessor_class",
    "estimated_units", "building_sqft", "years_owned", "neighborhood",
    "condo_risk_status", "building_sale_possible", "violation_data",
    "permit_data", "tax_data", "skip_trace_data",
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
    if lead.acquisition_date:
        return lead.acquisition_date
    return parse_sale_date_string(getattr(lead, 'most_recent_sale', None))


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
    details["existing_notes_motivation"] = notes_motivation_score(
        lead, max_points=RESIDENTIAL_MAX_POINTS["existing_notes_motivation"]
    )
    details["manual_priority"] = manual_priority_score(
        lead, max_points=RESIDENTIAL_MAX_POINTS["manual_priority"]
    )
    details["source_type_distress"] = source_type_distress_score(lead)
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
    details["existing_notes_motivation"] = notes_motivation_score(
        lead, max_points=COMMERCIAL_MAX_POINTS["existing_notes_motivation"]
    )
    details["manual_priority"] = manual_priority_score(
        lead, max_points=COMMERCIAL_MAX_POINTS["manual_priority"]
    )
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


def calculate_data_quality_score(lead: Lead) -> tuple[float, list[str]]:
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
    return score, identify_missing_data(lead)


def identify_missing_data(lead: Lead) -> list[str]:
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
        "violation_data": lambda: False,
        "permit_data": lambda: False,
        "tax_data": lambda: False,
        "skip_trace_data": lambda: (
            lead.date_skip_traced is not None or bool(lead.phone_1) or bool(lead.email_1)
        ),
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


def extract_top_signals(score_details: dict) -> list:
    non_zero = []
    for dim, pts in score_details.items():
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
        owner_dims = ["absentee_owner", "owner_concentration", "ownership_duration", "owner_mailing_quality"]
        owner_max = (
            COMMERCIAL_MAX_POINTS["absentee_owner"]
            + COMMERCIAL_MAX_POINTS["owner_concentration"]
            + COMMERCIAL_MAX_POINTS["ownership_duration"]
            + 10  # owner_mailing_quality max (residential cap)
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
            "existing_notes_motivation", "manual_priority", "source_type_distress",
        ]
        owner_max = (
            RESIDENTIAL_MAX_POINTS["absentee_owner"]
            + RESIDENTIAL_MAX_POINTS["owner_mailing_quality"]
            + RESIDENTIAL_MAX_POINTS["ownership_duration"]
            + RESIDENTIAL_MAX_POINTS["existing_notes_motivation"]
            + RESIDENTIAL_MAX_POINTS["manual_priority"]
            + RESIDENTIAL_MAX_POINTS["source_type_distress"]
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
