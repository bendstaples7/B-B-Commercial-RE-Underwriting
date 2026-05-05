"""Condo Filter Service for commercial property analysis.

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

from sqlalchemy import or_

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

    def run_analysis(self) -> dict:
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
        leads = Lead.query.filter(
            or_(
                Lead.lead_category == 'commercial',
                Lead.property_type.ilike('%mixed%'),
            )
        ).all()

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
        for normalized_addr, group_leads in batch:
            metrics = self._compute_metrics(group_leads)
            result = classify(metrics)

            # Look up existing record for upsert
            analysis = AddressGroupAnalysis.query.filter_by(
                normalized_address=normalized_addr
            ).first()

            if analysis is None:
                analysis = AddressGroupAnalysis(
                    normalized_address=normalized_addr,
                    source_type='commercial',
                )
                db.session.add(analysis)

            # Update automated fields (preserve manual override fields)
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
            has_unit_marker(lead.property_street)
            for lead in group_leads
            if lead.property_street
        )

        # Condo language detection (assessor_class not on Lead model, pass None)
        has_condo_lang = any(
            has_condo_language(lead.property_type, None)
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

    def get_results(self, filters: dict, page: int, per_page: int) -> dict:
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

    def get_detail(self, analysis_id: int) -> dict | None:
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
                'assessor_class': None,
            }
            for lead in analysis.leads.all()
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
    ) -> dict:
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

        # Update override fields
        analysis.manual_override_status = status
        analysis.manual_override_reason = reason
        analysis.manually_reviewed = True

        # Cascade to linked leads
        for lead in analysis.leads.all():
            lead.condo_risk_status = status
            lead.building_sale_possible = building_sale

        db.session.commit()

        return self.get_detail(analysis_id)

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export_csv(self, filters: dict) -> str:
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
