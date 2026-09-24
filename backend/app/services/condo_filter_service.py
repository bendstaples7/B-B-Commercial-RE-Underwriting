"""Condo Filter Service for commercial property analysis.

SHELVED — This feature is fully implemented and tested but currently ineffective
because the classification engine depends on data fields (county_assessor_pin,
owner names, property_type/assessor_class) that are mostly null in the current
dataset. With incomplete data, nearly all groups classify as "needs_review".

Prerequisites to make this useful:
  1. Public records integration (county assessor data with PINs, owners, property classes)
  2. Skip tracing interface (fills in owner/contact data)
  3. ~80%+ of commercial leads should have non-null county_assessor_pin and owner names

Once those data sources are connected, re-enable the "Condo Analysis" tab in
frontend/src/components/LeadListPage.tsx — the backend requires no changes.

Orchestrates the full condo filter analysis pipeline: queries commercial
and mixed-use leads, normalizes addresses, groups by building-level address,
computes ownership/PIN metrics, detects condo indicators, applies
deterministic classification rules, and persists results for user review.
"""
import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import exists, or_

from app import db
from app.models.address_group_analysis import AddressGroupAnalysis
from app.models.lead import Lead
from app.services.helpers.address_normalizer import normalize_address
from app.services.helpers.unit_detector import has_unit_marker
from app.services.helpers.condo_language_detector import has_condo_language
from app.services.helpers.classification_engine import (
    AddressGroupMetrics,
    classify,
)

logger = logging.getLogger(__name__)

# Batch size for processing large datasets
_BATCH_SIZE = 500


class CondoFilterService:
    """Manages condo filter analysis, results retrieval, overrides, and export.

    Usage::

        service = CondoFilterService()
        summary = service.run_analysis()
        results = service.get_results(filters={}, page=1, per_page=20)
        detail = service.get_detail(analysis_id=1)
        service.apply_override(analysis_id=1, status='likely_not_condo',
                               building_sale='yes', reason='Verified single owner')
    """

    # ------------------------------------------------------------------
    # Analysis pipeline
    # ------------------------------------------------------------------

    def _visible_analysis_query(self, query, lead_id_scope):
        """Hide groups that only contain leads the caller does not own.

        Orphan rows (no linked leads) stay visible so fixture/unit records
        still list. Admin passes ``lead_id_scope=None`` (no filter).
        """
        if lead_id_scope is None:
            return query
        has_any_lead = exists().where(Lead.condo_analysis_id == AddressGroupAnalysis.id)
        if not lead_id_scope:
            return query.filter(~has_any_lead)
        has_owned_lead = exists().where(
            Lead.condo_analysis_id == AddressGroupAnalysis.id,
            Lead.id.in_(lead_id_scope),
        )
        return query.filter(or_(~has_any_lead, has_owned_lead))

    def run_analysis(self, lead_id_scope=None) -> dict:
        """Run full condo filter analysis on all commercial/mixed-use leads.

        Steps:
        1. Query commercial and mixed-use leads
        2. Normalize addresses and group by building-level address
        3. Compute metrics for each group
        4. Apply classification rules
        5. Upsert AddressGroupAnalysis records
        6. Update linked Lead records

        Returns
        -------
        dict
            Summary with total_groups, total_properties, by_status, and
            by_building_sale counts.
        """
        # Step 1: Query commercial and mixed-use leads
        query = Lead.query.filter(
            or_(
                Lead.lead_category == 'commercial',
                Lead.property_type.ilike('%mixed%'),
            )
        )
        if lead_id_scope is not None:
            if not lead_id_scope:
                leads = []
            else:
                leads = query.filter(Lead.id.in_(lead_id_scope)).all()
        else:
            leads = query.all()

        logger.info("Condo filter analysis: found %d commercial/mixed-use leads", len(leads))

        # Step 2: Group by normalized address (skip null property_street)
        groups = defaultdict(list)
        for lead in leads:
            if not lead.property_street:
                logger.debug("Skipping lead %s with null property_street", lead.id)
                continue
            normalized = normalize_address(lead.property_street)
            if normalized:
                groups[normalized].append(lead)

        logger.info("Condo filter analysis: grouped into %d address groups", len(groups))

        # Steps 3-6: Process in batches
        summary_by_status = defaultdict(int)
        summary_by_building_sale = defaultdict(int)
        total_properties = 0
        now = datetime.now(timezone.utc)

        group_items = list(groups.items())
        for batch_start in range(0, len(group_items), _BATCH_SIZE):
            batch = group_items[batch_start:batch_start + _BATCH_SIZE]
            self._process_batch(batch, now, summary_by_status, summary_by_building_sale)
            total_properties += sum(len(group_leads) for _, group_leads in batch)
            db.session.commit()

        return {
            'total_groups': len(groups),
            'total_properties': total_properties,
            'by_status': dict(summary_by_status),
            'by_building_sale': dict(summary_by_building_sale),
        }

    def _process_batch(
        self,
        batch: list[tuple[str, list]],
        now: datetime,
        summary_by_status: dict,
        summary_by_building_sale: dict,
    ) -> None:
        """Process a batch of address groups."""
        existing_by_address = {
            analysis.normalized_address: analysis
            for analysis in AddressGroupAnalysis.query.filter(
                AddressGroupAnalysis.normalized_address.in_(
                    [normalized_addr for normalized_addr, _group in batch]
                )
            ).all()
        }
        linked_by_analysis_id: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
        existing_ids = [
            analysis.id for analysis in existing_by_address.values()
            if analysis.id is not None
        ]
        if existing_ids:
            for analysis_id, lead_id, owner_user_id in (
                db.session.query(Lead.condo_analysis_id, Lead.id, Lead.owner_user_id)
                .filter(Lead.condo_analysis_id.in_(existing_ids))
                .all()
            ):
                linked_by_analysis_id[analysis_id].append((lead_id, owner_user_id))

        for normalized_addr, group_leads in batch:
            metrics = self._compute_metrics(group_leads)
            result = classify(metrics)

            # Look up existing record for upsert
            analysis = existing_by_address.get(normalized_addr)

            if analysis is None:
                analysis = AddressGroupAnalysis(
                    normalized_address=normalized_addr,
                    source_type='commercial',
                )
                db.session.add(analysis)

            group_ids = {lead.id for lead in group_leads}
            group_owners = {getattr(lead, 'owner_user_id', None) for lead in group_leads}
            foreign_linked = False
            if getattr(analysis, 'id', None) is not None:
                for lead_id, owner_user_id in linked_by_analysis_id.get(analysis.id, []):
                    if lead_id in group_ids:
                        continue
                    if owner_user_id not in group_owners:
                        foreign_linked = True
                        break
            if foreign_linked:
                summary_by_status[result.condo_risk_status] += 1
                summary_by_building_sale[result.building_sale_possible] += 1
                continue

            analysis.property_count = metrics.property_count
            analysis.pin_count = metrics.pin_count
            analysis.owner_count = metrics.owner_count
            analysis.has_unit_number = metrics.has_unit_number
            analysis.has_condo_language = metrics.has_condo_language
            analysis.missing_pin_count = metrics.missing_pin_count
            analysis.missing_owner_count = metrics.missing_owner_count
            analysis.condo_risk_status = result.condo_risk_status
            analysis.building_sale_possible = result.building_sale_possible
            analysis.analysis_details = {
                'triggered_rules': result.triggered_rules,
                'reason': result.reason,
                'confidence': result.confidence,
            }
            analysis.analyzed_at = now

            # Flush to get the ID for new records
            db.session.flush()

            # Determine effective status for linked leads
            if analysis.manually_reviewed and analysis.manual_override_status:
                # Overridden records: keep existing lead values unchanged
                # (override was already applied via apply_override)
                for lead in group_leads:
                    lead.condo_analysis_id = analysis.id
            else:
                for lead in group_leads:
                    lead.condo_risk_status = result.condo_risk_status
                    lead.building_sale_possible = result.building_sale_possible
                    lead.condo_analysis_id = analysis.id

            # Track summary counts (always use automated classification)
            summary_by_status[result.condo_risk_status] += 1
            summary_by_building_sale[result.building_sale_possible] += 1

    def _compute_metrics(self, group_leads: list) -> AddressGroupMetrics:
        """Compute address group metrics from a list of leads."""
        property_count = len(group_leads)

        # Unique non-null PINs
        pins = set()
        missing_pin_count = 0
        for lead in group_leads:
            if lead.county_assessor_pin:
                pins.add(lead.county_assessor_pin.strip())
            else:
                missing_pin_count += 1

        # Unique non-null owner name combinations
        owners = set()
        missing_owner_count = 0
        for lead in group_leads:
            owner_parts = []
            if lead.owner_first_name:
                owner_parts.append(lead.owner_first_name.strip().lower())
            if lead.owner_last_name:
                owner_parts.append(lead.owner_last_name.strip().lower())
            if lead.owner_2_first_name:
                owner_parts.append(lead.owner_2_first_name.strip().lower())
            if lead.owner_2_last_name:
                owner_parts.append(lead.owner_2_last_name.strip().lower())

            if owner_parts:
                owners.add(tuple(sorted(owner_parts)))
            else:
                missing_owner_count += 1

        # Unit marker detection
        has_unit = any(
            has_unit_marker(
                lead.property_street,
                getattr(lead, 'address_2', None),
            )
            for lead in group_leads
            if lead.property_street or getattr(lead, 'address_2', None)
        )

        # Condo language detection
        has_condo_lang = any(
            has_condo_language(lead.property_type, getattr(lead, 'assessor_class', None))
            for lead in group_leads
        )

        return AddressGroupMetrics(
            property_count=property_count,
            pin_count=len(pins),
            owner_count=len(owners),
            has_unit_number=has_unit,
            has_condo_language=has_condo_lang,
            missing_pin_count=missing_pin_count,
            missing_owner_count=missing_owner_count,
        )

    # ------------------------------------------------------------------
    # Results retrieval
    # ------------------------------------------------------------------

    def get_results(self, filters: dict, page: int, per_page: int, lead_id_scope=None) -> dict:
        """Get paginated, filtered analysis results.

        Parameters
        ----------
        filters : dict
            Optional filter keys: condo_risk_status, building_sale_possible,
            manually_reviewed.
        page : int
            Page number (1-indexed).
        per_page : int
            Results per page.

        Returns
        -------
        dict
            Paginated response with results, total, page, per_page, pages.
        """
        query = AddressGroupAnalysis.query

        if 'condo_risk_status' in filters:
            query = query.filter(
                AddressGroupAnalysis.condo_risk_status == filters['condo_risk_status']
            )
        if 'building_sale_possible' in filters:
            query = query.filter(
                AddressGroupAnalysis.building_sale_possible == filters['building_sale_possible']
            )
        if 'manually_reviewed' in filters:
            query = query.filter(
                AddressGroupAnalysis.manually_reviewed == filters['manually_reviewed']
            )

        query = self._visible_analysis_query(query, lead_id_scope)
        query = query.order_by(AddressGroupAnalysis.analyzed_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        results = [self._serialize_analysis(a) for a in pagination.items]

        return {
            'results': results,
            'total': pagination.total,
            'page': pagination.page,
            'per_page': pagination.per_page,
            'pages': pagination.pages,
        }

    # ------------------------------------------------------------------
    # Detail retrieval
    # ------------------------------------------------------------------

    def get_detail(self, analysis_id: int, lead_id_scope=None) -> dict | None:
        """Get full detail for a single address group including linked leads.

        Parameters
        ----------
        analysis_id : int
            ID of the AddressGroupAnalysis record.

        Returns
        -------
        dict or None
            Full record with linked leads, or None if not found.
        """
        analysis = db.session.get(AddressGroupAnalysis, analysis_id)
        if analysis is None:
            return None

        linked = analysis.leads.all()
        if lead_id_scope is not None:
            if linked and not any(lead.id in lead_id_scope for lead in linked):
                return None
            linked = [lead for lead in linked if lead.id in lead_id_scope]

        detail = self._serialize_analysis(analysis)
        detail['leads'] = [
            {
                'id': lead.id,
                'property_street': lead.property_street,
                'county_assessor_pin': lead.county_assessor_pin,
                'owner_first_name': lead.owner_first_name,
                'owner_last_name': lead.owner_last_name,
                'owner_2_first_name': lead.owner_2_first_name,
                'owner_2_last_name': lead.owner_2_last_name,
                'property_type': lead.property_type,
                'assessor_class': getattr(lead, 'assessor_class', None),
            }
            for lead in linked
        ]
        return detail

    # ------------------------------------------------------------------
    # Manual override
    # ------------------------------------------------------------------

    def apply_override(
        self,
        analysis_id: int,
        status: str,
        building_sale: str,
        reason: str,
        lead_id_scope=None,
    ) -> dict | None:
        """Apply manual override to an address group and cascade to linked leads.

        Parameters
        ----------
        analysis_id : int
            ID of the AddressGroupAnalysis record.
        status : str
            New condo_risk_status value.
        building_sale : str
            New building_sale_possible value.
        reason : str
            Justification for the override.

        Returns
        -------
        dict
            Updated analysis record with linked leads.
        """
        analysis = db.session.get(AddressGroupAnalysis, analysis_id)
        if analysis is None:
            return None

        linked = analysis.leads.all()
        if lead_id_scope is not None:
            if not linked or any(lead.id not in lead_id_scope for lead in linked):
                return None

        # Update override fields on the analysis record itself
        analysis.manual_override_status = status
        analysis.manual_override_reason = reason
        analysis.manually_reviewed = True
        analysis.condo_risk_status = status
        analysis.building_sale_possible = building_sale

        # Cascade to linked leads
        for lead in linked:
            lead.condo_risk_status = status
            lead.building_sale_possible = building_sale

        db.session.commit()

        return self.get_detail(analysis_id, lead_id_scope=lead_id_scope)

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export_csv(self, filters: dict, lead_id_scope=None) -> str:
        """Generate CSV content for filtered analysis results.

        Parameters
        ----------
        filters : dict
            Same filter keys as get_results.

        Returns
        -------
        str
            CSV content as a string.
        """
        query = AddressGroupAnalysis.query

        if 'condo_risk_status' in filters:
            query = query.filter(
                AddressGroupAnalysis.condo_risk_status == filters['condo_risk_status']
            )
        if 'building_sale_possible' in filters:
            query = query.filter(
                AddressGroupAnalysis.building_sale_possible == filters['building_sale_possible']
            )
        if 'manually_reviewed' in filters:
            query = query.filter(
                AddressGroupAnalysis.manually_reviewed == filters['manually_reviewed']
            )

        query = self._visible_analysis_query(query, lead_id_scope)
        analyses = query.order_by(AddressGroupAnalysis.analyzed_at.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow([
            'normalized_address',
            'representative_property_address',
            'pin_count',
            'owner_count',
            'condo_risk_status',
            'building_sale_possible',
            'owner_names',
            'mailing_addresses',
            'property_ids',
            'pins',
            'reason',
            'confidence',
        ])

        # Data rows
        for analysis in analyses:
            leads = analysis.leads.all()
            if lead_id_scope is not None:
                leads = [lead for lead in leads if lead.id in lead_id_scope]

            # Representative address: first lead's property_street
            representative_address = leads[0].property_street if leads else ''

            # Concatenate multi-valued fields with pipe delimiter
            owner_names = ' | '.join(
                self._format_owner_name(lead)
                for lead in leads
                if self._format_owner_name(lead)
            )
            mailing_addresses = ' | '.join(
                lead.mailing_address
                for lead in leads
                if lead.mailing_address
            )
            property_ids = ' | '.join(
                str(lead.id) for lead in leads
            )
            pins = ' | '.join(
                lead.county_assessor_pin
                for lead in leads
                if lead.county_assessor_pin
            )

            # Extract reason and confidence from analysis_details
            details = analysis.analysis_details or {}
            reason = details.get('reason', '')
            confidence = details.get('confidence', '')

            writer.writerow([
                analysis.normalized_address,
                representative_address,
                analysis.pin_count,
                analysis.owner_count,
                analysis.condo_risk_status,
                analysis.building_sale_possible,
                owner_names,
                mailing_addresses,
                property_ids,
                pins,
                reason,
                confidence,
            ])

        return output.getvalue()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _serialize_analysis(self, analysis: AddressGroupAnalysis) -> dict:
        """Serialize an AddressGroupAnalysis record to a dict."""
        return {
            'id': analysis.id,
            'normalized_address': analysis.normalized_address,
            'source_type': analysis.source_type,
            'property_count': analysis.property_count,
            'pin_count': analysis.pin_count,
            'owner_count': analysis.owner_count,
            'has_unit_number': analysis.has_unit_number,
            'has_condo_language': analysis.has_condo_language,
            'missing_pin_count': analysis.missing_pin_count,
            'missing_owner_count': analysis.missing_owner_count,
            'condo_risk_status': analysis.condo_risk_status,
            'building_sale_possible': analysis.building_sale_possible,
            'analysis_details': analysis.analysis_details,
            'manually_reviewed': analysis.manually_reviewed,
            'manual_override_status': analysis.manual_override_status,
            'manual_override_reason': analysis.manual_override_reason,
            'analyzed_at': analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
            'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
            'updated_at': analysis.updated_at.isoformat() if analysis.updated_at else None,
        }

    @staticmethod
    def _format_owner_name(lead: Lead) -> str:
        """Format owner name(s) from a lead record."""
        parts = []
        if lead.owner_first_name or lead.owner_last_name:
            name = ' '.join(
                p for p in [lead.owner_first_name, lead.owner_last_name] if p
            )
            parts.append(name)
        if lead.owner_2_first_name or lead.owner_2_last_name:
            name = ' '.join(
                p for p in [lead.owner_2_first_name, lead.owner_2_last_name] if p
            )
            parts.append(name)
        return ', '.join(parts)
