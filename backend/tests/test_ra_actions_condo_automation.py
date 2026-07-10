"""Tests for property match review and building ownership endpoints."""
from datetime import datetime, timezone

import pytest

from app import db
from app.models import Lead

_AUTH_HEADERS = {'X-User-Id': 'test-user'}


def _make_lead(app, street='100 Test St', **kwargs):
    with app.app_context():
        lead = Lead(
            owner_first_name='Test',
            owner_last_name='Owner',
            property_street=street,
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            lead_status=kwargs.get('lead_status', 'skip_trace'),
            lead_score=50,
            has_property_match=kwargs.get('has_property_match', False),
            source_type='import',
            lead_category=kwargs.get('lead_category', 'residential'),
        )
        db.session.add(lead)
        db.session.commit()
        return lead.id


class TestPropertyMatchPreview:
    def test_preview_requires_auth(self, client):
        resp = client.get('/api/leads/1/property-match/preview')
        assert resp.status_code == 401

    def test_preview_not_found(self, client, app):
        resp = client.get('/api/leads/999999/property-match/preview', headers=_AUTH_HEADERS)
        assert resp.status_code == 400


class TestNoNextActionBulk:
    def test_status_counts_endpoint(self, client, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='Bulk',
                owner_last_name='Test',
                property_street='200 Bulk St',
                property_city='Chicago',
                property_state='IL',
                lead_status='awaiting_skip_trace',
                lead_score=40,
                has_property_match=True,
                recommended_action=None,
                source_type='import',
            )
            db.session.add(lead)
            db.session.commit()

        resp = client.get('/api/queues/no-next-action/status-counts', headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_bulk_update_status_requires_body(self, client):
        resp = client.post(
            '/api/queues/no-next-action/bulk-update-status',
            json={},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 400


class TestImportJobsAuth:
    def test_list_import_jobs_requires_auth(self, client):
        resp = client.get('/api/leads/import/jobs')
        assert resp.status_code == 401

    def test_default_user_job_visible_to_authenticated_user(self, client, app):
        from app.models.import_job import ImportJob

        with app.app_context():
            job = ImportJob(
                user_id='default_user',
                spreadsheet_id='sheet-1',
                sheet_name='Sheet1',
                status='completed',
                rows_imported=42,
                completed_at=datetime.now(timezone.utc),
            )
            db.session.add(job)
            db.session.commit()

        resp = client.get('/api/leads/import/jobs', headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] >= 1
        assert any(j['rows_imported'] == 42 for j in data['jobs'])
