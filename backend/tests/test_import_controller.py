"""Integration tests for Import API endpoints."""
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app import db
from app.models import ImportJob, FieldMapping, OAuthToken, Lead
from app.services.google_sheets_importer import AuthResult, SheetInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_oauth_token(user_id='default'):
    """Create a fake OAuth token record."""
    token = OAuthToken(
        user_id=user_id,
        encrypted_refresh_token=b'fake-encrypted-token',
        token_expiry=datetime(2030, 1, 1),
    )
    db.session.add(token)
    db.session.commit()
    return token


def _create_field_mapping(user_id='default', spreadsheet_id='sheet123',
                          sheet_name='Sheet1', mapping=None):
    """Create a field mapping record."""
    if mapping is None:
        mapping = {'Address': 'property_street', 'First Name': 'owner_first_name', 'Last Name': 'owner_last_name'}
    fm = FieldMapping(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        sheet_name=sheet_name,
        mapping=mapping,
    )
    db.session.add(fm)
    db.session.commit()
    return fm


def _create_import_job(user_id='default', spreadsheet_id='sheet123',
                       sheet_name='Sheet1', status='completed',
                       field_mapping_id=None, **overrides):
    """Create an import job record."""
    job = ImportJob(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        sheet_name=sheet_name,
        field_mapping_id=field_mapping_id,
        status=status,
        total_rows=overrides.get('total_rows', 10),
        rows_processed=overrides.get('rows_processed', 10),
        rows_imported=overrides.get('rows_imported', 8),
        rows_skipped=overrides.get('rows_skipped', 2),
        error_log=overrides.get('error_log', []),
        started_at=overrides.get('started_at', datetime.utcnow()),
        completed_at=overrides.get('completed_at', datetime.utcnow()),
    )
    db.session.add(job)
    db.session.commit()
    return job


# ---------------------------------------------------------------------------
# Tests: POST /api/leads/import/auth
# ---------------------------------------------------------------------------

class TestAuthenticate:
    """Tests for the OAuth2 authentication endpoint."""

    @patch('app.controllers.import_controller.importer')
    def test_auth_success(self, mock_importer, client, app):
        """Successful authentication returns 200."""
        mock_importer.authenticate.return_value = AuthResult(
            success=True, user_id='user1',
        )
        resp = client.post(
            '/api/leads/import/auth',
            data=json.dumps({'user_id': 'user1', 'refresh_token': 'tok'}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['user_id'] == 'user1'
        assert data['message'] == 'Authentication successful'

    @patch('app.controllers.import_controller.importer')
    def test_auth_failure(self, mock_importer, client, app):
        """Failed authentication returns 401."""
        mock_importer.authenticate.return_value = AuthResult(
            success=False, error='Invalid credentials',
        )
        resp = client.post(
            '/api/leads/import/auth',
            data=json.dumps({'user_id': 'user1', 'auth_code': 'bad'}),
            content_type='application/json',
        )
        assert resp.status_code == 401
        data = json.loads(resp.data)
        assert data['error'] == 'Authentication failed'

    def test_auth_no_body(self, client, app):
        """Missing request body returns 400."""
        resp = client.post(
            '/api/leads/import/auth',
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests: GET /api/leads/import/sheets
# ---------------------------------------------------------------------------

class TestListSheets:
    """Tests for the sheet listing endpoint."""

    @patch('app.controllers.import_controller.importer')
    def test_list_sheets_success(self, mock_importer, client, app):
        """Returns sheets when authenticated."""
        with app.app_context():
            _create_oauth_token('user1')

        mock_importer.list_sheets.return_value = [
            SheetInfo(sheet_id=0, title='Leads', row_count=100, column_count=10),
            SheetInfo(sheet_id=1, title='Contacts', row_count=50, column_count=5),
        ]

        resp = client.get(
            '/api/leads/import/sheets?spreadsheet_id=sheet123&user_id=user1',
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['sheets']) == 2
        assert data['sheets'][0]['title'] == 'Leads'
        assert data['sheets'][1]['row_count'] == 50

    def test_list_sheets_missing_spreadsheet_id(self, client, app):
        """Returns 400 when spreadsheet_id is missing."""
        resp = client.get('/api/leads/import/sheets?user_id=user1')
        assert resp.status_code == 400

    def test_list_sheets_no_token(self, client, app):
        """Returns 401 when no OAuth token exists."""
        resp = client.get(
            '/api/leads/import/sheets?spreadsheet_id=sheet123&user_id=notoken',
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: GET /api/leads/import/headers
# ---------------------------------------------------------------------------

class TestReadHeaders:
    """Tests for the header reading endpoint."""

    @patch('app.controllers.import_controller.importer')
    def test_read_headers_success(self, mock_importer, client, app):
        """Returns headers and auto-mapping."""
        with app.app_context():
            _create_oauth_token('user1')

        mock_importer.read_headers.return_value = ['Address', 'Owner Name', 'Phone']
        mock_importer.auto_map_fields.return_value = {
            'Address': 'property_street',
            'Owner Name': 'owner_first_name',
            'Phone': 'phone_1',
        }

        resp = client.get(
            '/api/leads/import/headers'
            '?spreadsheet_id=sheet123&sheet_name=Sheet1&user_id=user1',
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['headers'] == ['Address', 'Owner Name', 'Phone']
        assert data['auto_mapping']['Address'] == 'property_street'

    def test_read_headers_missing_params(self, client, app):
        """Returns 400 when required params are missing."""
        resp = client.get('/api/leads/import/headers?user_id=user1')
        assert resp.status_code == 400

        resp2 = client.get(
            '/api/leads/import/headers?spreadsheet_id=sheet123&user_id=user1',
        )
        assert resp2.status_code == 400

    def test_read_headers_no_token(self, client, app):
        """Returns 401 when no OAuth token exists."""
        resp = client.get(
            '/api/leads/import/headers'
            '?spreadsheet_id=sheet123&sheet_name=Sheet1&user_id=notoken',
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: POST /api/leads/import/mapping
# ---------------------------------------------------------------------------

class TestSaveMapping:
    """Tests for the field mapping save/update endpoint."""

    def test_save_mapping_create(self, client, app):
        """Creates a new field mapping and returns 201."""
        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
            'mapping': {'Address': 'property_street', 'First Name': 'owner_first_name', 'Last Name': 'owner_last_name'},
        }
        resp = client.post(
            '/api/leads/import/mapping',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data['user_id'] == 'user1'
        assert data['mapping']['Address'] == 'property_street'

    def test_save_mapping_update(self, client, app):
        """Updates an existing field mapping and returns 200."""
        with app.app_context():
            _create_field_mapping('user1', 'sheet123', 'Sheet1')

        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
            'mapping': {
                'Address': 'property_street',
                'First Name': 'owner_first_name',
                'Last Name': 'owner_last_name',
                'Phone': 'phone_1',
            },
        }
        resp = client.post(
            '/api/leads/import/mapping',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'Phone' in data['mapping']

    def test_save_mapping_missing_required_fields(self, client, app):
        """Returns 400 when required request fields are missing."""
        payload = {'user_id': 'user1'}
        resp = client.post(
            '/api/leads/import/mapping',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_save_mapping_no_required_db_fields(self, client, app):
        """Returns 201 when mapping has no required DB fields (none are required now)."""
        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
            'mapping': {'Phone': 'phone_1'},
        }
        resp = client.post(
            '/api/leads/import/mapping',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 201

    def test_save_mapping_invalid_mapping_type(self, client, app):
        """Returns 400 when mapping is not a dict."""
        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
            'mapping': 'not a dict',
        }
        resp = client.post(
            '/api/leads/import/mapping',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_save_mapping_no_body(self, client, app):
        """Returns 400 when request body is empty."""
        resp = client.post(
            '/api/leads/import/mapping',
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests: POST /api/leads/import/start
# ---------------------------------------------------------------------------

class TestStartImport:
    """Tests for the import start endpoint."""

    @patch('app.controllers.import_controller._enqueue_import_task')
    def test_start_import_success(self, mock_enqueue, client, app):
        """Creates an ImportJob and returns 201."""
        with app.app_context():
            _create_oauth_token('user1')
            fm = _create_field_mapping('user1', 'sheet123', 'Sheet1')

        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
        }
        resp = client.post(
            '/api/leads/import/start',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data['user_id'] == 'user1'
        assert data['spreadsheet_id'] == 'sheet123'
        assert 'id' in data
        mock_enqueue.assert_called_once()

    def test_start_import_missing_fields(self, client, app):
        """Returns 400 when required fields are missing."""
        payload = {'user_id': 'user1'}
        resp = client.post(
            '/api/leads/import/start',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_start_import_no_token(self, client, app):
        """Returns 401 when no OAuth token exists."""
        with app.app_context():
            _create_field_mapping('user1', 'sheet123', 'Sheet1')

        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
        }
        resp = client.post(
            '/api/leads/import/start',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 401

    def test_start_import_no_mapping(self, client, app):
        """Returns 400 when no field mapping exists."""
        with app.app_context():
            _create_oauth_token('user1')

        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
        }
        resp = client.post(
            '/api/leads/import/start',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    @patch('app.controllers.import_controller._enqueue_import_task')
    def test_start_import_conflict(self, mock_enqueue, client, app):
        """Returns 409 when an import is already in progress."""
        with app.app_context():
            _create_oauth_token('user1')
            fm = _create_field_mapping('user1', 'sheet123', 'Sheet1')
            _create_import_job(
                'user1', 'sheet123', 'Sheet1',
                status='in_progress',
                field_mapping_id=fm.id,
            )

        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
        }
        resp = client.post(
            '/api/leads/import/start',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 409

    def test_start_import_no_body(self, client, app):
        """Returns 400 when request body is empty."""
        resp = client.post(
            '/api/leads/import/start',
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_start_import_invalid_mapping_id(self, client, app):
        """Returns 404 when field_mapping_id doesn't exist."""
        with app.app_context():
            _create_oauth_token('user1')

        payload = {
            'user_id': 'user1',
            'spreadsheet_id': 'sheet123',
            'sheet_name': 'Sheet1',
            'field_mapping_id': 99999,
        }
        resp = client.post(
            '/api/leads/import/start',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /api/leads/import/jobs
# ---------------------------------------------------------------------------

class TestListImportJobs:
    """Tests for the import job listing endpoint."""

    def test_list_jobs_empty(self, client, app):
        """Empty database returns empty list."""
        resp = client.get('/api/leads/import/jobs')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['jobs'] == []
        assert data['total'] == 0

    def test_list_jobs_returns_jobs(self, client, app):
        """Returns created import jobs."""
        with app.app_context():
            _create_import_job()

        resp = client.get('/api/leads/import/jobs')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['jobs'][0]['status'] == 'completed'

    def test_list_jobs_filter_by_user(self, client, app):
        """Filter by user_id."""
        with app.app_context():
            _create_import_job(user_id='user1', spreadsheet_id='s1')
            _create_import_job(user_id='user2', spreadsheet_id='s2')

        resp = client.get('/api/leads/import/jobs?user_id=user1')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['jobs'][0]['user_id'] == 'user1'

    def test_list_jobs_filter_by_status(self, client, app):
        """Filter by status."""
        with app.app_context():
            _create_import_job(spreadsheet_id='s1', status='completed')
            _create_import_job(spreadsheet_id='s2', status='failed')

        resp = client.get('/api/leads/import/jobs?status=failed')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['jobs'][0]['status'] == 'failed'

    def test_list_jobs_pagination(self, client, app):
        """Pagination works correctly."""
        with app.app_context():
            for i in range(15):
                _create_import_job(spreadsheet_id=f's{i}')

        resp = client.get('/api/leads/import/jobs?page=1&per_page=10')
        data = json.loads(resp.data)
        assert len(data['jobs']) == 10
        assert data['total'] == 15
        assert data['pages'] == 2


# ---------------------------------------------------------------------------
# Tests: GET /api/leads/import/jobs/<job_id>
# ---------------------------------------------------------------------------

class TestGetImportJob:
    """Tests for the import job detail endpoint."""

    def test_get_job_success(self, client, app):
        """Returns full job details."""
        with app.app_context():
            job = _create_import_job(
                error_log=[{'row': 3, 'errors': ['Missing required field: owner_name']}],
            )
            job_id = job.id

        resp = client.get(f'/api/leads/import/jobs/{job_id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['id'] == job_id
        assert data['total_rows'] == 10
        assert data['rows_imported'] == 8
        assert data['rows_skipped'] == 2
        assert len(data['error_log']) == 1
        assert data['error_log'][0]['row'] == 3

    def test_get_job_not_found(self, client, app):
        """Returns 404 for non-existent job."""
        resp = client.get('/api/leads/import/jobs/99999')
        assert resp.status_code == 404
        data = json.loads(resp.data)
        assert data['error'] == 'Import job not found'


# ---------------------------------------------------------------------------
# Tests: POST /api/leads/import/jobs/<job_id>/rerun
# ---------------------------------------------------------------------------

class TestRerunImport:
    """Tests for the import re-run endpoint."""

    @patch('app.controllers.import_controller._enqueue_import_task')
    def test_rerun_success(self, mock_enqueue, client, app):
        """Creates a new job from the original and returns 201."""
        with app.app_context():
            _create_oauth_token('user1')
            fm = _create_field_mapping('user1', 'sheet123', 'Sheet1')
            original = _create_import_job(
                'user1', 'sheet123', 'Sheet1',
                status='completed',
                field_mapping_id=fm.id,
            )
            original_id = original.id

        resp = client.post(f'/api/leads/import/jobs/{original_id}/rerun')
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data['original_job_id'] == original_id
        assert data['spreadsheet_id'] == 'sheet123'
        assert data['id'] != original_id
        mock_enqueue.assert_called_once()

    def test_rerun_not_found(self, client, app):
        """Returns 404 for non-existent original job."""
        resp = client.post('/api/leads/import/jobs/99999/rerun')
        assert resp.status_code == 404

    @patch('app.controllers.import_controller._enqueue_import_task')
    def test_rerun_conflict(self, mock_enqueue, client, app):
        """Returns 409 when an import is already in progress."""
        with app.app_context():
            _create_oauth_token('user1')
            fm = _create_field_mapping('user1', 'sheet123', 'Sheet1')
            original = _create_import_job(
                'user1', 'sheet123', 'Sheet1',
                status='completed',
                field_mapping_id=fm.id,
            )
            # Create an active job for the same spreadsheet
            _create_import_job(
                'user1', 'sheet123', 'Sheet1',
                status='in_progress',
                field_mapping_id=fm.id,
            )
            original_id = original.id

        resp = client.post(f'/api/leads/import/jobs/{original_id}/rerun')
        assert resp.status_code == 409

    def test_rerun_no_token(self, client, app):
        """Returns 401 when OAuth token is missing."""
        with app.app_context():
            fm = _create_field_mapping('user1', 'sheet123', 'Sheet1')
            original = _create_import_job(
                'user1', 'sheet123', 'Sheet1',
                status='completed',
                field_mapping_id=fm.id,
            )
            original_id = original.id

        resp = client.post(f'/api/leads/import/jobs/{original_id}/rerun')
        assert resp.status_code == 401
