"""
Integration smoke tests for the full property analysis workflow.

These tests exercise the complete confirm flow end-to-end:
  POST /analysis/start → PUT /step/1 → POST /step/2

If any of these break — due to schema changes, enum mismatches, missing
fields, serialization bugs, or controller regressions — these tests fail
before the bug reaches a user.
"""
import json
import pytest
from unittest.mock import patch
from datetime import date

from app import db
from app.models import AnalysisSession, WorkflowStep
from app.services.comparable_sales_finder import ComparableSalesFinder


# ---------------------------------------------------------------------------
# Shared test payload — mirrors what the frontend sends after confirming facts
# ---------------------------------------------------------------------------

VALID_PROPERTY_FACTS = {
    'address': '123 Main St, Chicago, IL 60601',
    'property_type': 'SINGLE_FAMILY',
    'units': 1,
    'bedrooms': 3,
    'bathrooms': 1.5,
    'square_footage': 1400,
    'lot_size': 4500,
    'year_built': 1955,
    'construction_type': 'FRAME',
    'interior_condition': 'AVERAGE',
    'assessed_value': 180000.0,
    'annual_taxes': 4200.0,
    'zoning': 'RS-3',
    'basement': True,
    'parking_spaces': 1,
    'latitude': 41.8781,
    'longitude': -87.6298,
    'data_source': 'manual',
    'user_modified_fields': [],
}

# Minimal comparable returned by the mock finder
_MOCK_COMPARABLE = {
    'address': '456 Oak Ave, Chicago, IL 60601',
    'sale_date': date(2025, 1, 15),
    'sale_price': 210000.0,
    'property_type': 'single_family',
    'units': 1,
    'bedrooms': 3,
    'bathrooms': 1.0,
    'square_footage': 1350,
    'lot_size': 4000,
    'year_built': 1950,
    'construction_type': 'frame',
    'interior_condition': 'average',
    'distance_miles': 0.3,
    'latitude': 41.879,
    'longitude': -87.631,
}

# Minimal comparable in Gemini JSON format (string dates, string enum values)
_MOCK_GEMINI_COMPARABLE = {
    'address': '456 Oak Ave, Chicago, IL 60601',
    'sale_date': '2025-01-15',
    'sale_price': 210000.0,
    'property_type': 'SINGLE_FAMILY',
    'units': 1,
    'bedrooms': 3,
    'bathrooms': 1.0,
    'square_footage': 1350,
    'lot_size': 4000,
    'year_built': 1950,
    'construction_type': 'FRAME',
    'interior_condition': 'AVERAGE',
    'distance_miles': 0.3,
    'latitude': 41.879,
    'longitude': -87.631,
    'similarity_notes': 'Similar single-family home.',
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _start_session(client, address='123 Main St, Chicago, IL 60601'):
    """POST /analysis/start and return (session_id, response_data)."""
    resp = client.post(
        '/api/analysis/start',
        data=json.dumps({'address': address, 'user_id': 'test_user'}),
        content_type='application/json',
    )
    assert resp.status_code == 201, f"start failed: {resp.data}"
    data = json.loads(resp.data)
    return data['session_id'], data


# ---------------------------------------------------------------------------
# Tests: POST /api/analysis/start
# ---------------------------------------------------------------------------

class TestStartAnalysis:
    def test_start_returns_session_id(self, client, app):
        session_id, data = _start_session(client)
        assert session_id is not None
        assert data['current_step'] == 'PROPERTY_FACTS'

    def test_start_creates_db_record(self, client, app):
        session_id, _ = _start_session(client)
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session is not None
            assert session.current_step == WorkflowStep.PROPERTY_FACTS

    def test_start_missing_address_returns_400(self, client, app):
        resp = client.post(
            '/api/analysis/start',
            data=json.dumps({'user_id': 'test_user'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_start_missing_user_id_returns_400(self, client, app):
        resp = client.post(
            '/api/analysis/start',
            data=json.dumps({'address': '123 Main St, Chicago, IL 60601'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_start_does_not_create_duplicate_on_repeat_call(self, client, app):
        """Two POSTs with the same address create two separate sessions (by design),
        but each must succeed independently."""
        sid1, _ = _start_session(client)
        sid2, _ = _start_session(client)
        assert sid1 != sid2  # Each call creates a new session — idempotency is on the frontend


# ---------------------------------------------------------------------------
# Tests: PUT /api/analysis/<session_id>/step/1  (confirm property facts)
# ---------------------------------------------------------------------------

class TestConfirmPropertyFacts:
    def test_confirm_full_payload_succeeds(self, client, app):
        session_id, _ = _start_session(client)
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(VALID_PROPERTY_FACTS),
            content_type='application/json',
        )
        assert resp.status_code == 200, f"confirm failed: {resp.data}"
        data = json.loads(resp.data)
        assert data['step'] == 'PROPERTY_FACTS'

    def test_confirm_persists_property_facts_to_db(self, client, app):
        session_id, _ = _start_session(client)
        client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(VALID_PROPERTY_FACTS),
            content_type='application/json',
        )
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.subject_property is not None
            assert session.subject_property.address == '123 Main St, Chicago, IL 60601'
            assert session.subject_property.bedrooms == 3

    def test_confirm_all_property_types_accepted(self, client, app):
        """Every valid property_type enum value must be accepted without a DB error."""
        for prop_type in ('SINGLE_FAMILY', 'MULTI_FAMILY', 'COMMERCIAL'):
            session_id, _ = _start_session(client)
            payload = {**VALID_PROPERTY_FACTS, 'property_type': prop_type}
            resp = client.put(
                f'/api/analysis/{session_id}/step/1',
                data=json.dumps(payload),
                content_type='application/json',
            )
            assert resp.status_code == 200, (
                f"property_type='{prop_type}' failed with {resp.status_code}: {resp.data}"
            )

    def test_confirm_all_construction_types_accepted(self, client, app):
        for constr_type in ('FRAME', 'BRICK', 'MASONRY'):
            session_id, _ = _start_session(client)
            payload = {**VALID_PROPERTY_FACTS, 'construction_type': constr_type}
            resp = client.put(
                f'/api/analysis/{session_id}/step/1',
                data=json.dumps(payload),
                content_type='application/json',
            )
            assert resp.status_code == 200, (
                f"construction_type='{constr_type}' failed: {resp.data}"
            )

    def test_confirm_all_interior_conditions_accepted(self, client, app):
        for condition in ('NEEDS_GUT', 'POOR', 'AVERAGE', 'NEW_RENO', 'HIGH_END'):
            session_id, _ = _start_session(client)
            payload = {**VALID_PROPERTY_FACTS, 'interior_condition': condition}
            resp = client.put(
                f'/api/analysis/{session_id}/step/1',
                data=json.dumps(payload),
                content_type='application/json',
            )
            assert resp.status_code == 200, (
                f"interior_condition='{condition}' failed: {resp.data}"
            )

    def test_confirm_partial_payload_succeeds(self, client, app):
        """Backend accepts partial updates — only address is required."""
        session_id, _ = _start_session(client)
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps({'address': '123 Main St, Chicago, IL 60601'}),
            content_type='application/json',
        )
        assert resp.status_code == 200, f"partial confirm failed: {resp.data}"

    def test_confirm_empty_zoning_accepted(self, client, app):
        """Empty zoning string must not cause a validation error."""
        session_id, _ = _start_session(client)
        payload = {**VALID_PROPERTY_FACTS, 'zoning': ''}
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200, f"empty zoning failed: {resp.data}"

    def test_confirm_zero_year_built_accepted(self, client, app):
        """year_built=0 (stub value for unknown) must not fail validation."""
        session_id, _ = _start_session(client)
        payload = {**VALID_PROPERTY_FACTS, 'year_built': 0}
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200, f"year_built=0 failed: {resp.data}"

    def test_confirm_unknown_fields_ignored(self, client, app):
        """Extra fields (e.g. user_id injected by middleware) must not cause 400."""
        session_id, _ = _start_session(client)
        payload = {**VALID_PROPERTY_FACTS, 'user_id': 'injected_by_interceptor', 'extra_field': 'ignored'}
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200, f"unknown fields caused failure: {resp.data}"

    def test_confirm_missing_address_returns_400(self, client, app):
        session_id, _ = _start_session(client)
        payload = {k: v for k, v in VALID_PROPERTY_FACTS.items() if k != 'address'}
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_confirm_invalid_session_returns_400(self, client, app):
        resp = client.put(
            '/api/analysis/nonexistent-session-id/step/1',
            data=json.dumps(VALID_PROPERTY_FACTS),
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests: POST /api/analysis/<session_id>/step/2  (advance to comparable search)
# ---------------------------------------------------------------------------

class TestAdvanceToComparableSearch:
    def _confirm_facts(self, client, session_id, payload=None):
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(payload or VALID_PROPERTY_FACTS),
            content_type='application/json',
        )
        assert resp.status_code == 200, f"confirm step failed: {resp.data}"

    def test_advance_to_step_2_succeeds(self, client, app):
        session_id, _ = _start_session(client)
        self._confirm_facts(client, session_id)
        resp = client.post(
            f'/api/analysis/{session_id}/step/2',
            data=json.dumps({}),
            content_type='application/json',
        )
        # Step 2 is now async — returns 202 with {"status": "accepted"}
        assert resp.status_code == 202, f"advance to step 2 failed: {resp.data}"
        data = json.loads(resp.data)
        assert data['status'] == 'accepted'
        assert data['session_id'] == session_id

    def test_advance_without_confirmed_facts_returns_400(self, client, app):
        """Cannot advance to step 2 if property facts were never confirmed."""
        session_id, _ = _start_session(client)
        resp = client.post(
            f'/api/analysis/{session_id}/step/2',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_advance_persists_comparables(self, client, app):
        """After POST /step/2 (202) and task execution, comparables are persisted."""
        session_id, _ = _start_session(client)
        self._confirm_facts(client, session_id)
        # POST /step/2 returns 202 and enqueues the task (delay is a no-op in tests)
        client.post(
            f'/api/analysis/{session_id}/step/2',
            data=json.dumps({}),
            content_type='application/json',
        )
        # Simulate the Celery worker executing the task
        from celery_worker import run_comparable_search_task
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService
        mock_gemini_result = {
            "comparables": [_MOCK_GEMINI_COMPARABLE] * 10,
            "narrative": "Test narrative.",
        }
        with patch("app.create_app", return_value=app), \
             patch.object(
                 GeminiComparableSearchService,
                 "search",
                 return_value=mock_gemini_result,
             ):
            run_comparable_search_task(session_id)
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.comparables.count() == 10


# ---------------------------------------------------------------------------
# Tests: Full end-to-end confirm flow (the regression test for the original bug)
# ---------------------------------------------------------------------------

class TestFullConfirmFlow:
    def test_full_flow_start_confirm_advance(self, client, app):
        """
        Regression test: exercises the exact sequence that was broken.
        POST /start → PUT /step/1 → POST /step/2 must all return 2xx.
        """
        with patch.object(
            ComparableSalesFinder, 'find_comparables',
            return_value=[_MOCK_COMPARABLE] * 10
        ):
            # 1. Start session
            start_resp = client.post(
                '/api/analysis/start',
                data=json.dumps({'address': '1443 W Foster Ave, Chicago, IL 60640', 'user_id': 'test_user'}),
                content_type='application/json',
            )
            assert start_resp.status_code == 201
            session_id = json.loads(start_resp.data)['session_id']

            # 2. Confirm property facts (MULTI_FAMILY — the enum that was broken)
            confirm_resp = client.put(
                f'/api/analysis/{session_id}/step/1',
                data=json.dumps({
                    **VALID_PROPERTY_FACTS,
                    'address': '1443 W Foster Ave, Chicago, IL 60640',
                    'property_type': 'MULTI_FAMILY',
                    'units': 3,
                }),
                content_type='application/json',
            )
            assert confirm_resp.status_code == 200, (
                f"Confirm step failed — this is the regression: {confirm_resp.data}"
            )

            # 3. Advance to comparable search — now async, returns 202
            advance_resp = client.post(
                f'/api/analysis/{session_id}/step/2',
                data=json.dumps({}),
                content_type='application/json',
            )
            assert advance_resp.status_code == 202, (
                f"Advance to step 2 failed: {advance_resp.data}"
            )
            assert json.loads(advance_resp.data)['status'] == 'accepted'


# ---------------------------------------------------------------------------
# Task 7.4 — Full 6-step end-to-end flow test
# ---------------------------------------------------------------------------

# Minimal ranked comparable returned by the mock scoring engine
_MOCK_RANKED_COMP_DATA = {
    'comparable_id': None,   # filled in dynamically
    'session_id': None,
    'total_score': 90.0,
    'rank': 1,
    'recency_score': 85.0,
    'proximity_score': 80.0,
    'units_score': 100.0,
    'beds_baths_score': 100.0,
    'sqft_score': 95.0,
    'construction_score': 100.0,
    'interior_score': 100.0,
}


class TestCompleteAnalysisFlow:
    """
    Task 7.4 — Full 6-step end-to-end regression test.

    Runs all 6 steps in sequence with mocked external services and verifies:
    - Each step transition returns 2xx
    - Session state advances correctly
    - completed_steps and step_results are populated
    - The final session is at REPORT_GENERATION
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _start(self, client):
        resp = client.post(
            '/api/analysis/start',
            data=json.dumps({'address': '1443 W Foster Ave, Chicago, IL 60640', 'user_id': 'e2e_user'}),
            content_type='application/json',
        )
        assert resp.status_code == 201, f"start failed: {resp.data}"
        return json.loads(resp.data)['session_id']

    def _confirm_facts(self, client, session_id):
        payload = {
            **VALID_PROPERTY_FACTS,
            'address': '1443 W Foster Ave, Chicago, IL 60640',
            'property_type': 'MULTI_FAMILY',
            'units': 4,
        }
        resp = client.put(
            f'/api/analysis/{session_id}/step/1',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200, f"step 1 failed: {resp.data}"
        return json.loads(resp.data)

    def _advance(self, client, session_id, step_number):
        resp = client.post(
            f'/api/analysis/{session_id}/step/{step_number}',
            data=json.dumps({}),
            content_type='application/json',
        )
        # Step 2 is async and returns 202; all other steps return 200
        if step_number == 2:
            assert resp.status_code == 202, f"step {step_number} failed: {resp.data}"
        else:
            assert resp.status_code == 200, f"step {step_number} failed: {resp.data}"
        return json.loads(resp.data)

    # ------------------------------------------------------------------
    # The full flow test
    # ------------------------------------------------------------------

    def test_complete_analysis_flow_all_6_steps(self, client, app):
        """
        Runs all 6 steps in sequence with mocked external services.

        Step sequence:
          1. POST /start                    → session created at PROPERTY_FACTS
          2. PUT  /step/1                   → property facts confirmed
          3. POST /step/2                   → comparable search (mocked)
          4. POST /step/3                   → comparable review (no-op)
          5. POST /step/4                   → weighted scoring (real engine)
          6. POST /step/5                   → valuation models (real engine)
          7. POST /step/6                   → report generation (mocked)
        """
        from unittest.mock import patch, MagicMock
        from app.services.comparable_sales_finder import ComparableSalesFinder
        from app.services.report_generator import ReportGenerator

        mock_comps = [_MOCK_COMPARABLE] * 3  # 3 comps — enough for dev/test (MIN_COMPARABLES=1)

        mock_report = {
            'property_summary': 'Test summary',
            'valuation': 'Test valuation',
            'scenarios': 'Test scenarios',
        }

        with patch.object(ComparableSalesFinder, 'find_comparables', return_value=mock_comps), \
             patch.object(ReportGenerator, 'generate_report', return_value=mock_report):

            # Step 1: Start session
            session_id = self._start(client)

            with app.app_context():
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                assert session.current_step == WorkflowStep.PROPERTY_FACTS

            # Step 2: Confirm property facts (PUT /step/1)
            self._confirm_facts(client, session_id)

            with app.app_context():
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                assert session.subject_property is not None

            # Step 3: Advance to COMPARABLE_SEARCH (POST /step/2)
            # Step 2 is async — returns 202 with {"status": "accepted", "session_id": ...}
            # The Celery task runs in the background; in tests .delay is a no-op mock.
            # We simulate the task completing by calling run_comparable_search_task directly.
            result = self._advance(client, session_id, 2)
            assert result['status'] == 'accepted'

            # Simulate the Celery worker executing the task
            from celery_worker import run_comparable_search_task
            from app.services.gemini_comparable_search_service import GeminiComparableSearchService
            mock_gemini_result = {
                "comparables": [_MOCK_GEMINI_COMPARABLE] * 3,
                "narrative": "Test narrative.",
            }
            with patch("app.create_app", return_value=app), \
                 patch.object(
                     GeminiComparableSearchService,
                     "search",
                     return_value=mock_gemini_result,
                 ):
                run_comparable_search_task(session_id)

            with app.app_context():
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                assert session.comparables.count() == 3
                assert 'PROPERTY_FACTS' in session.completed_steps
                assert 'COMPARABLE_SEARCH' in session.step_results

            # Step 4: Advance to COMPARABLE_REVIEW (POST /step/3)
            result = self._advance(client, session_id, 3)
            assert result['current_step'] == 'COMPARABLE_REVIEW'

            with app.app_context():
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                assert 'COMPARABLE_SEARCH' in session.completed_steps
                assert 'COMPARABLE_REVIEW' in session.step_results

            # Step 5: Advance to WEIGHTED_SCORING (POST /step/4)
            result = self._advance(client, session_id, 4)
            assert result['current_step'] == 'WEIGHTED_SCORING'
            assert result['result']['status'] == 'complete'
            assert result['result']['ranked_count'] == 3

            with app.app_context():
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                assert session.ranked_comparables.count() == 3
                assert 'COMPARABLE_REVIEW' in session.completed_steps
                assert 'WEIGHTED_SCORING' in session.step_results

            # Step 6: Advance to VALUATION_MODELS (POST /step/5)
            result = self._advance(client, session_id, 5)
            assert result['current_step'] == 'VALUATION_MODELS'
            assert result['result']['status'] == 'complete'
            assert result['result']['arv_range']['likely'] > 0
            assert result['result']['confidence_score'] is not None

            with app.app_context():
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                assert session.valuation_result is not None
                assert 'WEIGHTED_SCORING' in session.completed_steps
                assert 'VALUATION_MODELS' in session.step_results

            # Step 7: Advance to REPORT_GENERATION (POST /step/6)
            result = self._advance(client, session_id, 6)
            assert result['current_step'] == 'REPORT_GENERATION'
            assert result['result']['status'] == 'complete'

            with app.app_context():
                session = AnalysisSession.query.filter_by(session_id=session_id).first()
                assert session.current_step == WorkflowStep.REPORT_GENERATION
                assert 'VALUATION_MODELS' in session.completed_steps
                assert 'REPORT_GENERATION' in session.step_results

                # All 6 steps should be in completed_steps
                expected_steps = [
                    'PROPERTY_FACTS', 'COMPARABLE_SEARCH', 'COMPARABLE_REVIEW',
                    'WEIGHTED_SCORING', 'VALUATION_MODELS',
                ]
                for step_name in expected_steps:
                    assert step_name in session.completed_steps, (
                        f"Expected '{step_name}' in completed_steps, got: {session.completed_steps}"
                    )

    def test_each_step_transition_returns_2xx(self, client, app):
        """Every step transition in the 6-step flow returns a 2xx status code."""
        from unittest.mock import patch
        from app.services.report_generator import ReportGenerator
        from celery_worker import run_comparable_search_task
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService

        mock_gemini_result = {
            "comparables": [_MOCK_GEMINI_COMPARABLE] * 3,
            "narrative": "Test narrative.",
        }
        mock_report = {'summary': 'ok'}

        with patch.object(ReportGenerator, 'generate_report', return_value=mock_report):

            session_id = self._start(client)
            self._confirm_facts(client, session_id)

            for step_number in range(2, 7):
                resp = client.post(
                    f'/api/analysis/{session_id}/step/{step_number}',
                    data=json.dumps({}),
                    content_type='application/json',
                )
                assert 200 <= resp.status_code < 300, (
                    f"Step {step_number} returned {resp.status_code}: {resp.data}"
                )
                # Step 2 is async — simulate the Celery worker completing the task
                # so the session advances to COMPARABLE_SEARCH before step 3 is attempted.
                if step_number == 2:
                    with patch("app.create_app", return_value=app), \
                         patch.object(
                             GeminiComparableSearchService,
                             "search",
                             return_value=mock_gemini_result,
                         ):
                        run_comparable_search_task(session_id)

    def test_session_state_advances_correctly_through_all_steps(self, client, app):
        """Session current_step advances through all 6 steps in order."""
        from unittest.mock import patch
        from app.services.report_generator import ReportGenerator
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService

        expected_steps = [
            'COMPARABLE_SEARCH',
            'COMPARABLE_REVIEW',
            'WEIGHTED_SCORING',
            'VALUATION_MODELS',
            'REPORT_GENERATION',
        ]

        mock_gemini_result = {
            "comparables": [_MOCK_GEMINI_COMPARABLE] * 3,
            "narrative": "Test narrative.",
        }
        mock_report = {'summary': 'ok'}

        with patch.object(ReportGenerator, 'generate_report', return_value=mock_report):

            session_id = self._start(client)
            self._confirm_facts(client, session_id)

            for step_number, expected_step in zip(range(2, 7), expected_steps):
                result = self._advance(client, session_id, step_number)
                if step_number == 2:
                    # Step 2 is async — returns 202 sentinel; simulate task completion
                    assert result['status'] == 'accepted'
                    from celery_worker import run_comparable_search_task
                    with patch("app.create_app", return_value=app), \
                         patch.object(
                             GeminiComparableSearchService,
                             "search",
                             return_value=mock_gemini_result,
                         ):
                        run_comparable_search_task(session_id)
                    # Verify session advanced via DB
                    with app.app_context():
                        session = AnalysisSession.query.filter_by(session_id=session_id).first()
                        assert session.current_step.name == expected_step, (
                            f"After task completion for step 2, expected current_step="
                            f"'{expected_step}', got '{session.current_step.name}'"
                        )
                else:
                    assert result['current_step'] == expected_step, (
                        f"After advancing to step {step_number}, expected current_step="
                        f"'{expected_step}', got '{result['current_step']}'"
                    )
