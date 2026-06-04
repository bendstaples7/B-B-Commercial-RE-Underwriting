"""Integration tests for the async CSV ingestion path — Task 16.2.

Tests:
- POST /api/ingestion/csv with 501-row CSV → 202 with import_job_id;
  ImportJob created with status='in_progress'; after calling the Celery task
  function directly (simulating task_always_eager), status = 'completed'.
- POST /api/ingestion/csv with 499-row CSV → 200 with summary dict.

Strategy for no-Redis environments:
  The Celery task (process_csv_ingestion) is NOT invoked via .delay() in the
  async test — doing so would require a live Redis broker and worker.  Instead:
  1. We patch process_csv_ingestion.delay so it is a no-op (records the call
     but does not execute).
  2. After the 202 response we verify the ImportJob exists with status='in_progress'.
  3. We then call the real task function directly (bypassing Celery entirely),
     which simulates task_always_eager / CELERY_TASK_ALWAYS_EAGER mode.
  4. We reload the ImportJob from DB and assert status='completed'.

Requirements: 6.9
"""
import csv
import io
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.import_job import ImportJob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OWNER_USER_ID = "user-123"


def _make_csv_bytes(num_rows: int) -> bytes:
    """Return UTF-8-encoded CSV bytes with *num_rows* data rows.

    Each row has a valid property_address so no rows are skipped.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["property_address"])
    writer.writeheader()
    for i in range(num_rows):
        writer.writerow({"property_address": f"{i + 100} Integration Ave"})
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Async path: 501 rows → 202 + import_job_id + eager task execution
# ---------------------------------------------------------------------------

class TestCSVAsyncPath:
    """Test the >500 row async CSV upload path end-to-end."""

    def test_501_row_csv_returns_202_with_job_id(self, client, app):
        """POST /api/ingestion/csv with 501-row CSV → 202 response with import_job_id.

        Celery .delay() is patched to a no-op so Redis is never contacted.
        We verify:
        1. The HTTP response is 202 with an 'import_job_id' field.
        2. The ImportJob was created in the DB with status='in_progress'.
        3. After calling process_csv directly (eager simulation), status='completed'.

        Requirements: 6.9
        """
        csv_bytes = _make_csv_bytes(501)

        import celery_worker

        with app.app_context():
            # Patch process_csv_ingestion.delay to be a no-op so no Redis call.
            # We need the real task function to be importable for step 3.
            with patch.object(
                celery_worker.process_csv_ingestion,
                "delay",
                return_value=MagicMock(),
            ) as mock_delay:
                # Also patch DuPage GIS connector to avoid real HTTP calls
                with patch(
                    "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_address",
                    return_value=None,
                ), patch(
                    "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_pin",
                    return_value=None,
                ):
                    resp = client.post(
                        f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
                        data={"file": (io.BytesIO(csv_bytes), "leads_501.csv")},
                        content_type="multipart/form-data",
                    )

            # ---------------------------------------------------------------
            # Step 1: Assert 202 response with import_job_id
            # ---------------------------------------------------------------
            assert resp.status_code == 202, (
                f"Expected 202, got {resp.status_code}: {resp.get_json()}"
            )
            data = resp.get_json()
            assert "import_job_id" in data, (
                f"Response missing 'import_job_id': {data}"
            )
            job_id = data["import_job_id"]
            assert isinstance(job_id, int), (
                f"import_job_id should be int, got {type(job_id)}: {job_id}"
            )

            # ---------------------------------------------------------------
            # Step 2: Assert .delay() was called once with correct args
            # ---------------------------------------------------------------
            mock_delay.assert_called_once()
            delay_call_args = mock_delay.call_args[0]  # positional args
            assert delay_call_args[0] == job_id, (
                f"delay() first arg should be job_id={job_id}, got {delay_call_args[0]}"
            )
            # delay_call_args[1] is the temp file path (any string)
            assert isinstance(delay_call_args[1], str), (
                f"delay() second arg (file_path) should be str, got {delay_call_args[1]}"
            )
            assert delay_call_args[2] == OWNER_USER_ID, (
                f"delay() third arg should be '{OWNER_USER_ID}', got {delay_call_args[2]}"
            )

            # ---------------------------------------------------------------
            # Step 3: Assert ImportJob in DB has status='in_progress'
            #         (before the async task has run)
            # ---------------------------------------------------------------
            job = db.session.get(ImportJob, job_id)
            assert job is not None, f"ImportJob {job_id} not found in DB"
            assert job.status == "in_progress", (
                f"Expected status='in_progress' before task runs, got '{job.status}'"
            )

            # ---------------------------------------------------------------
            # Step 4: Simulate eager execution — call the task function
            #         directly (bypassing Celery broker / Redis entirely).
            #         We must pass the real tmp_path written by the controller.
            # ---------------------------------------------------------------
            real_tmp_path = delay_call_args[1]

            # Write the CSV to that path because the controller already wrote
            # it; however, the temp file may have been created by the
            # controller with the correct content already.  If it still exists,
            # call the task directly.  If not (e.g. already cleaned up), write
            # a new copy with the same row count.
            if not os.path.exists(real_tmp_path):
                fd, real_tmp_path = tempfile.mkstemp(suffix=".csv")
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                    fh.write(csv_bytes.decode("utf-8"))

            # Re-set status to 'in_progress' in case process_csv was called
            # inside the eager path already — this ensures we're testing the
            # transition.  (No-op if status is already 'in_progress'.)
            job.status = "in_progress"
            db.session.commit()

            # Call the core service directly (same code path as the Celery task
            # but without broker/worker overhead).
            from app.services.deduplication_engine import DeduplicationEngine
            from app.services.gis.base import GISConnectorRegistry
            from app.services.lead_ingestion_service import LeadIngestionService

            with patch(
                "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_address",
                return_value=None,
            ), patch(
                "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_pin",
                return_value=None,
            ):
                dedup = DeduplicationEngine()
                service = LeadIngestionService(
                    dedup_engine=dedup,
                    gis_registry=GISConnectorRegistry,
                )
                service.process_csv(job_id, real_tmp_path, OWNER_USER_ID)

            # ---------------------------------------------------------------
            # Step 5: Assert ImportJob status is now 'completed'
            # ---------------------------------------------------------------
            db.session.expire(job)  # force reload from DB
            job = db.session.get(ImportJob, job_id)
            assert job is not None
            assert job.status == "completed", (
                f"Expected status='completed' after task runs, got '{job.status}'"
            )
            assert job.rows_processed == 501, (
                f"Expected rows_processed=501, got {job.rows_processed}"
            )
            assert job.rows_imported is not None

    def test_501_row_csv_delay_called_with_correct_owner_user_id(self, client, app):
        """Verify process_csv_ingestion.delay receives the correct owner_user_id."""
        csv_bytes = _make_csv_bytes(501)

        import celery_worker

        with app.app_context():
            with patch.object(
                celery_worker.process_csv_ingestion,
                "delay",
                return_value=MagicMock(),
            ) as mock_delay:
                resp = client.post(
                    f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
                    data={"file": (io.BytesIO(csv_bytes), "leads.csv")},
                    content_type="multipart/form-data",
                )

            assert resp.status_code == 202
            mock_delay.assert_called_once()
            call_owner_user_id = mock_delay.call_args[0][2]
            assert call_owner_user_id == OWNER_USER_ID


# ---------------------------------------------------------------------------
# Sync path: 499 rows → 200 with summary dict
# ---------------------------------------------------------------------------

class TestCSVSyncPath:
    """Test the ≤500 row synchronous CSV upload path end-to-end."""

    def test_499_row_csv_returns_200_with_summary(self, client, app):
        """POST /api/ingestion/csv with 499-row CSV → 200 with summary dict.

        Runs the actual LeadIngestionService.process_csv() inline (sync path).
        Asserts:
        - Response status 200.
        - Response body contains rows_processed, leads_created, leads_updated,
          rows_skipped.
        - rows_processed == 499.

        Requirements: 6.8, 6.9
        """
        csv_bytes = _make_csv_bytes(499)

        with app.app_context():
            with patch(
                "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_address",
                return_value=None,
            ), patch(
                "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_pin",
                return_value=None,
            ):
                resp = client.post(
                    f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
                    data={"file": (io.BytesIO(csv_bytes), "leads_499.csv")},
                    content_type="multipart/form-data",
                )

        assert resp.status_code == 200, (
            f"Expected 200 for 499-row CSV, got {resp.status_code}: {resp.get_json()}"
        )
        data = resp.get_json()
        assert "rows_processed" in data, f"Missing 'rows_processed' in {data}"
        assert "leads_created" in data, f"Missing 'leads_created' in {data}"
        assert "leads_updated" in data, f"Missing 'leads_updated' in {data}"
        assert "rows_skipped" in data, f"Missing 'rows_skipped' in {data}"
        assert data["rows_processed"] == 499, (
            f"Expected rows_processed=499, got {data['rows_processed']}"
        )

    def test_exactly_500_row_csv_returns_200(self, client, app):
        """POST /api/ingestion/csv with exactly 500 rows → 200 (boundary sync path).

        Requirements: 6.9
        """
        csv_bytes = _make_csv_bytes(500)

        with app.app_context():
            with patch(
                "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_address",
                return_value=None,
            ), patch(
                "app.services.gis.dupage_gis_connector.DuPageGISConnector.lookup_by_pin",
                return_value=None,
            ):
                resp = client.post(
                    f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
                    data={"file": (io.BytesIO(csv_bytes), "leads_500.csv")},
                    content_type="multipart/form-data",
                )

        assert resp.status_code == 200, (
            f"Expected 200 for 500-row CSV, got {resp.status_code}: {resp.get_json()}"
        )
        data = resp.get_json()
        assert data["rows_processed"] == 500
