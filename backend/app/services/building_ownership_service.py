"""Building ownership (condo vs single-owner) analysis for individual leads."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from app import db
from app.models.address_group_analysis import AddressGroupAnalysis
from app.models.lead import Lead
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.services.condo_filter_service import CondoFilterService
from app.services.gis.cook_county_gis_connector import lookup_all_pins_at_address
from app.services.gis.routing import connector_for_lead
from app.services.helpers.address_normalizer import normalize_address
from app.services.helpers.classification_engine import AddressGroupMetrics, classify
from app.services.helpers.condo_language_detector import has_condo_language
from app.services.helpers.cook_county_assessor_class import assessor_class_to_condo_language
from app.services.helpers.unit_detector import has_unit_marker
from app.services.lead_refresh import refresh_lead_scoring

logger = logging.getLogger(__name__)


class BuildingOwnershipService:
    """Per-lead building ownership / condo classification."""

    def __init__(self) -> None:
        self._condo_filter = CondoFilterService()

    def analyze_lead(self, lead_id: int) -> dict:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        assessor_pins = self._collect_assessor_pins(lead)
        metrics = self._compute_metrics_for_lead(lead, assessor_pins)
        result = classify(metrics)

        normalized = normalize_address(lead.property_street or '')
        if not normalized:
            raise ValueError('Lead has no property street for building analysis')

        analysis = AddressGroupAnalysis.query.filter_by(normalized_address=normalized).first()
        if analysis is None:
            analysis = AddressGroupAnalysis(normalized_address=normalized, source_type='commercial')
            db.session.add(analysis)

        now = datetime.now(timezone.utc)
        analysis.property_count = 1
        analysis.pin_count = metrics.pin_count
        analysis.owner_count = metrics.owner_count
        analysis.has_unit_number = metrics.has_unit_number
        analysis.has_condo_language = metrics.has_condo_language
        analysis.missing_pin_count = metrics.missing_pin_count
        analysis.missing_owner_count = metrics.missing_owner_count
        if not (analysis.manually_reviewed and analysis.manual_override_status):
            analysis.condo_risk_status = result.condo_risk_status
            analysis.building_sale_possible = result.building_sale_possible
        analysis.analysis_details = {
            'triggered_rules': result.triggered_rules,
            'reason': result.reason,
            'confidence': result.confidence,
            'assessor_pins': assessor_pins,
        }
        analysis.analyzed_at = now
        db.session.flush()

        if not (analysis.manually_reviewed and analysis.manual_override_status):
            lead.condo_risk_status = result.condo_risk_status
            lead.building_sale_possible = result.building_sale_possible
        lead.condo_analysis_id = analysis.id
        db.session.commit()

        refresh_lead_scoring(lead_id)
        db.session.refresh(lead)

        return {
            'lead_id': lead_id,
            'condo_analysis_id': analysis.id,
            'condo_risk_status': lead.condo_risk_status,
            'building_sale_possible': lead.building_sale_possible,
            'recommended_action': lead.recommended_action.value if lead.recommended_action else None,
            'analysis_details': analysis.analysis_details,
            'classification': {
                'condo_risk_status': result.condo_risk_status,
                'building_sale_possible': result.building_sale_possible,
                'reason': result.reason,
                'confidence': result.confidence,
                'triggered_rules': result.triggered_rules,
            },
        }

    def get_for_lead(self, lead_id: int) -> dict | None:
        lead = db.session.get(Lead, lead_id)
        if lead is None or not lead.condo_analysis_id:
            return None
        detail = self._condo_filter.get_detail(lead.condo_analysis_id)
        if detail is None:
            return None
        detail['lead_id'] = lead_id
        detail['assessor_class'] = getattr(lead, 'assessor_class', None)
        return detail

    def apply_override(
        self,
        lead_id: int,
        status: str,
        building_sale: str,
        reason: str,
    ) -> dict:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')
        if not lead.condo_analysis_id:
            raise ValueError('Lead has no building ownership analysis')
        self._condo_filter.apply_override(
            lead.condo_analysis_id, status, building_sale, reason,
        )
        refresh_lead_scoring(lead_id)
        return self.get_for_lead(lead_id) or {}

    def _collect_assessor_pins(self, lead: Lead) -> list[dict]:
        pins: list[dict] = []
        seen: set[str] = set()

        if lead.county_assessor_pin:
            pin = str(lead.county_assessor_pin).strip()
            if pin and pin not in seen:
                seen.add(pin)
                pins.append(self._pin_detail(pin))

        connector = connector_for_lead(lead)
        if connector and getattr(connector, 'market', None) == 'cook_county_il' and lead.property_street:
            for row in lookup_all_pins_at_address(lead.property_street):
                pin = row['pin']
                if pin not in seen:
                    seen.add(pin)
                    pins.append({**row, **self._pin_detail(pin)})

        return pins

    def _pin_detail(self, pin: str) -> dict:
        cache = ParcelUniverseCache.query.filter_by(pin=pin).first()
        prop_class = cache.property_class if cache else None
        return {
            'pin': pin,
            'property_class': prop_class,
            'is_condo_class': assessor_class_to_condo_language(prop_class),
        }

    def _compute_metrics_for_lead(self, lead: Lead, assessor_pins: list[dict]) -> AddressGroupMetrics:
        pins = set()
        if lead.county_assessor_pin:
            pins.add(str(lead.county_assessor_pin).strip())
        for row in assessor_pins:
            if row.get('pin'):
                pins.add(str(row['pin']).strip())

        missing_pin = 0 if pins else 1

        owners = set()
        owner1_parts = []
        for attr in ('owner_first_name', 'owner_last_name'):
            val = getattr(lead, attr, None)
            if val:
                owner1_parts.append(str(val).strip().lower())
        if owner1_parts:
            owners.add(tuple(sorted(owner1_parts)))

        owner2_parts = []
        for attr in ('owner_2_first_name', 'owner_2_last_name'):
            val = getattr(lead, attr, None)
            if val:
                owner2_parts.append(str(val).strip().lower())
        if owner2_parts:
            owners.add(tuple(sorted(owner2_parts)))
        missing_owner = 0 if owners else 1

        assessor_class = getattr(lead, 'assessor_class', None)
        if not assessor_class:
            for row in assessor_pins:
                if row.get('property_class'):
                    assessor_class = row['property_class']
                    break

        has_unit = has_unit_marker(lead.property_street)
        has_condo_lang = (
            has_condo_language(lead.property_type, assessor_class)
            or any(row.get('is_condo_class') for row in assessor_pins)
        )

        return AddressGroupMetrics(
            property_count=1,
            pin_count=len(pins),
            owner_count=len(owners),
            has_unit_number=has_unit,
            has_condo_language=has_condo_lang,
            missing_pin_count=missing_pin,
            missing_owner_count=missing_owner,
        )
