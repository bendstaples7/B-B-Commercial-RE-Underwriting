"""Lead Ingestion Service — orchestrates all lead source type ingestion.

Coordinates ImportJob lifecycle, GIS enrichment, and skip-trace flagging
for platform-wide lead ingestion. DuPage County is the first market; the
service is designed to be market-agnostic.

Requirements: 1.5, 8.1–8.7, 9.1–9.7
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.services.deduplication_engine import DeduplicationEngine
from app.services.gis.base import GISConnector, GISConnectorRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

VALID_SOURCE_TYPES = frozenset({
    "foreclosure", "long_owned", "absentee_owner", "tax_distress", "manual_distress"
})

VALID_DATA_SOURCES = frozenset({
    "dupage_gis", "dupage_sheriff", "dupage_recorder",
    "tax_distress_source", "manual_csv"
})

# Source types that receive GIS enrichment after deduplication
GIS_ENRICHED_SOURCE_TYPES = frozenset({"foreclosure", "tax_distress", "manual_distress"})

# GIS fields populated from parcel lookup (only null fields are updated)
_GIS_FIELDS = [
    'county_assessor_pin',
    'property_type',
    'year_built',
    'square_footage',
    'bedrooms',
    'bathrooms',
    'lot_size',
    'owner_first_name',
    'owner_last_name',
    'mailing_address',
    'mailing_city',
    'mailing_state',
    'mailing_zip',
]


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _append_note(lead, text: str) -> None:
    """Append *text* to lead.notes, separated by '; '.

    If notes is currently null/empty the text is set directly.
    Avoids leading '; ' on a previously-empty notes field.
    """
    existing = lead.notes or ''
    if existing.strip():
        lead.notes = existing + '; ' + text
    else:
        lead.notes = text


def _score_lead_after_commit(lead) -> None:
    """Score a lead immediately after it has been committed to the DB.

    Called at the end of each ingestion batch so leads are always scored
    when first created. Errors are logged and swallowed — a scoring failure
    must never abort an ingestion run.
    """
    try:
        from app.services.deterministic_scoring_engine import DeterministicScoringEngine
        engine = DeterministicScoringEngine()
        engine.recalculate_lead_score(lead)
    except Exception as exc:
        logger.error(
            "Auto-scoring failed for lead %s (source_type=%s): %s",
            getattr(lead, 'id', '?'),
            getattr(lead, 'source_type', '?'),
            exc,
        )


# ---------------------------------------------------------------------------
# LeadIngestionService
# ---------------------------------------------------------------------------

class LeadIngestionService:
    """Central orchestrator for all lead source type ingestion.

    Owns the ImportJob lifecycle, delegates record-level work to per-source
    handlers, and coordinates GIS enrichment via the connector registry.

    Args:
        dedup_engine: Platform-wide DeduplicationEngine instance.
        gis_registry: Dict mapping market identifier → GISConnector instance.
                      Matches the GISConnectorRegistry type from gis/base.py.
    """

    def __init__(
        self,
        dedup_engine: DeduplicationEngine,
        gis_registry: dict,
    ) -> None:
        self.dedup_engine = dedup_engine
        self.gis_registry = gis_registry  # type: dict[str, GISConnector]

    def _gis_connector_for_lead(self, lead):
        """Resolve the GIS connector for a lead (instance registry + global fallback)."""
        from app.services.gis.routing import (
            connector_for_lead,
            parse_city_state_zip_from_address,
            _resolve_market,
        )
        from app.services.gis.base import GISConnectorRegistry

        if (
            not getattr(lead, "property_city", None)
            or not getattr(lead, "property_state", None)
            or not getattr(lead, "property_zip", None)
        ):
            city, state, zip_code = parse_city_state_zip_from_address(
                getattr(lead, "property_street", None) or ""
            )
            if city and not getattr(lead, "property_city", None):
                lead.property_city = city
            if state and not getattr(lead, "property_state", None):
                lead.property_state = state
            if zip_code and not getattr(lead, "property_zip", None):
                lead.property_zip = zip_code

        market = _resolve_market(lead)
        if market and market in self.gis_registry:
            return self.gis_registry.get(market)

        # Only use the global connector registry in production wiring where
        # gis_registry *is* GISConnectorRegistry. Tests pass an explicit dict
        # (often empty) and must not fall through to live connectors.
        if self.gis_registry is GISConnectorRegistry:
            return connector_for_lead(lead)
        return None

    # ------------------------------------------------------------------ #
    # Skip-trace flag (Requirement 1.5)                                   #
    # ------------------------------------------------------------------ #

    def _set_skip_trace_flag(self, lead, is_creation: bool) -> None:
        """Set needs_skip_trace on a lead per Requirement 1.5.

        Rule:
        - On creation: True if both phone_1 AND email_1 are null/empty;
          False if at least one is a non-empty string.
        - On update: leave needs_skip_trace unchanged regardless of
          incoming contact data.

        Args:
            lead: The Property/Lead ORM instance being created or updated.
            is_creation: True when the record is newly created; False on update.
        """
        if not is_creation:
            return  # leave unchanged on update

        has_phone = bool(lead.phone_1 and str(lead.phone_1).strip())
        has_email = bool(lead.email_1 and str(lead.email_1).strip())
        lead.needs_skip_trace = not (has_phone or has_email)

    # ------------------------------------------------------------------ #
    # Review-required flag (Requirements 5.2–5.4)                         #
    # ------------------------------------------------------------------ #

    def _set_review_required_flag(self, lead, is_creation: bool) -> None:
        """Set or clear review_required based on critical field completeness (Req 5.2–5.4).

        Rule:
        - On creation: set True + reason only when all three of phone_1, email_1,
          county_assessor_pin are null or empty.
        - On update: clear flag (set False, reason=None) if all three fields are now
          populated; otherwise leave flag unchanged.
        """
        has_phone = bool(lead.phone_1 and str(lead.phone_1).strip())
        has_email = bool(lead.email_1 and str(lead.email_1).strip())
        has_pin   = bool(lead.county_assessor_pin and str(lead.county_assessor_pin).strip())

        all_missing = not has_phone and not has_email and not has_pin
        all_present = has_phone and has_email and has_pin

        if is_creation:
            if all_missing:
                lead.review_required = True
                lead.review_reason   = 'Missing phone, email, and county PIN'
            # Otherwise leave False (default) — Req 5.3
        else:
            # On update: clear if all three are now present
            if all_present and lead.review_required:
                lead.review_required = False
                lead.review_reason   = None
            # Otherwise leave review_required unchanged — Req 5.4

    # ------------------------------------------------------------------ #
    # GIS enrichment (Requirements 8.1–8.7)                               #
    # ------------------------------------------------------------------ #

    def _enrich_with_gis(
        self,
        lead,
        connector: GISConnector,
        import_job_id: int | None = None,
    ) -> dict:
        """Attempt a GIS parcel lookup and populate null fields on the lead.

        Lookup strategy (Requirement 8.1):
        1. Try lookup_by_address using lead.property_street.
        2. If no result and lead.county_assessor_pin is set, try lookup_by_pin.

        On match (Requirement 8.2, 8.3):
        - Populate each GIS field on the lead only when the current value is null.
        - Set has_property_match = True.

        On no match (Requirement 8.4):
        - Set needs_skip_trace = True.
        - Append "GIS match not found" to lead.notes.

        On error / timeout (Requirement 8.6):
        - Log the error with property address and source type.
        - Leave GIS fields unchanged.
        - Never raise — caller batch continues.

        Regardless of outcome, record enrichment result in the return dict
        for ImportJob logging (Requirement 8.7).

        Args:
            lead: The Property/Lead ORM instance to enrich.
            connector: Resolved GISConnector for the lead's market.
            import_job_id: ID of the current ImportJob (for logging context).

        Returns:
            Outcome dict containing connector_name, source_type, match_found,
            fields_populated, and error (or None).
        """
        outcome = {
            'connector_name': connector.connector_name,
            'source_type': lead.source_type,
            'match_found': False,
            'fields_populated': 0,
            'error': None,
        }

        try:
            # Primary lookup: by address
            parcel = connector.lookup_by_address(lead.property_street or '')

            # Fallback: by PIN when address lookup returns nothing
            if parcel is None and lead.county_assessor_pin:
                parcel = connector.lookup_by_pin(lead.county_assessor_pin)

            if parcel is None:
                # No match found (Requirement 8.4)
                lead.needs_skip_trace = True
                lead.has_property_match = False          # Req 6.2, 6.3
                _append_note(lead, 'GIS match not found')
                return outcome

            # Match found — populate null fields (Requirement 8.2)
            fields_populated = 0
            for field in _GIS_FIELDS:
                parcel_value = getattr(parcel, field, None)
                current_value = getattr(lead, field, None)
                if parcel_value is not None and current_value is None:
                    setattr(lead, field, parcel_value)
                    fields_populated += 1

            # Mark property match (Requirement 8.3)
            lead.has_property_match = True
            outcome['match_found'] = True
            outcome['fields_populated'] = fields_populated

            if outcome['match_found'] and getattr(lead, 'id', None):
                try:
                    from app import db
                    from app.services.contact_service import ContactService
                    with db.session.begin_nested():
                        ContactService().upsert_owners_from_lead(lead, commit=False)
                except Exception as contact_exc:
                    logger.warning(
                        "Contact upsert after GIS enrich failed for lead_id=%s: %s",
                        lead.id, contact_exc,
                    )

            try:
                from app.services.cook_county_enrichment_service import (
                    maybe_dispatch_after_gis_match,
                )
                maybe_dispatch_after_gis_match(lead, connector)
            except Exception as dispatch_exc:
                logger.warning(
                    "Cook County enrichment dispatch failed for lead %s: %s",
                    getattr(lead, 'id', '?'),
                    dispatch_exc,
                )

        except Exception as exc:
            # Log and continue — never fail the batch (Requirement 8.6)
            logger.error(
                "GIS lookup error for '%s' (source_type=%s, import_job_id=%s): %s",
                lead.property_street,
                lead.source_type,
                import_job_id,
                exc,
            )
            outcome['error'] = str(exc)

        return outcome

    # ------------------------------------------------------------------ #
    # ImportJob lifecycle (Requirements 9.1–9.5, 9.7)                     #
    # ------------------------------------------------------------------ #

    def _create_import_job(
        self,
        owner_user_id: str,
        source_type: str,
    ):
        """Create an ImportJob record and flush to obtain its ID.

        Sets status='in_progress', rows counters to 0, and error_log to [].
        Uses flush() so the job ID is available before the transaction commits.

        Raises any DB exception to the caller so the run can be aborted per
        Requirement 9.2.

        Args:
            owner_user_id: User ID from the ingestion request.
            source_type: Source type being ingested (e.g. 'foreclosure').

        Returns:
            The new ImportJob ORM instance (not yet committed).
        """
        from app import db
        from app.models.import_job import ImportJob

        job = ImportJob(
            user_id=owner_user_id,
            spreadsheet_id='ingestion',   # placeholder — not a spreadsheet import
            sheet_name=source_type,
            source_type=source_type,
            status='in_progress',
            rows_processed=0,
            rows_imported=0,
            rows_skipped=0,
            error_log=[],
        )
        db.session.add(job)
        db.session.flush()  # Populate job.id; caller is responsible for commit
        return job

    def _complete_import_job(
        self,
        job,
        rows_processed: int,
        rows_imported: int,
        rows_skipped: int,
        error_log: list,
    ) -> None:
        """Mark an ImportJob as completed and write final counters.

        Called after all records have been processed successfully.
        Requirement 9.3: status='completed' only after data processing succeeds.

        Args:
            job: The ImportJob ORM instance to update.
            rows_processed: Total rows examined.
            rows_imported: Rows successfully created or updated.
            rows_skipped: Rows skipped (invalid, conflict, etc.).
            error_log: List of error/conflict dicts accumulated during the run.
        """
        job.status = 'completed'
        job.rows_processed = rows_processed
        job.rows_imported = rows_imported
        job.rows_skipped = rows_skipped
        job.error_log = error_log
        job.completed_at = datetime.now(timezone.utc)

    def _fail_import_job(self, job, reason: str) -> None:
        """Mark an ImportJob as failed and record the failure reason.

        Called when an ingestion run fails before completion (Requirement 9.4).

        Args:
            job: The ImportJob ORM instance to update.
            reason: Human-readable description of the failure.
        """
        job.status = 'failed'
        job.error_log = [{'error': reason}]
        job.completed_at = datetime.now(timezone.utc)

    def _score_imported_leads(self, job_id: int) -> None:
        """Score all leads created or updated in this import job.

        Runs the DeterministicScoringEngine against every lead whose
        last_import_job_id matches *job_id*.  Errors per lead are caught
        and logged so a single scoring failure never blocks the rest.

        This is called automatically after each handler commits so that
        leads are scored the moment they enter the database — no manual
        action required.
        """
        from app import db
        from app.models.lead import Property
        from app.services.deterministic_scoring_engine import DeterministicScoringEngine

        try:
            engine = DeterministicScoringEngine()
            leads = (
                db.session.query(Property)
                .filter(Property.last_import_job_id == job_id)
                .all()
            )
            logger.info(
                "Auto-scoring %d leads for import_job_id=%d", len(leads), job_id
            )
            scored = 0
            for lead in leads:
                try:
                    engine.recalculate_lead_score(lead)
                    scored += 1
                except Exception as exc:
                    logger.error(
                        "Scoring failed for lead %s: %s",
                        getattr(lead, 'id', '?'), exc
                    )
            logger.info("Auto-scored %d/%d leads for job %d", scored, len(leads), job_id)
        except Exception as exc:
            logger.error("_score_imported_leads failed for job %d: %s", job_id, exc)

    # ------------------------------------------------------------------ #
    # Long-owned homeowner ingestion (Requirements 3.1–3.6)               #
    # ------------------------------------------------------------------ #

    def ingest_long_owned(self, records: list, owner_user_id: str):
        """Ingest long-owned homeowner records. Returns ImportJob.

        Filters:
        - Skips non-SFR records (Req 3.6)
        - Skips records missing acquisition_date (Req 3.4)
        - Skips records owned < 15 full calendar years (Req 3.4)

        Notes:
        - Appends 'Owned 20+ years' when ownership >= 20 years (Req 3.5)
        - Sets source_type='long_owned', data_source='dupage_gis' (Req 1.1, 1.6)

        Args:
            records: List of raw property dicts from DuPage GIS or equivalent.
            owner_user_id: Platform user ID to assign as lead owner (Req 1.2).

        Returns:
            The completed ImportJob ORM instance.
        """
        from app import db
        from datetime import date

        try:
            job = self._create_import_job(owner_user_id, 'long_owned')
        except Exception as e:
            raise RuntimeError(f"Failed to create ImportJob: {e}") from e

        rows_processed = 0
        rows_imported = 0
        rows_skipped = 0
        error_log = []

        try:
            today = date.today()

            for record in records:
                rows_processed += 1
                pin = record.get('county_assessor_pin', 'unknown')

                # Skip non-SFR records (Req 3.6)
                if not self._is_sfr(record):
                    error_log.append({
                        'reason': 'non-SFR assessor classification',
                        'pin': pin,
                        'row': rows_processed,
                    })
                    rows_skipped += 1
                    continue

                # Skip records missing acquisition_date (Req 3.4)
                acquisition_date = record.get('acquisition_date')
                if not acquisition_date:
                    error_log.append({
                        'reason': 'missing acquisition_date',
                        'pin': pin,
                        'row': rows_processed,
                    })
                    rows_skipped += 1
                    continue

                # Parse acquisition_date if it's a string
                if isinstance(acquisition_date, str):
                    from datetime import datetime as dt
                    try:
                        acquisition_date = dt.strptime(acquisition_date, '%Y-%m-%d').date()
                    except ValueError:
                        error_log.append({
                            'reason': 'unparseable acquisition_date',
                            'pin': pin,
                            'row': rows_processed,
                        })
                        rows_skipped += 1
                        continue

                # Calculate full calendar years owned (Req 3.1)
                years_owned = (today - acquisition_date).days / 365.25

                # Skip < 15 full calendar years (Req 3.4)
                if years_owned < 15:
                    rows_skipped += 1
                    continue

                normalized = self._normalize_long_owned_record(record, owner_user_id, years_owned)

                dedup_result = self.dedup_engine.process_record(normalized, job.id)

                if dedup_result.outcome == 'conflict' and dedup_result.conflict_detail:
                    cd = dedup_result.conflict_detail
                    if cd.get('type') == 'pin_mismatch':
                        error_log.append(cd)
                        rows_skipped += 1
                        continue
                    else:
                        error_log.extend(cd.get('field_conflicts', []))

                lead = dedup_result.lead
                is_creation = (dedup_result.outcome == 'created')

                # Append 20+ years note idempotently (Req 3.5)
                if years_owned >= 20:
                    existing_notes = lead.notes or ''
                    if 'Owned 20+ years' not in existing_notes:
                        _append_note(lead, 'Owned 20+ years')

                self._set_skip_trace_flag(lead, is_creation)
                self._set_review_required_flag(lead, is_creation)
                lead.last_import_job_id = job.id
                db.session.add(lead)

                if dedup_result.outcome == 'conflict':
                    rows_skipped += 1
                else:
                    rows_imported += 1

            db.session.flush()
            self._complete_import_job(job, rows_processed, rows_imported, rows_skipped, error_log)
            db.session.commit()
            # Auto-score all leads created/updated by this job
            self._score_imported_leads(job.id)
        except Exception as e:
            self._fail_import_job(job, str(e))
            db.session.commit()
            raise

        return job

    def _is_sfr(self, record: dict) -> bool:
        """Return True if the record represents a single-family residential property.

        Checks assessor_class_code against known SFR codes for DuPage County.
        Class 202 and the 200-series codes (202–212) are the DuPage single-family
        classifications per the ingestion service configuration (Req 3.6).

        Args:
            record: Raw property dict containing 'assessor_class_code'.

        Returns:
            True if the code is in the SFR set; False otherwise.
        """
        sfr_codes = {'202', '203', '204', '205', '206', '207', '208', '209', '210', '211', '212'}
        code = str(record.get('assessor_class_code', '')).strip()
        return code in sfr_codes

    def _normalize_long_owned_record(self, record: dict, owner_user_id: str, years_owned: float) -> dict:
        """Map a long-owned property record to the canonical lead field dict.

        Sets platform-wide required fields per Requirements 1.1–1.4, 1.6:
        - source_type = 'long_owned'
        - data_source = 'dupage_gis'
        - property_state = 'IL'
        - county = 'DuPage'
        - lead_category = 'residential'

        Args:
            record: Raw property dict from DuPage GIS.
            owner_user_id: User ID to assign as lead owner.
            years_owned: Calculated ownership duration (used for note logic upstream).

        Returns:
            Normalized dict suitable for DeduplicationEngine.process_record().
        """
        return {
            'property_street': record.get('property_street'),
            'property_city': record.get('property_city'),
            'property_state': 'IL',
            'property_zip': record.get('property_zip'),
            'owner_first_name': record.get('owner_first_name'),
            'owner_last_name': record.get('owner_last_name'),
            'mailing_address': record.get('mailing_address'),
            'mailing_city': record.get('mailing_city'),
            'mailing_state': record.get('mailing_state'),
            'mailing_zip': record.get('mailing_zip'),
            'county_assessor_pin': record.get('county_assessor_pin'),
            'acquisition_date': record.get('acquisition_date'),
            'source_type': 'long_owned',
            'data_source': 'dupage_gis',
            'county': 'DuPage',
            'lead_category': 'residential',
            'owner_user_id': owner_user_id,
        }

    # ------------------------------------------------------------------ #
    # Absentee owner ingestion (Requirements 4.1–4.5)                     #
    # ------------------------------------------------------------------ #

    def ingest_absentee_owner(self, records: list, owner_user_id: str):
        """Ingest absentee owner records. Returns ImportJob.

        Filters:
        - Skips non-SFR records (Req 4.5)
        - Skips records where normalized property address equals normalized
          mailing address (Req 4.1)

        Notes:
        - Sets source_type='absentee_owner', data_source='dupage_gis' (Req 1.1, 1.6)
        - Sets mailing_address, mailing_city, mailing_state, mailing_zip (Req 4.2)
        - When property also qualifies as long-owned (≥ 15 years), keeps
          source_type='absentee_owner' and appends 'Long-owned absentee' to notes
          (Req 4.4)

        Args:
            records: List of raw property dicts from DuPage GIS.
            owner_user_id: Platform user ID to assign as lead owner (Req 1.2).

        Returns:
            The completed ImportJob ORM instance.
        """
        from app import db
        from datetime import date

        try:
            job = self._create_import_job(owner_user_id, 'absentee_owner')
        except Exception as e:
            raise RuntimeError(f"Failed to create ImportJob: {e}") from e

        rows_processed = 0
        rows_imported = 0
        rows_skipped = 0
        error_log = []

        try:
            today = date.today()

            for record in records:
                rows_processed += 1
                pin = record.get('county_assessor_pin', 'unknown')

                # Skip non-SFR records (Req 4.5)
                if not self._is_sfr(record):
                    error_log.append({
                        'reason': 'non-SFR assessor classification',
                        'pin': pin,
                        'row': rows_processed,
                    })
                    rows_skipped += 1
                    continue

                # Skip records where normalized addresses are equal (Req 4.1)
                property_addr = record.get('property_street', '') or ''
                mailing_addr = record.get('mailing_address', '') or ''

                norm_prop = self.dedup_engine.normalize_address(property_addr)
                norm_mail = self.dedup_engine.normalize_address(mailing_addr)

                if norm_prop and norm_mail and norm_prop == norm_mail:
                    rows_skipped += 1
                    continue

                # Determine if also long-owned (Req 4.4)
                is_long_owned = False
                acquisition_date = record.get('acquisition_date')
                if acquisition_date:
                    if isinstance(acquisition_date, str):
                        from datetime import datetime as dt
                        try:
                            acquisition_date = dt.strptime(acquisition_date, '%Y-%m-%d').date()
                        except ValueError:
                            acquisition_date = None
                    if acquisition_date:
                        years_owned = (today - acquisition_date).days / 365.25
                        is_long_owned = years_owned >= 15

                normalized = self._normalize_absentee_owner_record(record, owner_user_id)

                dedup_result = self.dedup_engine.process_record(normalized, job.id)

                if dedup_result.outcome == 'conflict' and dedup_result.conflict_detail:
                    cd = dedup_result.conflict_detail
                    if cd.get('type') == 'pin_mismatch':
                        error_log.append(cd)
                        rows_skipped += 1
                        continue
                    else:
                        error_log.extend(cd.get('field_conflicts', []))

                lead = dedup_result.lead
                is_creation = (dedup_result.outcome == 'created')

                # Append Long-owned absentee note idempotently (Req 4.4)
                if is_long_owned:
                    existing_notes = lead.notes or ''
                    if 'Long-owned absentee' not in existing_notes:
                        _append_note(lead, 'Long-owned absentee')

                self._set_skip_trace_flag(lead, is_creation)
                self._set_review_required_flag(lead, is_creation)
                lead.last_import_job_id = job.id
                db.session.add(lead)

                if dedup_result.outcome == 'conflict':
                    rows_skipped += 1
                else:
                    rows_imported += 1

            db.session.flush()
            self._complete_import_job(job, rows_processed, rows_imported, rows_skipped, error_log)
            db.session.commit()
            # Auto-score all leads created/updated by this job
            self._score_imported_leads(job.id)
        except Exception as e:
            self._fail_import_job(job, str(e))
            db.session.commit()
            raise

        return job

    def _normalize_absentee_owner_record(self, record: dict, owner_user_id: str) -> dict:
        """Map an absentee owner property record to the canonical lead field dict.

        Sets platform-wide required fields per Requirements 1.1–1.4, 1.6:
        - source_type = 'absentee_owner'
        - data_source = 'dupage_gis'
        - property_state = 'IL'
        - county = 'DuPage'
        - lead_category = 'residential'

        Also maps mailing address fields per Requirement 4.2.

        Args:
            record: Raw property dict from DuPage GIS.
            owner_user_id: User ID to assign as lead owner.

        Returns:
            Normalized dict suitable for DeduplicationEngine.process_record().
        """
        return {
            'property_street': record.get('property_street'),
            'property_city': record.get('property_city'),
            'property_state': 'IL',
            'property_zip': record.get('property_zip'),
            'owner_first_name': record.get('owner_first_name'),
            'owner_last_name': record.get('owner_last_name'),
            'mailing_address': record.get('mailing_address'),
            'mailing_city': record.get('mailing_city'),
            'mailing_state': record.get('mailing_state'),
            'mailing_zip': record.get('mailing_zip'),
            'county_assessor_pin': record.get('county_assessor_pin'),
            'source_type': 'absentee_owner',
            'data_source': 'dupage_gis',
            'county': 'DuPage',
            'lead_category': 'residential',
            'owner_user_id': owner_user_id,
        }

    # ------------------------------------------------------------------ #
    # Foreclosure / Sheriff Sale ingestion (Requirements 2.1–2.7)         #
    # ------------------------------------------------------------------ #

    def ingest_foreclosure(self, records: list, owner_user_id: str):
        """Ingest foreclosure/sheriff sale records.

        Maps each raw record through _normalize_foreclosure_record, passes the
        normalized dict to DeduplicationEngine.process_record(), and then
        attempts GIS enrichment via the dupage_il connector when available.

        Requirement 9.2: aborts immediately if the ImportJob cannot be created.

        Args:
            records: List of raw foreclosure record dicts from the caller.
            owner_user_id: Platform user ID that will own the created leads.

        Returns:
            The completed (or failed) ImportJob ORM instance.
        """
        from app import db

        # Create ImportJob — abort if creation fails (Req 9.2)
        try:
            job = self._create_import_job(owner_user_id, 'foreclosure')
        except Exception as e:
            raise RuntimeError(f"Failed to create ImportJob: {e}") from e

        rows_processed = 0
        rows_imported = 0
        rows_skipped = 0
        error_log = []

        try:
            for record in records:
                rows_processed += 1
                normalized = self._normalize_foreclosure_record(record, owner_user_id)

                dedup_result = self.dedup_engine.process_record(normalized, job.id)

                if dedup_result.outcome == 'conflict' and dedup_result.conflict_detail:
                    if 'pin_mismatch' in str(dedup_result.conflict_detail.get('type', '')):
                        error_log.append(dedup_result.conflict_detail)
                        rows_skipped += 1
                        continue
                    else:
                        error_log.extend(dedup_result.conflict_detail.get('field_conflicts', []))

                lead = dedup_result.lead
                is_creation = (dedup_result.outcome == 'created')

                # GIS enrichment for foreclosure leads (Req 8.1)
                connector = self._gis_connector_for_lead(lead)
                if connector:
                    gis_outcome = self._enrich_with_gis(lead, connector, job.id)
                    error_log_entry = {
                        'type': 'gis_enrichment',
                        'record': rows_processed,
                        **gis_outcome,
                    }
                    if gis_outcome.get('error'):
                        error_log.append(error_log_entry)

                self._set_skip_trace_flag(lead, is_creation)
                self._set_review_required_flag(lead, is_creation)
                lead.last_import_job_id = job.id
                db.session.add(lead)

                if dedup_result.outcome == 'conflict':
                    rows_skipped += 1
                else:
                    rows_imported += 1

            db.session.flush()
            self._complete_import_job(job, rows_processed, rows_imported, rows_skipped, error_log)
            db.session.commit()
            # Auto-score all leads created/updated by this job
            self._score_imported_leads(job.id)
        except Exception as e:
            self._fail_import_job(job, str(e))
            db.session.commit()
            raise

        return job

    # ------------------------------------------------------------------ #
    # Tax Distress ingestion (Requirements 5.1–5.6)                       #
    # ------------------------------------------------------------------ #

    def ingest_tax_distress(self, records: list, owner_user_id: str):
        """Ingest tax distress records. Returns ImportJob.

        Stores tax distress signal in ``tax_distress_data`` JSON column.
        NEVER writes tax delinquency / sale language to ``notes`` (Req 5.4).
        Applies PIN+address deduplication per Requirement 5.5:
          - Both PIN and address must match → update
          - Only one matches → conflict, skip record

        Args:
            records: List of raw tax distress dicts from the caller.
            owner_user_id: Platform user ID that will own the created leads.

        Returns:
            The completed (or failed) ImportJob ORM instance.
        """
        from app import db
        from app.models.lead import Property

        try:
            job = self._create_import_job(owner_user_id, 'tax_distress')
        except Exception as e:
            raise RuntimeError(f"Failed to create ImportJob: {e}") from e

        rows_processed = 0
        rows_imported = 0
        rows_skipped = 0
        error_log = []

        try:
            for record in records:
                rows_processed += 1

                incoming_pin = record.get('county_assessor_pin')
                incoming_street = record.get('property_street', '') or ''
                incoming_zip = record.get('property_zip', '') or ''

                # Req 5.5: Apply PIN+address deduplication
                # Both must match; conflict if only one matches.
                existing_by_pin = None
                if incoming_pin:
                    existing_by_pin = db.session.query(Property).filter(
                        Property.county_assessor_pin == incoming_pin
                    ).first()

                existing_by_address = self.dedup_engine.find_existing_lead(incoming_street)

                if existing_by_pin and existing_by_address:
                    if existing_by_pin.id != existing_by_address.id:
                        # PIN matches one lead, address matches a different lead → conflict
                        error_log.append({
                            'type': 'tax_distress_conflict',
                            'reason': 'PIN and address match different leads',
                            'incoming_pin': incoming_pin,
                            'incoming_address': incoming_street,
                            'pin_lead_id': existing_by_pin.id,
                            'address_lead_id': existing_by_address.id,
                        })
                        rows_skipped += 1
                        continue
                elif existing_by_pin and not existing_by_address:
                    # PIN matches but street doesn't align → conflict
                    if incoming_street and (existing_by_pin.property_street or '').upper() != incoming_street.upper():
                        error_log.append({
                            'type': 'tax_distress_conflict',
                            'reason': 'PIN matches but address does not',
                            'incoming_pin': incoming_pin,
                            'incoming_address': incoming_street,
                            'existing_lead_id': existing_by_pin.id,
                        })
                        rows_skipped += 1
                        continue
                elif existing_by_address and not existing_by_pin:
                    # Address matches but existing lead has a different PIN → conflict
                    if incoming_pin and existing_by_address.county_assessor_pin and \
                       existing_by_address.county_assessor_pin != incoming_pin:
                        error_log.append({
                            'type': 'tax_distress_conflict',
                            'reason': 'address matches but PIN does not',
                            'incoming_pin': incoming_pin,
                            'existing_pin': existing_by_address.county_assessor_pin,
                            'existing_lead_id': existing_by_address.id,
                        })
                        rows_skipped += 1
                        continue

                normalized = self._normalize_tax_distress_record(record, owner_user_id)

                dedup_result = self.dedup_engine.process_record(normalized, job.id)

                if dedup_result.outcome == 'conflict' and dedup_result.conflict_detail:
                    cd = dedup_result.conflict_detail
                    if cd.get('type') == 'pin_mismatch':
                        error_log.append(cd)
                        rows_skipped += 1
                        continue
                    else:
                        error_log.extend(cd.get('field_conflicts', []))

                lead = dedup_result.lead
                is_creation = (dedup_result.outcome == 'created')

                # GIS enrichment for tax_distress (Req 8.1)
                connector = self._gis_connector_for_lead(lead)
                if connector:
                    gis_outcome = self._enrich_with_gis(lead, connector, job.id)
                    if gis_outcome.get('error'):
                        error_log.append({'type': 'gis_enrichment', 'record': rows_processed, **gis_outcome})

                self._set_skip_trace_flag(lead, is_creation)
                self._set_review_required_flag(lead, is_creation)
                lead.last_import_job_id = job.id
                db.session.add(lead)

                if dedup_result.outcome == 'conflict':
                    rows_skipped += 1
                else:
                    rows_imported += 1

            db.session.flush()
            self._complete_import_job(job, rows_processed, rows_imported, rows_skipped, error_log)
            db.session.commit()
            # Auto-score all leads created/updated by this job
            self._score_imported_leads(job.id)
        except Exception as e:
            self._fail_import_job(job, str(e))
            db.session.commit()
            raise

        return job

    def _normalize_tax_distress_record(self, record: dict, owner_user_id: str) -> dict:
        """Map a tax distress record to the canonical lead field dict.

        Tax distress signal is stored in ``tax_distress_data`` JSON.
        NEVER populate ``notes`` with tax delinquency / sale language (Req 5.4).

        ``tax_distress_data`` keys:
        - ``signal_type``: 'tax_delinquency' or 'tax_sale' (default: 'tax_delinquency')
        - ``delinquent_amount``: source value or null when absent (Req 5.3)
        - ``tax_year``: source value or null when absent (Req 5.3)

        Args:
            record: Raw dict from the caller containing tax distress source data.
            owner_user_id: Platform user ID to assign to owner_user_id (Req 1.2).

        Returns:
            Normalized dict ready for DeduplicationEngine.process_record().
        """
        tax_distress_data = {
            'signal_type': record.get('signal_type', 'tax_delinquency'),
            'delinquent_amount': record.get('delinquent_amount'),  # null if absent (Req 5.3)
            'tax_year': record.get('tax_year'),                    # null if absent (Req 5.3)
        }

        return {
            'property_street': record.get('property_street'),
            'property_city': record.get('property_city'),
            'property_state': 'IL',
            'property_zip': record.get('property_zip'),
            'owner_first_name': record.get('owner_first_name'),
            'owner_last_name': record.get('owner_last_name'),
            'county_assessor_pin': record.get('county_assessor_pin'),
            'source_type': 'tax_distress',       # Req 1.1, 5.1
            'data_source': 'tax_distress_source', # Req 1.6, 5.1
            'county': 'DuPage',                   # Req 1.4
            'lead_category': 'residential',        # Req 1.3
            'owner_user_id': owner_user_id,        # Req 1.2
            'tax_distress_data': tax_distress_data, # Req 5.3, 5.6
            # notes is intentionally omitted — NEVER write tax distress language to notes (Req 5.4)
        }

    def _normalize_foreclosure_record(self, record: dict, owner_user_id: str) -> dict:
        """Map a raw foreclosure record to the canonical lead field dict.

        Field mapping per Requirements 2.1–2.4:
        - property_state is always 'IL' (Req 1.4)
        - county is always 'DuPage' (Req 1.4)
        - source_type is always 'foreclosure' (Req 1.1)
        - data_source is always 'dupage_sheriff' (Req 1.6)
        - lead_category is always 'residential' (Req 1.3)
        - notes assembles case number, sale date, and source URL (Req 2.2–2.4)

        Args:
            record: Raw dict from the caller containing foreclosure source data.
            owner_user_id: Platform user ID to assign to owner_user_id (Req 1.2).

        Returns:
            Normalized dict ready for DeduplicationEngine.process_record().
        """
        notes_parts = []

        # Req 2.2: case number → 'Case: <case_number>'
        if record.get('case_number'):
            notes_parts.append(f"Case: {record['case_number']}")

        # Req 2.3: sale date → 'Sale Date: <YYYY-MM-DD>'
        if record.get('sale_date'):
            sale_date = record['sale_date']
            if hasattr(sale_date, 'strftime'):
                sale_date = sale_date.strftime('%Y-%m-%d')
            notes_parts.append(f"Sale Date: {sale_date}")

        # Req 2.4: source URL / reference
        if record.get('source_url'):
            notes_parts.append(str(record['source_url']))

        return {
            'property_street': record.get('property_street'),
            'property_city': record.get('property_city'),
            'property_state': 'IL',
            'property_zip': record.get('property_zip'),
            'owner_first_name': record.get('owner_first_name'),
            'owner_last_name': record.get('owner_last_name'),
            'source_type': 'foreclosure',
            'data_source': 'dupage_sheriff',
            # Note: the Property model has no 'county' column; county context is
            # conveyed via data_source='dupage_sheriff' and property_state='IL'.
            'lead_category': 'residential',
            'owner_user_id': owner_user_id,
            'notes': '; '.join(notes_parts) if notes_parts else None,
        }

    # ------------------------------------------------------------------ #
    # Manual Distress CSV ingestion (Requirements 6.1–6.9)                #
    # ------------------------------------------------------------------ #

    def process_csv(self, job_id: int, file_path: str, owner_user_id: str):
        """Process a CSV file of manual distress leads.

        Used for both sync (≤500 rows, called inline) and async (>500 rows,
        called from Celery). Returns the completed/failed ImportJob.

        CSV columns:
        - property_address (required): street address string
        - condition_notes (optional): physical condition text, stored in notes
        - distress_reason (optional): reason text, stored in notes
        - manual_priority (optional): integer 1–5, stored in manual_priority column

        Row handling:
        - Skip rows with missing/empty property_address; log row + reason
        - Truncate condition_notes and distress_reason to 2000 chars each
        - Append incoming notes to existing notes separated by '; '
        - Validate manual_priority in [1,5]; warn + skip field if invalid
        - Set source_type='manual_distress', data_source='manual_csv'

        Args:
            job_id: ID of the pre-created ImportJob record.
            file_path: Absolute path to the temporary CSV file on disk.
            owner_user_id: Platform user ID that will own the created leads.

        Returns:
            The completed (or failed) ImportJob ORM instance.

        Requirements: 6.1–6.9
        """
        import csv
        import os
        from app import db
        from app.models.import_job import ImportJob

        # Retrieve the pre-created ImportJob (created by the caller before
        # dispatching sync or async processing).
        job = db.session.get(ImportJob, job_id)
        if job is None:
            raise ValueError(f"ImportJob {job_id} not found")

        rows_processed = 0
        rows_imported = 0
        rows_skipped = 0
        error_log = []

        try:
            with open(file_path, 'r', newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)

                for row_num, row in enumerate(reader, start=2):  # row 1 = headers
                    rows_processed += 1

                    # --------------------------------------------------
                    # Required field: property_address (Req 6.2, 6.7)
                    # --------------------------------------------------
                    property_address = (row.get('property_address') or '').strip()
                    if not property_address:
                        error_log.append({
                            'row': row_num,
                            'reason': 'missing or empty property_address',
                        })
                        rows_skipped += 1
                        continue

                    # --------------------------------------------------
                    # Build notes from condition_notes + distress_reason
                    # Each truncated to 2000 chars (Req 6.4, 6.5)
                    # --------------------------------------------------
                    condition_notes = (row.get('condition_notes') or '').strip()[:2000]
                    distress_reason = (row.get('distress_reason') or '').strip()[:2000]
                    notes_parts = [p for p in [condition_notes, distress_reason] if p]
                    incoming_notes = '; '.join(notes_parts) if notes_parts else None

                    # --------------------------------------------------
                    # Validate manual_priority (Req 6.6)
                    # --------------------------------------------------
                    manual_priority = None
                    raw_priority = (row.get('manual_priority') or '').strip()
                    if raw_priority:
                        try:
                            pval = int(raw_priority)
                            if 1 <= pval <= 5:
                                manual_priority = pval
                            else:
                                error_log.append({
                                    'row': row_num,
                                    'reason': f'manual_priority out of range [1,5]: {pval}',
                                    'type': 'warning',
                                })
                        except (ValueError, TypeError):
                            error_log.append({
                                'row': row_num,
                                'reason': f'manual_priority not an integer: {raw_priority!r}',
                                'type': 'warning',
                            })

                    # --------------------------------------------------
                    # Build normalized record for dedup engine (Req 1.1, 1.2, 1.3, 1.6)
                    # --------------------------------------------------
                    normalized = {
                        'property_street': property_address,
                        'source_type': 'manual_distress',
                        'data_source': 'manual_csv',
                        'lead_category': 'residential',
                        'owner_user_id': owner_user_id,
                    }
                    if manual_priority is not None:
                        normalized['manual_priority'] = manual_priority

                    dedup_result = self.dedup_engine.process_record(normalized, job_id)

                    if dedup_result.outcome == 'conflict' and dedup_result.conflict_detail:
                        cd = dedup_result.conflict_detail
                        if cd.get('type') == 'pin_mismatch':
                            error_log.append(cd)
                            rows_skipped += 1
                            continue
                        else:
                            error_log.extend(cd.get('field_conflicts', []))

                    lead = dedup_result.lead
                    is_creation = (dedup_result.outcome == 'created')

                    # --------------------------------------------------
                    # Append incoming notes to existing notes (Req 6.4, 6.5)
                    # --------------------------------------------------
                    if incoming_notes:
                        _append_note(lead, incoming_notes)

                    # --------------------------------------------------
                    # GIS enrichment for manual_distress leads (Req 8.1)
                    # --------------------------------------------------
                    connector = self._gis_connector_for_lead(lead)
                    if connector:
                        gis_outcome = self._enrich_with_gis(lead, connector, job_id)
                        if gis_outcome.get('error'):
                            error_log.append({
                                'type': 'gis_enrichment',
                                'record': rows_processed,
                                **gis_outcome,
                            })

                    self._set_skip_trace_flag(lead, is_creation)
                    self._set_review_required_flag(lead, is_creation)
                    lead.last_import_job_id = job_id
                    db.session.add(lead)

                    if dedup_result.outcome == 'conflict':
                        rows_skipped += 1
                    else:
                        rows_imported += 1

            db.session.flush()
            self._complete_import_job(job, rows_processed, rows_imported, rows_skipped, error_log)
            db.session.commit()
            # Auto-score all leads created/updated by this job
            self._score_imported_leads(job.id)

            # Clean up temp file after successful processing
            try:
                os.unlink(file_path)
            except OSError:
                pass

        except Exception as e:
            self._fail_import_job(job, str(e))
            db.session.commit()
            # Clean up temp file on failure too
            try:
                os.unlink(file_path)
            except OSError:
                pass
            raise

        return job
