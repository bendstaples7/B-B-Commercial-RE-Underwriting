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

    def analyze_lead(
        self,
        lead_id: int,
        *,
        force: bool = False,
        tax_situs_street: str | None = None,
        candidate_pins: list[str] | None = None,
        apply_closest_pin: bool = False,
        persist_aka: bool = True,
    ) -> dict:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        from app.services.building_ownership_backfill import lead_needs_building_ownership_analysis

        pin_list = [
            str(p).strip()
            for p in (candidate_pins or [])
            if str(p or '').strip()
        ]

        # Skip before mutating PIN/AKA so a stale analysis never writes side effects.
        will_run = force or lead_needs_building_ownership_analysis(lead)
        if not will_run:
            existing = self.get_for_lead(lead_id)
            if existing is not None:
                return {
                    **existing,
                    'lead_id': lead_id,
                    'condo_analysis_id': lead.condo_analysis_id,
                    'skipped': True,
                    'skip_reason': 'analysis_current',
                }

        if apply_closest_pin and pin_list:
            chosen = self._pick_closest_candidate_pin(pin_list)
            from app.services.property_match_review_service import PropertyMatchReviewService
            PropertyMatchReviewService().approve_match(
                lead_id, actor='building_ownership.tax_situs', pin=chosen,
            )
            lead = db.session.get(Lead, lead_id)
        elif persist_aka and tax_situs_street:
            from app.services.property_match_review_service import (
                assessor_street_differs_from_lead,
            )
            if assessor_street_differs_from_lead(lead.property_street, tax_situs_street):
                # Persist AKA without changing marketing street when analyzing pre-Apply.
                from app.services.property_address_service import title_case_address_part
                lead.assessor_aka_street = title_case_address_part(tax_situs_street.strip())
                # Street-only write: clear stale locality from a prior PIN.
                lead.assessor_aka_city = None
                lead.assessor_aka_state = None
                lead.assessor_aka_zip = None
                db.session.add(lead)
                db.session.commit()

        assessor_pins = self._collect_assessor_pins(
            lead,
            tax_situs_street=tax_situs_street,
            seed_pins=pin_list or None,
        )
        metrics = self._compute_metrics_for_lead(lead, assessor_pins)
        result = classify(metrics)

        key_street = (
            (tax_situs_street or '').strip()
            or (getattr(lead, 'assessor_aka_street', None) or '').strip()
            or (lead.property_street or '')
        )
        normalized = normalize_address(key_street)
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
            'tax_situs_street': (tax_situs_street or lead.assessor_aka_street),
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

        recommended = lead.recommended_action
        if recommended is not None and hasattr(recommended, 'value'):
            recommended = recommended.value

        return {
            'lead_id': lead_id,
            'condo_analysis_id': analysis.id,
            'condo_risk_status': lead.condo_risk_status,
            'building_sale_possible': lead.building_sale_possible,
            'county_assessor_pin': lead.county_assessor_pin,
            'assessor_aka_street': getattr(lead, 'assessor_aka_street', None),
            'recommended_action': recommended,
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

    @staticmethod
    def _pick_closest_candidate_pin(pin_list: list[str]) -> str:
        """Stable pin choice when seeds are bare strings (first seed wins)."""
        return pin_list[0]

    def _collect_assessor_pins(
        self,
        lead: Lead,
        *,
        tax_situs_street: str | None = None,
        seed_pins: list[str] | None = None,
    ) -> list[dict]:
        pins: list[dict] = []
        seen: set[str] = set()

        def _add_pin(pin: str | None, extra: dict | None = None) -> None:
            raw = str(pin or '').strip()
            if not raw or raw in seen:
                return
            seen.add(raw)
            row = {**(extra or {}), **self._pin_detail(raw)}
            row['pin'] = raw
            pins.append(row)

        def _add_address_rows(street: str | None) -> None:
            text = (street or '').strip()
            if not text:
                return
            for row in lookup_all_pins_at_address(text):
                _add_pin(row.get('pin'), row)

        for seed in seed_pins or []:
            _add_pin(seed)

        if lead.county_assessor_pin:
            _add_pin(lead.county_assessor_pin)

        connector = connector_for_lead(lead)
        is_cook = (
            connector is not None
            and getattr(connector, 'market', None) == 'cook_county_il'
        )
        if is_cook:
            from app.services.property_match_review_service import street_name_key

            _add_address_rows(lead.property_street)
            aka = (getattr(lead, 'assessor_aka_street', None) or '').strip()
            if aka:
                _add_address_rows(aka)
            situs = (tax_situs_street or '').strip()
            if situs and situs.upper() != (aka or '').upper():
                _add_address_rows(situs)

            # Resolve tax situs from applied PIN when marketing street ladder is empty.
            if lead.county_assessor_pin and hasattr(connector, 'lookup_address_by_pin'):
                try:
                    addr = connector.lookup_address_by_pin(lead.county_assessor_pin) or {}
                    pin_street = (addr.get('property_street') or '').strip()
                    if pin_street:
                        _add_address_rows(pin_street)
                except Exception:
                    logger.debug(
                        'PIN situs lookup failed for lead %s', lead.id, exc_info=True,
                    )

            # Spatial cluster when still thin — only keep nearby PINs on the same
            # street name as marketing / AKA / tax situs (no cross-street fan-out).
            if len(pins) < 2 and lead.property_street:
                try:
                    from app.services.gis.cook_county_parcel_spatial import (
                        lookup_nearby_parcel_candidates,
                    )
                    allowed_names = {
                        k for k in (
                            street_name_key(lead.property_street),
                            street_name_key(aka),
                            street_name_key(situs),
                        ) if k
                    }
                    nearby = lookup_nearby_parcel_candidates(
                        lead.property_street,
                        city=lead.property_city,
                        state=lead.property_state,
                        zip_code=lead.property_zip,
                        limit=8,
                    )
                    for row in nearby:
                        st = (row.get('property_street') or '').strip()
                        if allowed_names and street_name_key(st) not in allowed_names:
                            continue
                        _add_pin(row.get('pin'), row)
                    expand_street = situs or aka or (lead.property_street or '')
                    if expand_street:
                        _add_address_rows(expand_street)
                except Exception:
                    logger.exception(
                        'Spatial PIN collect failed for lead %s', lead.id,
                    )

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

        units = getattr(lead, "units", None)
        try:
            units_int = int(units) if units is not None else None
        except (TypeError, ValueError):
            units_int = None
        is_commercial = (
            str(getattr(lead, "lead_category", "") or "").strip().lower() == "commercial"
        )

        return AddressGroupMetrics(
            property_count=1,
            pin_count=len(pins),
            owner_count=len(owners),
            has_unit_number=has_unit,
            has_condo_language=has_condo_lang,
            missing_pin_count=missing_pin,
            missing_owner_count=missing_owner,
            units=units_int,
            is_commercial=is_commercial,
        )
