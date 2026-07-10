"""Tests for commercial building ownership backfill."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app import db
from app.models.address_group_analysis import AddressGroupAnalysis
from app.models.lead import Lead
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.building_ownership_backfill import (
    is_commercial_cook_county_lead,
    lead_needs_building_ownership_analysis,
    query_lead_ids_for_building_ownership_backfill,
    try_claim_startup_backfill_dispatch,
)
from app.services.building_ownership_service import BuildingOwnershipService

_AUTH_HEADERS = {'X-User-Id': 'test-user'}
_BACKFILL_URL = '/api/leads/building-ownership/backfill'


def _auth_headers(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _make_admin_token(app) -> str:
    with app.app_context():
        admin = User(
            user_id=str(uuid.uuid4()),
            email='admin-backfill@test.com',
            email_lower='admin-backfill@test.com',
            password_hash='$2b$12$fakehashfakehashfakehashfakehashfakehashfakehash',
            display_name='Admin',
            is_active=True,
            is_admin=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(admin)
        db.session.commit()
        return AuthService().issue_token(admin)


def _commercial_lead(app, street='3017 W George St', **kwargs):
    with app.app_context():
        lead = Lead(
            owner_first_name='Test',
            owner_last_name='Owner',
            property_street=street,
            property_city='Chicago',
            property_state='IL',
            property_zip='60618',
            lead_category='commercial',
            lead_status=kwargs.get('lead_status', 'skip_trace'),
            lead_score=50,
            has_property_match=True,
            source_type='import',
        )
        db.session.add(lead)
        db.session.commit()
        return lead.id


class TestBuildingOwnershipBackfill:
    def test_commercial_chicago_lead_is_eligible(self, app):
        with app.app_context():
            lead = db.session.get(Lead, _commercial_lead(app))
            assert is_commercial_cook_county_lead(lead) is True
            assert lead_needs_building_ownership_analysis(lead) is True

    def test_residential_lead_not_eligible(self, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='Res',
                owner_last_name='Owner',
                property_street='100 Main St',
                property_city='Chicago',
                property_state='IL',
                lead_category='residential',
                lead_status='skip_trace',
                lead_score=50,
                has_property_match=True,
                source_type='import',
            )
            db.session.add(lead)
            db.session.commit()
            assert lead_needs_building_ownership_analysis(lead) is False

    def test_manual_override_skips_reanalysis(self, app):
        with app.app_context():
            lead_id = _commercial_lead(app)
            lead = db.session.get(Lead, lead_id)
            analysis = AddressGroupAnalysis(
                normalized_address='3017 W GEORGE ST',
                source_type='commercial',
                condo_risk_status='likely_not_condo',
                building_sale_possible='yes',
                manually_reviewed=True,
                manual_override_status='likely_not_condo',
                analyzed_at=datetime.now(timezone.utc) - timedelta(days=90),
            )
            db.session.add(analysis)
            db.session.flush()
            lead.condo_analysis_id = analysis.id
            db.session.commit()
            assert lead_needs_building_ownership_analysis(lead) is False

    def test_query_returns_commercial_leads(self, app):
        lead_id = _commercial_lead(app)
        with app.app_context():
            ids = query_lead_ids_for_building_ownership_backfill(last_id=0, limit=50)
            assert lead_id in ids

    def test_analyze_lead_skips_current_analysis(self, app):
        with app.app_context():
            lead_id = _commercial_lead(app)
            lead = db.session.get(Lead, lead_id)
            analysis = AddressGroupAnalysis(
                normalized_address='3017 W GEORGE ST',
                source_type='commercial',
                condo_risk_status='likely_not_condo',
                building_sale_possible='yes',
                analyzed_at=datetime.now(timezone.utc),
            )
            db.session.add(analysis)
            db.session.flush()
            lead.condo_analysis_id = analysis.id
            lead.condo_risk_status = 'likely_not_condo'
            lead.building_sale_possible = 'yes'
            db.session.commit()

            result = BuildingOwnershipService().analyze_lead(lead_id)
            assert result.get('skipped') is True
            assert result.get('skip_reason') == 'analysis_current'

    def test_backfill_endpoint_requires_admin(self, client, app):
        resp = client.post(_BACKFILL_URL, json={}, headers=_AUTH_HEADERS)
        assert resp.status_code == 403

    def test_backfill_endpoint_allows_admin(self, client, app):
        token = _make_admin_token(app)
        with app.app_context():
            resp = client.post(
                _BACKFILL_URL,
                json={'per_run_cap': 1, 'enqueue_async': False, 'last_id': 0},
                headers=_auth_headers(token),
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'processed' in data


class TestStartupBackfillDispatchGuard:
    def test_redis_held_elsewhere_skips_pg_lock(self, app):
        with app.app_context():
            with patch(
                'app.services.building_ownership_backfill._redis_startup_claim_status',
                return_value=False,
            ):
                with patch.object(db.session, 'execute') as mock_execute:
                    assert try_claim_startup_backfill_dispatch() is False
                    mock_execute.assert_not_called()

    def test_pg_lock_authoritative_when_redis_unavailable(self, app):
        with app.app_context():
            with patch(
                'app.services.building_ownership_backfill._redis_startup_claim_status',
                return_value=None,
            ):
                mock_result = MagicMock()
                mock_result.scalar.return_value = True
                with patch.object(db.session, 'execute', return_value=mock_result):
                    assert try_claim_startup_backfill_dispatch() is True

    def test_pg_failure_fails_closed(self, app):
        with app.app_context():
            with patch(
                'app.services.building_ownership_backfill._redis_startup_claim_status',
                return_value=True,
            ):
                with patch.object(db.session, 'execute', side_effect=RuntimeError('db down')):
                    with patch(
                        'app.services.building_ownership_backfill._release_redis_startup_claim',
                    ) as mock_release:
                        assert try_claim_startup_backfill_dispatch() is False
                        mock_release.assert_called_once()

    def test_pg_lock_not_acquired_releases_redis_claim(self, app):
        with app.app_context():
            with patch(
                'app.services.building_ownership_backfill._redis_startup_claim_status',
                return_value=True,
            ):
                mock_result = MagicMock()
                mock_result.scalar.return_value = False
                with patch.object(db.session, 'execute', return_value=mock_result):
                    with patch(
                        'app.services.building_ownership_backfill._release_redis_startup_claim',
                    ) as mock_release:
                        assert try_claim_startup_backfill_dispatch() is False
                        mock_release.assert_called_once()
