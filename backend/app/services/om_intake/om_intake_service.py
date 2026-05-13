"""
OMIntakeService — central orchestrator for the Commercial OM PDF Intake pipeline.

Handles job lifecycle management: creation, status queries, state transitions,
result storage, scenario comparison retrieval, retry, and confirmation.

Requirements: 1.1–1.8, 7.1–7.12, 8.1, 8.3, 9.3, 11.1–11.3, 12.4
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app import db
from app.exceptions import ConflictError, InvalidFileError, ResourceNotFoundError
from app.models import (  # noqa: F401
    Deal,
    MarketRentAssumption,
    OMFieldOverride,
    OMIntakeJob,
    RentRollEntry,
    Unit,
)
from app.services.om_intake.om_intake_dataclasses import (
    ExtractedOMData,
    ScenarioComparison,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB
_PDF_MAGIC = b"%PDF"
_JOB_TTL_DAYS = 90


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decimal_to_str(obj: Any) -> Any:
    """Recursively convert Decimal values to strings for JSON storage."""
    if isinstance(obj, dict):
        return {k: _decimal_to_str(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_decimal_to_str(v) for v in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    return obj


def _load_job(job_id: int) -> OMIntakeJob:
    """Load an OMIntakeJob by primary key; raises ResourceNotFoundError if missing."""
    job = OMIntakeJob.query.get(job_id)
    if job is None:
        raise ResourceNotFoundError(
            f"OMIntakeJob {job_id} not found",
            payload={"job_id": job_id},
        )
    return job


# ---------------------------------------------------------------------------
# OMIntakeService
# ---------------------------------------------------------------------------


class OMIntakeService:
    """Service for managing OMIntakeJob records and pipeline state transitions.

    All public methods that accept a ``user_id`` enforce ownership checks so
    that users cannot access each other's jobs (Req 1.8).

    Internal state-transition helpers (``transition_to_*``, ``store_*``) do
    NOT perform user checks — they are called from Celery tasks that already
    have the job_id from a trusted internal context.
    """

    # ------------------------------------------------------------------
    # Public API — called from the controller
    # ------------------------------------------------------------------

    def create_job(
        self, user_id: str, file_bytes: bytes, filename: str
    ) -> OMIntakeJob:
        """Validate the uploaded file, persist a new PENDING job, and enqueue parsing.

        Args:
            user_id: The authenticated user uploading the file.
            file_bytes: Raw bytes of the uploaded PDF.
            filename: Original filename supplied by the client.

        Returns:
            The newly created OMIntakeJob (status=PENDING).

        Raises:
            InvalidFileError: If the file is not a PDF or exceeds 50 MB.

        Requirements: 1.1, 1.2, 1.3, 1.5, 1.6
        """
        # --- MIME / magic-byte validation (Req 1.2) ---
        lower_name = filename.lower() if filename else ""
        has_pdf_extension = lower_name.endswith(".pdf")
        has_pdf_magic = file_bytes[:4] == _PDF_MAGIC if len(file_bytes) >= 4 else False

        if not has_pdf_extension or not has_pdf_magic:
            raise InvalidFileError(
                "Uploaded file is not a valid PDF. "
                "Only PDF files (application/pdf) are accepted.",
                payload={"filename": filename, "reason": "unsupported_mime_type"},
            )

        # --- File size validation (Req 1.3) ---
        if len(file_bytes) > _MAX_FILE_BYTES:
            raise InvalidFileError(
                f"Uploaded file exceeds the 50 MB size limit "
                f"({len(file_bytes)} bytes received).",
                payload={"filename": filename, "reason": "file_too_large"},
            )

        # --- Create job record (Req 1.1, 1.5, 1.6) ---
        job = OMIntakeJob(
            user_id=user_id,
            original_filename=filename,
            intake_status="PENDING",
            pdf_bytes=file_bytes,
            expires_at=datetime.utcnow() + timedelta(days=_JOB_TTL_DAYS),
        )
        db.session.add(job)
        db.session.commit()

        # --- Enqueue Celery task by name ---
        import os
        from celery import Celery as _Celery
        _client = _Celery(broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'))
        _client.send_task('om_intake.process_pipeline', args=[job.id])

        return job

    def get_job(self, user_id: str, job_id: int) -> OMIntakeJob:
        """Retrieve a job by ID, enforcing ownership and expiry checks.

        Args:
            user_id: The requesting user.
            job_id: The OMIntakeJob primary key.

        Returns:
            The OMIntakeJob if found, owned by user_id, and not expired.

        Raises:
            ResourceNotFoundError: If the job does not exist, belongs to a
                different user, or has expired (Req 1.8, 8.3).

        Requirements: 1.7, 1.8, 8.3
        """
        job = OMIntakeJob.query.get(job_id)

        # Return 404 for both "not found" and "wrong user" to avoid leaking
        # job existence (Req 1.8).
        if job is None or job.user_id != user_id:
            raise ResourceNotFoundError(
                f"OMIntakeJob {job_id} not found.",
                payload={"job_id": job_id},
            )

        # Expiry check (Req 8.3)
        if job.expires_at < datetime.utcnow():
            raise ResourceNotFoundError(
                f"OMIntakeJob {job_id} has expired and is no longer accessible.",
                payload={"job_id": job_id, "reason": "expired"},
            )

        return job

    def list_jobs(
        self, user_id: str, page: int = 1, page_size: int = 25
    ) -> tuple[list[OMIntakeJob], int]:
        """Return a paginated list of jobs owned by the user, newest first.

        Args:
            user_id: The requesting user.
            page: 1-based page number.
            page_size: Number of records per page (clamped to [1, 100]).

        Returns:
            A tuple of (jobs_list, total_count).

        Requirements: 8.1
        """
        # Clamp page_size to [1, 100] (Req 8.1)
        page_size = max(1, min(page_size, 100))

        base_query = OMIntakeJob.query.filter_by(user_id=user_id).order_by(
            OMIntakeJob.created_at.desc()
        )

        total_count = base_query.count()
        offset = (page - 1) * page_size
        jobs = base_query.offset(offset).limit(page_size).all()

        return jobs, total_count

    def get_scenario_comparison(self, user_id: str, job_id: int) -> dict:
        """Return the stored ScenarioComparison dict for a REVIEW/CONFIRMED job.

        Args:
            user_id: The requesting user.
            job_id: The OMIntakeJob primary key.

        Returns:
            The scenario_comparison JSON dict stored on the job.

        Raises:
            ResourceNotFoundError: If the job is not found, not owned by the
                user, or is not in REVIEW/CONFIRMED status.

        Requirements: 5.1, 8.2
        """
        job = self.get_job(user_id, job_id)

        if job.intake_status not in ("REVIEW", "CONFIRMED"):
            raise ResourceNotFoundError(
                f"Scenario comparison is not available for job {job_id} "
                f"(current status: {job.intake_status}).",
                payload={"job_id": job_id, "intake_status": job.intake_status},
            )

        return job.scenario_comparison

    def retry_failed_job(self, user_id: str, job_id: int) -> OMIntakeJob:
        """Create a new PENDING job from the same PDF bytes as a FAILED job.

        The original job remains in FAILED status (Req 9.3).

        Args:
            user_id: The requesting user.
            job_id: The FAILED OMIntakeJob to retry.

        Returns:
            The newly created OMIntakeJob (status=PENDING).

        Raises:
            ResourceNotFoundError: If the job is not found or not owned by user.
            ConflictError: If the job is not in FAILED status.

        Requirements: 9.3
        """
        job = self.get_job(user_id, job_id)

        if job.intake_status != "FAILED":
            raise ConflictError(
                f"Only FAILED jobs can be retried. "
                f"Job {job_id} is currently in '{job.intake_status}' status.",
                payload={"job_id": job_id, "intake_status": job.intake_status},
            )

        new_job = OMIntakeJob(
            user_id=job.user_id,
            original_filename=job.original_filename,
            intake_status="PENDING",
            pdf_bytes=job.pdf_bytes,
            expires_at=datetime.utcnow() + timedelta(days=_JOB_TTL_DAYS),
        )
        db.session.add(new_job)
        db.session.commit()

        # Enqueue parsing for the new job
        import os
        from celery import Celery as _Celery
        _client = _Celery(broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'))
        _client.send_task('om_intake.process_pipeline', args=[new_job.id])

        return new_job

    # ------------------------------------------------------------------
    # Internal state-transition helpers — called by Celery tasks
    # ------------------------------------------------------------------

    def transition_to_parsing(self, job_id: int) -> None:
        """Transition a job to PARSING status.

        Called by the Celery parse task before PDF extraction begins.

        Args:
            job_id: The OMIntakeJob primary key.
        """
        job = _load_job(job_id)
        job.intake_status = "PARSING"
        job.updated_at = datetime.utcnow()
        db.session.commit()

    def store_parsed_text(
        self,
        job_id: int,
        raw_text: str,
        tables: list,
        warnings: list,
    ) -> None:
        """Persist PDF extraction results on the job record.

        Args:
            job_id: The OMIntakeJob primary key.
            raw_text: Full UTF-8 text extracted from the PDF.
            tables: Structured table data (list of tables).
            warnings: List of warning strings from the parser.

        Requirements: 2.1, 2.2, 2.7
        """
        job = _load_job(job_id)
        job.raw_text = raw_text
        job.tables_json = tables

        if warnings:
            if isinstance(warnings, list):
                job.table_extraction_warning = warnings[0]
            else:
                job.table_extraction_warning = str(warnings)

        job.updated_at = datetime.utcnow()
        db.session.commit()

    def transition_to_extracting(self, job_id: int) -> None:
        """Transition a job to EXTRACTING status.

        Called after successful PDF text extraction.

        Args:
            job_id: The OMIntakeJob primary key.
        """
        job = _load_job(job_id)
        job.intake_status = "EXTRACTING"
        job.updated_at = datetime.utcnow()
        db.session.commit()

    def store_extracted_data(self, job_id: int, data: ExtractedOMData) -> None:
        """Persist the Gemini-extracted OM data on the job record.

        Serializes the ExtractedOMData dataclass to a dict, converting any
        Decimal values to strings for JSON storage.  After storing, runs
        consistency checks (Req 10.1–10.8) and persists the resulting
        warnings and error flags on the job.

        Args:
            job_id: The OMIntakeJob primary key.
            data: The ExtractedOMData instance from GeminiOMExtractorService.

        Requirements: 3.2, 10.1, 10.2, 10.3, 10.4, 10.6, 10.7, 10.8
        """
        job = _load_job(job_id)

        serialized = _decimal_to_str(dataclasses.asdict(data))
        job.extracted_om_data = serialized

        # --- Consistency checks (Req 10) ---
        warnings = self._run_consistency_checks(job, serialized)
        job.consistency_warnings = warnings if warnings else []

        job.updated_at = datetime.utcnow()
        db.session.commit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_consistency_checks(job: "OMIntakeJob", data_dict: dict) -> list:
        """Run all consistency checks against the serialized ExtractedOMData dict.

        Each field in *data_dict* is a ``{"value": ..., "confidence": ...}``
        dict (or a list of such dicts for ``unit_mix``).

        Side-effects:
            Sets ``job.asking_price_missing_error`` (Req 10.6) and
            ``job.unit_count_missing_error`` (Req 10.7) directly on the job
            object.  The caller is responsible for committing the session.

        Args:
            job: The OMIntakeJob being updated (mutated in-place for flags).
            data_dict: The serialized ExtractedOMData dict.

        Returns:
            A list of warning dicts to be stored in ``job.consistency_warnings``.

        Requirements: 10.1, 10.2, 10.3, 10.4, 10.6, 10.7, 10.8
        """

        def _get_val(field_dict):
            """Extract the ``value`` key from a field dict, or None."""
            if isinstance(field_dict, dict):
                return field_dict.get("value")
            return None

        warnings: list = []

        # ----------------------------------------------------------------
        # Req 10.6 — asking_price missing flag
        # ----------------------------------------------------------------
        asking_price = _get_val(data_dict.get("asking_price"))
        if asking_price is None or asking_price == 0:
            job.asking_price_missing_error = True
        else:
            job.asking_price_missing_error = False

        # ----------------------------------------------------------------
        # Req 10.7 — unit_count missing flag
        # ----------------------------------------------------------------
        unit_count_stated_raw = _get_val(data_dict.get("unit_count"))
        try:
            unit_count_stated = (
                int(unit_count_stated_raw) if unit_count_stated_raw is not None else None
            )
        except (TypeError, ValueError):
            unit_count_stated = None

        if unit_count_stated is None or unit_count_stated < 1:
            job.unit_count_missing_error = True
        else:
            job.unit_count_missing_error = False

        # ----------------------------------------------------------------
        # Req 10.1 — unit_count sum check
        # ----------------------------------------------------------------
        unit_mix = data_dict.get("unit_mix")
        if isinstance(unit_mix, list) and unit_mix:
            row_counts = []
            for row in unit_mix:
                if isinstance(row, dict):
                    raw = _get_val(row.get("unit_count"))
                    try:
                        row_counts.append(int(raw) if raw is not None else 0)
                    except (TypeError, ValueError):
                        row_counts.append(0)
            sum_unit_count = sum(row_counts)

            if unit_count_stated is not None and sum_unit_count != unit_count_stated:
                delta = sum_unit_count - unit_count_stated
                warnings.append(
                    {
                        "type": "unit_count_mismatch_warning",
                        "field": "unit_count",
                        "computed": sum_unit_count,
                        "stated": unit_count_stated,
                        "delta": delta,
                    }
                )

        # ----------------------------------------------------------------
        # Req 10.2 — NOI consistency check
        # ----------------------------------------------------------------
        egi_raw = _get_val(data_dict.get("current_effective_gross_income"))
        expenses_raw = _get_val(data_dict.get("current_gross_expenses"))
        noi_stated_raw = _get_val(data_dict.get("current_noi"))

        # Convert to float for arithmetic (values may be int, float, or str Decimal)
        def _to_float(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        egi = _to_float(egi_raw)
        expenses = _to_float(expenses_raw)
        noi_stated = _to_float(noi_stated_raw)

        if egi is None or expenses is None or noi_stated is None or noi_stated == 0:
            # Req 10.8 — skip and record insufficient_data_warning
            warnings.append(
                {
                    "type": "insufficient_data_warning",
                    "field": "noi_consistency",
                    "reason": "missing operand",
                }
            )
        else:
            noi_computed = egi - expenses
            if abs(noi_computed - noi_stated) / abs(noi_stated) > 0.02:
                warnings.append(
                    {
                        "type": "noi_consistency_warning",
                        "field": "current_noi",
                        "computed": noi_computed,
                        "stated": noi_stated,
                        "delta": noi_computed - noi_stated,
                    }
                )

        # ----------------------------------------------------------------
        # Req 10.3 — Cap rate consistency check
        # ----------------------------------------------------------------
        asking_price_f = _to_float(asking_price)
        noi_for_cap = _to_float(noi_stated_raw)
        cap_rate_stated_raw = _get_val(data_dict.get("current_cap_rate"))
        cap_rate_stated = _to_float(cap_rate_stated_raw)

        if asking_price_f is None or asking_price_f == 0 or noi_for_cap is None or cap_rate_stated is None or cap_rate_stated == 0:
            warnings.append(
                {
                    "type": "insufficient_data_warning",
                    "field": "cap_rate_consistency",
                    "reason": "missing operand",
                }
            )
        else:
            cap_rate_computed = noi_for_cap / asking_price_f
            if abs(cap_rate_computed - cap_rate_stated) > 0.005:
                warnings.append(
                    {
                        "type": "cap_rate_consistency_warning",
                        "field": "current_cap_rate",
                        "computed": cap_rate_computed,
                        "stated": cap_rate_stated,
                        "delta": cap_rate_computed - cap_rate_stated,
                    }
                )

        # ----------------------------------------------------------------
        # Req 10.4 — GRM consistency check
        # ----------------------------------------------------------------
        gpi_raw = _get_val(data_dict.get("current_gross_potential_income"))
        gpi = _to_float(gpi_raw)
        grm_stated_raw = _get_val(data_dict.get("current_grm"))
        grm_stated = _to_float(grm_stated_raw)

        if asking_price_f is None or asking_price_f == 0 or gpi is None or gpi == 0 or grm_stated is None or grm_stated == 0:
            warnings.append(
                {
                    "type": "insufficient_data_warning",
                    "field": "grm_consistency",
                    "reason": "missing operand",
                }
            )
        else:
            grm_computed = asking_price_f / gpi
            if abs(grm_computed - grm_stated) / abs(grm_stated) > 0.02:
                warnings.append(
                    {
                        "type": "grm_consistency_warning",
                        "field": "current_grm",
                        "computed": grm_computed,
                        "stated": grm_stated,
                        "delta": grm_computed - grm_stated,
                    }
                )

        return warnings

    def store_market_rent(
        self,
        job_id: int,
        unit_type: str,
        estimate: Any,
        low: Any,
        high: Any,
    ) -> None:
        """Store market rent research results for a single unit type.

        Args:
            job_id: The OMIntakeJob primary key.
            unit_type: The unit type label (e.g. "2BR/1BA").
            estimate: The market rent point estimate.
            low: The low end of the market rent range.
            high: The high end of the market rent range.

        Requirements: 4.2
        """
        from sqlalchemy.orm.attributes import flag_modified

        job = _load_job(job_id)

        # Initialize dict if not yet set; copy to ensure SQLAlchemy detects
        # the mutation (plain db.JSON columns don't use MutableDict tracking).
        current = dict(job.market_rent_results) if job.market_rent_results else {}
        current[unit_type] = {
            "estimate": str(estimate),
            "low": str(low),
            "high": str(high),
        }
        job.market_rent_results = current
        flag_modified(job, "market_rent_results")
        db.session.commit()

    def store_scenario_comparison(
        self, job_id: int, comparison: ScenarioComparison
    ) -> None:
        """Persist the computed ScenarioComparison on the job record.

        Serializes the frozen ScenarioComparison dataclass to a dict,
        converting Decimal values to strings for JSON storage.

        Args:
            job_id: The OMIntakeJob primary key.
            comparison: The ScenarioComparison produced by compute_scenarios.

        Requirements: 5.1
        """
        job = _load_job(job_id)

        serialized = _decimal_to_str(dataclasses.asdict(comparison))
        job.scenario_comparison = serialized
        db.session.commit()

    def transition_to_review(self, job_id: int) -> None:
        """Transition a job to REVIEW status.

        Called after market rent research and scenario computation complete.

        Args:
            job_id: The OMIntakeJob primary key.
        """
        job = _load_job(job_id)
        job.intake_status = "REVIEW"
        job.updated_at = datetime.utcnow()
        db.session.commit()

    def transition_to_failed(self, job_id: int, error_message: str) -> None:
        """Transition a job to FAILED status, recording the failure stage.

        Captures the current status as ``failed_at_stage`` before overwriting
        it with FAILED (Req 9.2).

        Args:
            job_id: The OMIntakeJob primary key.
            error_message: Human-readable description of the failure.

        Requirements: 9.2
        """
        job = _load_job(job_id)
        job.failed_at_stage = job.intake_status
        job.intake_status = "FAILED"
        job.error_message = error_message
        db.session.commit()

    # ------------------------------------------------------------------
    # Confirmation — called from the controller (Task 8.1 + 8.2)
    # ------------------------------------------------------------------

    def confirm_job(self, user_id: str, job_id: int, confirmed_data: dict) -> Deal:
        """Confirm an OM intake job and create a pre-populated Deal record.

        Validates job state, merges user overrides with extracted data, maps
        fields to a Deal, creates Unit / RentRollEntry / MarketRentAssumption
        records, runs post-confirmation integrity checks, and transitions the
        job to CONFIRMED — all inside a single atomic database transaction.

        Args:
            user_id: The authenticated user confirming the intake.
            job_id: The OMIntakeJob primary key.
            confirmed_data: Dict of user-confirmed field values that may
                override any field from ``extracted_om_data``.

        Returns:
            The newly created Deal record.

        Raises:
            ResourceNotFoundError: If the job is not found, not owned by the
                user, or has expired.
            ConflictError: If the job is already CONFIRMED or not in REVIEW.
            InvalidFileError: If required fields are missing/invalid or
                post-confirmation integrity checks fail.

        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9,
                      7.11, 7.12, 11.1, 11.2, 11.3, 12.4
        """
        # ----------------------------------------------------------------
        # Step 1 — Validate job state (outside transaction)
        # ----------------------------------------------------------------
        job = self.get_job(user_id, job_id)

        if job.intake_status == "CONFIRMED":
            raise ConflictError(
                f"OMIntakeJob {job_id} is already confirmed.",
                payload={"job_id": job_id, "deal_id": job.deal_id},
            )

        if job.intake_status != "REVIEW":
            raise ConflictError(
                f"OMIntakeJob {job_id} cannot be confirmed from status "
                f"'{job.intake_status}'. Job must be in REVIEW status.",
                payload={"job_id": job_id, "intake_status": job.intake_status},
            )

        # ----------------------------------------------------------------
        # Step 2 — Merge confirmed_data with extracted_om_data
        # ----------------------------------------------------------------
        extracted = job.extracted_om_data or {}

        def _get_val(field: str) -> Any:
            """Return confirmed value if present, else extracted value."""
            if field in confirmed_data:
                return confirmed_data[field]
            field_dict = extracted.get(field)
            if isinstance(field_dict, dict):
                return field_dict.get("value")
            return None

        def _to_decimal(v: Any) -> Decimal | None:
            """Safely convert a value to Decimal, returning None on failure."""
            if v is None:
                return None
            try:
                return Decimal(str(v))
            except (InvalidOperation, TypeError, ValueError):
                return None

        # ----------------------------------------------------------------
        # Step 3 — Validate required fields (before transaction)
        # ----------------------------------------------------------------
        asking_price_raw = _get_val("asking_price")
        asking_price = _to_decimal(asking_price_raw)
        if asking_price is None or asking_price <= 0:
            raise InvalidFileError(
                "asking_price must be a positive number to create a Deal.",
                payload={"field": "asking_price", "value": asking_price_raw},
            )

        unit_count_raw = _get_val("unit_count")
        try:
            unit_count = int(unit_count_raw) if unit_count_raw is not None else None
        except (TypeError, ValueError):
            unit_count = None
        if unit_count is None or unit_count < 1:
            raise InvalidFileError(
                "unit_count must be >= 1 to create a Deal.",
                payload={"field": "unit_count", "value": unit_count_raw},
            )

        # ----------------------------------------------------------------
        # Steps 4–14 — Atomic transaction
        # ----------------------------------------------------------------
        try:
            # ---- Step 3b: Store OMFieldOverride records for overrides ----
            for field_name, confirmed_value in confirmed_data.items():
                extracted_field = extracted.get(field_name)
                if isinstance(extracted_field, dict):
                    original_value = extracted_field.get("value")
                else:
                    original_value = extracted_field

                # Convert Decimal to float for JSON storage
                def _json_safe(v):
                    if isinstance(v, Decimal):
                        return float(v)
                    return v

                # Use merge() to upsert (handles unique constraint)
                override = OMFieldOverride(
                    om_intake_job_id=job_id,
                    field_name=field_name,
                    original_value=_json_safe(original_value),
                    overridden_value=_json_safe(confirmed_value),
                    overridden_at=datetime.utcnow(),
                )
                db.session.merge(override)

            # ---- Step 5: Map fields to Deal ----
            # Resolve unit_mix — may come from confirmed_data or extracted_om_data
            unit_mix_raw = confirmed_data.get("unit_mix")
            if unit_mix_raw is None:
                extracted_unit_mix = extracted.get("unit_mix")
                if isinstance(extracted_unit_mix, list):
                    unit_mix_raw = []
                    for row in extracted_unit_mix:
                        if isinstance(row, dict):
                            # Each field is {"value": ..., "confidence": ...}
                            unit_mix_raw.append({
                                k: (v.get("value") if isinstance(v, dict) else v)
                                for k, v in row.items()
                            })
                        else:
                            unit_mix_raw.append(row)
                else:
                    unit_mix_raw = []

            # Resolve other_income_items
            other_income_items_raw = confirmed_data.get("other_income_items")
            if other_income_items_raw is None:
                extracted_oi = extracted.get("other_income_items")
                if isinstance(extracted_oi, list):
                    other_income_items_raw = []
                    for item in extracted_oi:
                        if isinstance(item, dict):
                            other_income_items_raw.append({
                                k: (v.get("value") if isinstance(v, dict) else v)
                                for k, v in item.items()
                            })
                        else:
                            other_income_items_raw.append(item)
                else:
                    other_income_items_raw = []

            # Resolve expense_items
            expense_items_raw = confirmed_data.get("expense_items")
            if expense_items_raw is None:
                extracted_exp = extracted.get("expense_items")
                if isinstance(extracted_exp, list):
                    expense_items_raw = []
                    for item in extracted_exp:
                        if isinstance(item, dict):
                            expense_items_raw.append({
                                k: (v.get("value") if isinstance(v, dict) else v)
                                for k, v in item.items()
                            })
                        else:
                            expense_items_raw.append(item)
                else:
                    expense_items_raw = []

            # ---- Step 6: Map expense labels to Deal OpEx fields ----
            property_taxes_annual = None
            insurance_annual = None
            utilities_annual = Decimal("0")
            repairs_and_maintenance_annual = None
            management_fee_rate = None
            admin_and_marketing_annual = None
            payroll_annual = None
            other_opex_annual = None
            unmatched_expense_items = []

            for item in expense_items_raw:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").lower()
                amount_raw = item.get("current_annual_amount") or item.get("proforma_annual_amount")
                amount = _to_decimal(amount_raw)

                if any(kw in label for kw in ("real estate tax", "property tax", "taxes")):
                    property_taxes_annual = amount
                elif "insurance" in label:
                    insurance_annual = amount
                elif any(kw in label for kw in ("gas", "electric", "water", "sewer", "trash", "utilities")):
                    if amount is not None:
                        utilities_annual = (utilities_annual or Decimal("0")) + amount
                elif any(kw in label for kw in ("maintenance", "repairs", "repair")):
                    repairs_and_maintenance_annual = amount
                elif any(kw in label for kw in ("management", "mgmt")):
                    # If it looks like a percentage (< 1.0 or ends with %), treat as rate
                    if amount is not None and amount < Decimal("1"):
                        management_fee_rate = amount
                    else:
                        # Store as other_opex_annual (accumulate)
                        if other_opex_annual is None:
                            other_opex_annual = amount
                        elif amount is not None:
                            other_opex_annual += amount
                elif any(kw in label for kw in ("admin", "marketing", "advertising")):
                    admin_and_marketing_annual = amount
                elif any(kw in label for kw in ("payroll", "labor", "staff")):
                    payroll_annual = amount
                else:
                    unmatched_expense_items.append(item)

            # Treat zero utilities_annual as None (no data)
            if utilities_annual == Decimal("0"):
                utilities_annual = None

            # ---- Step 7: Compute other_income_monthly ----
            other_income_monthly = Decimal("0")
            for oi_item in other_income_items_raw:
                if not isinstance(oi_item, dict):
                    continue
                annual_raw = oi_item.get("annual_amount")
                annual = _to_decimal(annual_raw)
                if annual is not None:
                    other_income_monthly += annual / Decimal("12")

            # ---- Step 8: Financing fields (stored on Deal if columns exist) ----
            # Deal model does not have loan_amount/interest_rate/amortization_years columns.
            # Per design: "store as null if absent" — these are noted but not persisted.

            # ---- Resolve vacancy_rate ----
            vacancy_rate_raw = _get_val("proforma_vacancy_rate")
            vacancy_rate = _to_decimal(vacancy_rate_raw)

            # ---- Resolve property_address (required by Deal) ----
            property_address = _get_val("property_address") or ""

            # ---- Build Deal ----
            deal_kwargs: dict[str, Any] = dict(
                created_by_user_id=user_id,
                property_address=property_address,
                property_city=_get_val("property_city"),
                property_state=_get_val("property_state"),
                property_zip=_get_val("property_zip"),
                unit_count=unit_count,
                purchase_price=asking_price,
                other_income_monthly=other_income_monthly,
            )

            # Optional expense fields
            if property_taxes_annual is not None:
                deal_kwargs["property_taxes_annual"] = property_taxes_annual
            if insurance_annual is not None:
                deal_kwargs["insurance_annual"] = insurance_annual
            if utilities_annual is not None:
                deal_kwargs["utilities_annual"] = utilities_annual
            if repairs_and_maintenance_annual is not None:
                deal_kwargs["repairs_and_maintenance_annual"] = repairs_and_maintenance_annual
            if management_fee_rate is not None:
                deal_kwargs["management_fee_rate"] = management_fee_rate
            if admin_and_marketing_annual is not None:
                deal_kwargs["admin_and_marketing_annual"] = admin_and_marketing_annual
            if payroll_annual is not None:
                deal_kwargs["payroll_annual"] = payroll_annual
            if other_opex_annual is not None:
                deal_kwargs["other_opex_annual"] = other_opex_annual
            if vacancy_rate is not None:
                deal_kwargs["vacancy_rate"] = vacancy_rate

            deal = Deal(**deal_kwargs)

            # ---- Step 9: Flush to get deal.id ----
            db.session.add(deal)
            db.session.flush()

            # ---- Step 10: Create Unit records ----
            units_created = 0
            rent_roll_sum = Decimal("0")

            # Track distinct unit types for MarketRentAssumption (one per type)
            seen_unit_types: dict[str, dict] = {}

            for row in unit_mix_raw:
                if not isinstance(row, dict):
                    continue

                row_unit_type = str(row.get("unit_type_label") or "")
                row_unit_count_raw = row.get("unit_count")
                try:
                    row_unit_count = int(row_unit_count_raw) if row_unit_count_raw is not None else 0
                except (TypeError, ValueError):
                    row_unit_count = 0

                if row_unit_count <= 0:
                    raise InvalidFileError(
                        f"unit_mix row '{row_unit_type}' has unit_count <= 0 "
                        f"({row_unit_count_raw}). All unit mix rows must have "
                        f"a positive unit count.",
                        payload={
                            "field": "unit_mix.unit_count",
                            "unit_type_label": row_unit_type,
                            "value": row_unit_count_raw,
                        },
                    )

                sqft_raw = row.get("sqft")
                sqft = int(_to_decimal(sqft_raw) or 0) or None

                current_avg_rent_raw = row.get("current_avg_rent")
                current_avg_rent = _to_decimal(current_avg_rent_raw) or Decimal("0")

                proforma_rent_raw = row.get("proforma_rent")
                proforma_rent = _to_decimal(proforma_rent_raw)

                market_rent_raw = row.get("market_rent_estimate")
                market_rent = _to_decimal(market_rent_raw)

                # Track for MarketRentAssumption (last row wins for duplicate types)
                seen_unit_types[row_unit_type] = {
                    "proforma_rent": proforma_rent,
                    "market_rent_estimate": market_rent,
                }

                # Parse beds/baths from unit type label (e.g. "2BR/1BA" → beds=2, baths=1)
                import re as _re
                _label_upper = row_unit_type.upper()
                _beds_match = _re.search(r'(\d+)\s*B[DR]', _label_upper)
                _baths_match = _re.search(r'(\d+(?:\.\d+)?)\s*BA', _label_upper)
                parsed_beds = int(_beds_match.group(1)) if _beds_match else 0
                parsed_baths = float(_baths_match.group(1)) if _baths_match else 0

                # Create one Unit per unit in this row
                for i in range(row_unit_count):
                    unit = Unit(
                        deal_id=deal.id,
                        unit_identifier=f"{row_unit_type}-{i + 1}",
                        unit_type=row_unit_type,
                        sqft=sqft,
                        beds=parsed_beds,
                        baths=parsed_baths,
                        occupancy_status="Occupied",
                    )
                    db.session.add(unit)
                    db.session.flush()  # get unit.id

                    # ---- Step 11: Create RentRollEntry ----
                    rent_entry = RentRollEntry(
                        unit_id=unit.id,
                        current_rent=current_avg_rent,
                    )
                    db.session.add(rent_entry)

                    rent_roll_sum += current_avg_rent
                    units_created += 1

            # ---- Step 12: Create MarketRentAssumption records ----
            for unit_type_label, rent_data in seen_unit_types.items():
                mra = MarketRentAssumption(
                    deal_id=deal.id,
                    unit_type=unit_type_label,
                    post_reno_target_rent=rent_data["proforma_rent"],
                    target_rent=rent_data["market_rent_estimate"],
                )
                db.session.add(mra)

            # ---- Step 13: Post-confirmation integrity checks (Task 8.2) ----
            # Check 1: deal.purchase_price == asking_price (within $0.01)
            if abs(deal.purchase_price - asking_price) > Decimal("0.01"):
                raise InvalidFileError(
                    f"Integrity check failed: deal.purchase_price "
                    f"({deal.purchase_price}) does not match asking_price "
                    f"({asking_price}).",
                    payload={
                        "check": "purchase_price_match",
                        "deal_purchase_price": str(deal.purchase_price),
                        "asking_price": str(asking_price),
                    },
                )

            # Check 2: total unit records created == unit_count
            if units_created != unit_count:
                raise InvalidFileError(
                    f"Integrity check failed: created {units_created} Unit "
                    f"records but unit_count is {unit_count}.",
                    payload={
                        "check": "unit_count_match",
                        "units_created": units_created,
                        "unit_count": unit_count,
                    },
                )

            # Check 3: sum of RentRollEntry.current_rent == sum of
            # (unit_count * current_avg_rent) across unit_mix rows (within $0.01)
            expected_rent_sum = Decimal("0")
            for row in unit_mix_raw:
                if not isinstance(row, dict):
                    continue
                row_unit_count_raw = row.get("unit_count")
                try:
                    row_unit_count = int(row_unit_count_raw) if row_unit_count_raw is not None else 0
                except (TypeError, ValueError):
                    row_unit_count = 0
                current_avg_rent_raw = row.get("current_avg_rent")
                current_avg_rent = _to_decimal(current_avg_rent_raw) or Decimal("0")
                expected_rent_sum += Decimal(str(row_unit_count)) * current_avg_rent

            if abs(rent_roll_sum - expected_rent_sum) > Decimal("0.01"):
                raise InvalidFileError(
                    f"Integrity check failed: rent roll sum ({rent_roll_sum}) "
                    f"does not match expected unit mix rent sum "
                    f"({expected_rent_sum}).",
                    payload={
                        "check": "rent_roll_sum_match",
                        "rent_roll_sum": str(rent_roll_sum),
                        "expected_rent_sum": str(expected_rent_sum),
                    },
                )

            # ---- Step 14: Transition job to CONFIRMED ----
            # Store unmatched expense items in consistency_warnings
            if unmatched_expense_items:
                existing_warnings = list(job.consistency_warnings or [])
                existing_warnings.append({
                    "type": "unmatched_expense_items",
                    "items": unmatched_expense_items,
                })
                job.consistency_warnings = existing_warnings

            job.intake_status = "CONFIRMED"
            job.deal_id = deal.id
            job.updated_at = datetime.utcnow()

            db.session.commit()
            return deal

        except Exception:
            db.session.rollback()
            raise
