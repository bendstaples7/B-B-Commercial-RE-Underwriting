"""Unit tests for ingestion controller — Task 11.3.

Tests:
- POST /api/ingestion/foreclosure — valid body → 200
- POST /api/ingestion/foreclosure — missing owner_user_id → 400
- POST /api/ingestion/foreclosure — empty records → 400
- GET  /api/ingestion/jobs/<job_id> — existing job → 200 with correct fields
- GET  /api/ingestion/jobs/99999    — non-existing job → 404
- POST /api/ingestion/csv — ≤500 rows → 200 (mocked service)
- POST /api/ingestion/csv — >500 rows → 202 with import_job_id (mocked Celery)
- POST /api/ingestion/csv — file > 10 MB → 400
- POST /api/ingestion/csv — missing owner_user_id → 400

Requirements: 1.7, 6.3, 6.8, 6.9, 9.6
"""
import io
import csv
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.import_job import ImportJob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OWNER_USER_ID = "test-user-001"

FORECLOSURE_RECORD = {
    "property_street": "123 Oak St",
    "property_city": "Wheaton",
    "property_zip": "60187",
    "owner_first_name": "Jane",
    "owner_last_name": "Doe",
}


def _make_fake_job(
    job_id: int = 1,
    status: str = "completed",
    source_type: str = "foreclosure",
    rows_processed: int = 1,
    rows_imported: int = 1,
    rows_skipped: int = 0,
) -> MagicMock:
    """Return a MagicMock that looks like an ImportJob ORM instance."""
    job = MagicMock(spec=ImportJob)
    job.id = job_id
    job.status = status
    job.source_type = source_type
    job.rows_processed = rows_processed
    job.rows_imported = rows_imported
    job.rows_skipped = rows_skipped
    job.error_log = []
    job.created_at = datetime(2024, 1, 15, 12, 0, 0)
    job.completed_at = datetime(2024, 1, 15, 12, 0, 5)
    return job


def _make_csv_content(num_rows: int) -> bytes:
    """Return UTF-8 bytes for a CSV file with *num_rows* data rows."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["property_address"])
    writer.writeheader()
    for i in range(num_rows):
        writer.writerow({"property_address": f"{i + 100} Main St"})
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# POST /api/ingestion/foreclosure
# ---------------------------------------------------------------------------

class TestIngestForeclosure:

    def test_valid_body_returns_200(self, client, app):
        """POST /api/ingestion/foreclosure with valid body → 200 with job fields."""
        fake_job = _make_fake_job(job_id=42, source_type="foreclosure")

        with app.app_context():
            with patch(
                "app.controllers.ingestion_controller._build_service"
            ) as mock_build:
                mock_service = MagicMock()
                mock_service.ingest_foreclosure.return_value = fake_job
                mock_build.return_value = mock_service

                payload = {
                    "owner_user_id": OWNER_USER_ID,
                    "records": [FORECLOSURE_RECORD],
                }
                resp = client.post(
                    "/api/ingestion/foreclosure",
                    data=json.dumps(payload),
                    content_type="application/json",
                )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == 42
        assert data["status"] == "completed"
        assert data["source_type"] == "foreclosure"
        assert "rows_processed" in data
        assert "rows_imported" in data
        assert "rows_skipped" in data

    def test_missing_owner_user_id_returns_400(self, client):
        """POST /api/ingestion/foreclosure without owner_user_id → 400."""
        payload = {"records": [FORECLOSURE_RECORD]}
        resp = client.post(
            "/api/ingestion/foreclosure",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_empty_records_returns_400(self, client):
        """POST /api/ingestion/foreclosure with empty records list → 400."""
        payload = {"owner_user_id": OWNER_USER_ID, "records": []}
        resp = client.post(
            "/api/ingestion/foreclosure",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_service_called_with_correct_args(self, client, app):
        """Verifies ingest_foreclosure receives the records and owner_user_id."""
        fake_job = _make_fake_job()

        with app.app_context():
            with patch(
                "app.controllers.ingestion_controller._build_service"
            ) as mock_build:
                mock_service = MagicMock()
                mock_service.ingest_foreclosure.return_value = fake_job
                mock_build.return_value = mock_service

                payload = {
                    "owner_user_id": OWNER_USER_ID,
                    "records": [FORECLOSURE_RECORD],
                }
                client.post(
                    "/api/ingestion/foreclosure",
                    data=json.dumps(payload),
                    content_type="application/json",
                )

                mock_service.ingest_foreclosure.assert_called_once_with(
                    [FORECLOSURE_RECORD], OWNER_USER_ID
                )


# ---------------------------------------------------------------------------
# GET /api/ingestion/jobs/<job_id>
# ---------------------------------------------------------------------------

class TestGetImportJob:

    def test_existing_job_returns_200_with_fields(self, client, app):
        """GET /api/ingestion/jobs/<id> for an existing job → 200 with all required fields."""
        with app.app_context():
            # Create a real ImportJob in the DB
            job = ImportJob(
                user_id=OWNER_USER_ID,
                spreadsheet_id="ingestion",
                sheet_name="foreclosure",
                source_type="foreclosure",
                status="completed",
                rows_processed=5,
                rows_imported=4,
                rows_skipped=1,
                error_log=[],
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        resp = client.get(f"/api/ingestion/jobs/{job_id}")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == job_id
        assert data["status"] == "completed"
        assert data["source_type"] == "foreclosure"
        assert data["rows_processed"] == 5
        assert data["rows_imported"] == 4
        assert data["rows_skipped"] == 1
        assert "error_log" in data
        assert "created_at" in data

    def test_nonexistent_job_returns_404(self, client):
        """GET /api/ingestion/jobs/99999 when job does not exist → 404."""
        resp = client.get("/api/ingestion/jobs/99999")

        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
        assert "99999" in data["error"]["message"]


# ---------------------------------------------------------------------------
# POST /api/ingestion/csv
# ---------------------------------------------------------------------------

class TestUploadCSV:

    def test_missing_owner_user_id_returns_400(self, client):
        """POST /api/ingestion/csv without owner_user_id query param → 400."""
        csv_bytes = _make_csv_content(5)
        resp = client.post(
            "/api/ingestion/csv",
            data={"file": (io.BytesIO(csv_bytes), "leads.csv")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 400

    def test_file_over_10mb_returns_400(self, client):
        """POST /api/ingestion/csv with file > 10 MB → 400 before any parsing."""
        # 10 MB + 1 byte of zeros — not valid CSV but size check happens first
        big_content = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
            data={"file": (io.BytesIO(big_content), "big.csv")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "10 MB" in data["error"]["message"] or "10" in data["error"]["message"]

    def test_le_500_rows_returns_200_with_summary(self, client, app):
        """POST /api/ingestion/csv with ≤500 rows → 200 with summary dict."""
        csv_bytes = _make_csv_content(5)

        fake_job = MagicMock(spec=ImportJob)
        fake_job.id = 10
        fake_job.rows_processed = 5
        fake_job.rows_imported = 5
        fake_job.rows_skipped = 0
        fake_job.status = "completed"

        with app.app_context():
            with patch(
                "app.controllers.ingestion_controller._build_service"
            ) as mock_build:
                mock_service = MagicMock()
                # _create_import_job returns a job with an id so commit works
                created_job = MagicMock(spec=ImportJob)
                created_job.id = 10
                mock_service._create_import_job.return_value = created_job
                mock_service.process_csv.return_value = fake_job
                mock_build.return_value = mock_service

                # Patch db.session.commit to be a no-op
                with patch("app.controllers.ingestion_controller.db") as mock_db:
                    mock_db.session.commit.return_value = None

                    resp = client.post(
                        f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
                        data={"file": (io.BytesIO(csv_bytes), "leads.csv")},
                        content_type="multipart/form-data",
                    )

        assert resp.status_code == 200
        data = resp.get_json()
        assert "rows_processed" in data
        assert "leads_created" in data
        assert "leads_updated" in data
        assert "rows_skipped" in data

    def test_gt_500_rows_returns_202_with_job_id(self, client, app):
        """POST /api/ingestion/csv with >500 rows → 202 with import_job_id.

        The Celery task (process_csv_ingestion) is not yet registered in
        celery_worker.py (task 16.1 is pending).  The controller handles the
        ImportError gracefully and still returns 202 with import_job_id.
        We patch the controller's inner import to inject a mock task so that
        we can also verify the happy-path where Celery IS available.
        """
        # Build a CSV with 501 data rows
        csv_bytes = _make_csv_content(501)

        fake_job = MagicMock(spec=ImportJob)
        fake_job.id = 99

        # Create a fake celery task module attribute so the controller import
        # succeeds (simulates task 16.1 being complete).
        mock_task = MagicMock()
        mock_task.delay.return_value = MagicMock()

        import celery_worker as cw

        with patch.object(cw, "process_csv_ingestion", mock_task):
            with app.app_context():
                with patch(
                    "app.controllers.ingestion_controller._build_service"
                ) as mock_build:
                    mock_service = MagicMock()
                    mock_service._create_import_job.return_value = fake_job
                    mock_build.return_value = mock_service

                    with patch("app.controllers.ingestion_controller.db") as mock_db:
                        mock_db.session.commit.return_value = None

                        resp = client.post(
                            f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
                            data={"file": (io.BytesIO(csv_bytes), "leads.csv")},
                            content_type="multipart/form-data",
                        )

        assert resp.status_code == 202
        data = resp.get_json()
        assert "import_job_id" in data

    def test_exactly_500_rows_returns_200(self, client, app):
        """POST /api/ingestion/csv with exactly 500 rows → 200 (sync path)."""
        csv_bytes = _make_csv_content(500)

        fake_job = MagicMock(spec=ImportJob)
        fake_job.id = 55
        fake_job.rows_processed = 500
        fake_job.rows_imported = 500
        fake_job.rows_skipped = 0

        with app.app_context():
            with patch(
                "app.controllers.ingestion_controller._build_service"
            ) as mock_build:
                mock_service = MagicMock()
                created_job = MagicMock(spec=ImportJob)
                created_job.id = 55
                mock_service._create_import_job.return_value = created_job
                mock_service.process_csv.return_value = fake_job
                mock_build.return_value = mock_service

                with patch("app.controllers.ingestion_controller.db") as mock_db:
                    mock_db.session.commit.return_value = None

                    resp = client.post(
                        f"/api/ingestion/csv?owner_user_id={OWNER_USER_ID}",
                        data={"file": (io.BytesIO(csv_bytes), "leads.csv")},
                        content_type="multipart/form-data",
                    )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Filter params forwarding — validate service is called with correct args
# ---------------------------------------------------------------------------

class TestFilterParamsForwarding:

    def test_foreclosure_records_forwarded_to_service(self, client, app):
        """Assert records from POST body are passed unmodified to the service."""
        records = [
            {"property_street": "1 Elm Ave", "owner_first_name": "Alice"},
            {"property_street": "2 Oak St", "owner_first_name": "Bob"},
        ]
        fake_job = _make_fake_job()

        with app.app_context():
            with patch(
                "app.controllers.ingestion_controller._build_service"
            ) as mock_build:
                mock_service = MagicMock()
                mock_service.ingest_foreclosure.return_value = fake_job
                mock_build.return_value = mock_service

                payload = {"owner_user_id": OWNER_USER_ID, "records": records}
                client.post(
                    "/api/ingestion/foreclosure",
                    data=json.dumps(payload),
                    content_type="application/json",
                )

                call_args = mock_service.ingest_foreclosure.call_args
                assert call_args[0][0] == records
                assert call_args[0][1] == OWNER_USER_ID
