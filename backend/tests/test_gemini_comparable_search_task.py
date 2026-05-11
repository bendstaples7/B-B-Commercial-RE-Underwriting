"""Tests for run_comparable_search_task in celery_worker.py.

Covers:
  - Property 5: Comparable count matches Gemini response list length
  - Property 6: Narrative round-trip preservation
  - Unit tests for the updated Celery task

Implementation note
-------------------
``run_comparable_search_task`` calls ``create_app()`` internally to obtain a
Flask app context.  In tests we patch ``celery_worker.create_app`` to return
the test app (which already has an in-memory SQLite DB with all tables
created) so the task operates on the same database as the test assertions.

``GeminiComparableSearchService`` is imported lazily inside the task function,
so the correct patch target is the service's own module path:
``app.services.gemini_comparable_search_service.GeminiComparableSearchService``.
"""
import os
import uuid
import pytest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch, MagicMock

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_comparable_dict(i: int = 0) -> dict:
    """Return a minimal valid comparable dict for mocking Gemini responses."""
    return {
        'address': f'{100 + i} Test St, Chicago, IL 60601',
        'sale_date': '2024-01-15',
        'sale_price': 400000.0 + i * 1000,
        'property_type': 'single_family',
        'units': 1,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'square_footage': 1500,
        'lot_size': 5000,
        'year_built': 1990,
        'construction_type': 'frame',
        'interior_condition': 'average',
        'distance_miles': 0.5 + i * 0.1,
        'latitude': 41.8781 + i * 0.001,
        'longitude': -87.6298 + i * 0.001,
        'similarity_notes': f'Similar property {i}',
    }


def _make_gemini_result(n: int, narrative: str = 'Test narrative') -> dict:
    """Return a mock Gemini search result with N comparables."""
    return {
        'comparables': [_make_comparable_dict(i) for i in range(n)],
        'narrative': narrative,
    }


def _create_session_with_property(app):
    """Create a minimal AnalysisSession with a linked PropertyFacts in the DB.

    Returns the session_id string (UUID) so the task can look it up.
    Must be called within an active app context.
    """
    from app import db
    from app.models import AnalysisSession
    from app.models.analysis_session import WorkflowStep
    from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition

    session_id = str(uuid.uuid4())

    session = AnalysisSession(
        session_id=session_id,
        user_id='test-user',
        created_at=datetime.utcnow(),
        current_step=WorkflowStep.PROPERTY_FACTS,
        loading=True,
        step_results={},
        completed_steps=[],
    )
    db.session.add(session)
    db.session.flush()  # get session.id

    pf = PropertyFacts(
        address='456 Elm St, Chicago, IL 60601',
        property_type=PropertyType.SINGLE_FAMILY,
        units=1,
        bedrooms=3,
        bathrooms=2.0,
        square_footage=1500,
        lot_size=5000,
        year_built=1990,
        construction_type=ConstructionType.FRAME,
        basement=False,
        parking_spaces=1,
        assessed_value=300000.0,
        annual_taxes=6000.0,
        zoning='R-1',
        interior_condition=InteriorCondition.AVERAGE,
        latitude=41.8781,
        longitude=-87.6298,
        data_source='test',
        user_modified_fields=[],
        session_id=session.id,
    )
    db.session.add(pf)
    db.session.commit()

    return session_id


def _cleanup_session(app, session_id):
    """Remove a session and its related records from the test DB."""
    from app import db
    from app.models import AnalysisSession, ComparableSale

    session = AnalysisSession.query.filter_by(session_id=session_id).first()
    if session is None:
        return
    ComparableSale.query.filter_by(session_id=session.id).delete()
    if session.subject_property is not None:
        db.session.delete(session.subject_property)
    db.session.delete(session)
    db.session.commit()


@contextmanager
def _task_context(app, mock_result):
    """Context manager that patches create_app and GeminiComparableSearchService.

    ``create_app`` is imported inside the task as ``from app import create_app``,
    so the correct patch target is ``app.create_app``.
    ``GeminiComparableSearchService`` is imported inside the task as
    ``from app.services.gemini_comparable_search_service import GeminiComparableSearchService``,
    so the correct patch target is the class's own module.

    Yields the mock search method so callers can inspect calls if needed.
    """
    with patch(
        'app.create_app',
        return_value=app,
    ), patch(
        'app.services.gemini_comparable_search_service.GeminiComparableSearchService.search',
        return_value=mock_result,
    ) as mock_search:
        yield mock_search


@contextmanager
def _task_context_with_error(app, exc):
    """Context manager that patches create_app and makes GeminiComparableSearchService raise."""
    with patch(
        'app.create_app',
        return_value=app,
    ), patch(
        'app.services.gemini_comparable_search_service.GeminiComparableSearchService.search',
        side_effect=exc,
    ):
        yield


# ---------------------------------------------------------------------------
# Property 5: Comparable count matches Gemini response list length
# ---------------------------------------------------------------------------

# Feature: gemini-comparable-search, Property 5: Comparable count matches Gemini response list length
@given(n=st.integers(min_value=0, max_value=20))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property5_comparable_count_matches_response_length(n, app):
    """Property 5: Comparable count matches Gemini response list length.

    Validates: Requirements 2.2

    For any N comparables returned by a mocked Gemini API, after
    run_comparable_search_task completes, exactly N ComparableSale records
    SHALL exist in the DB for that session.
    """
    from app import db
    from app.models import ComparableSale, AnalysisSession
    from celery_worker import run_comparable_search_task

    with app.app_context():
        session_id = _create_session_with_property(app)
        mock_result = _make_gemini_result(n)

        with _task_context(app, mock_result):
            run_comparable_search_task(session_id)

        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        count = ComparableSale.query.filter_by(session_id=session.id).count()
        assert count == n, (
            f"Expected {n} ComparableSale records, got {count}"
        )

        # Cleanup so the next hypothesis example starts fresh
        _cleanup_session(app, session_id)


# ---------------------------------------------------------------------------
# Property 6: Narrative round-trip preservation
# ---------------------------------------------------------------------------

# Feature: gemini-comparable-search, Property 6: Narrative round-trip preservation
@given(narrative=st.text())
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property6_narrative_round_trip_preservation(narrative, app):
    """Property 6: Narrative round-trip preservation.

    Validates: Requirements 2.3

    For any narrative string returned by a mocked Gemini API, after
    run_comparable_search_task completes, session.step_results['COMPARABLE_SEARCH']['narrative']
    SHALL equal that exact string.
    """
    from app.models import AnalysisSession
    from celery_worker import run_comparable_search_task

    with app.app_context():
        session_id = _create_session_with_property(app)
        mock_result = _make_gemini_result(1, narrative=narrative)

        with _task_context(app, mock_result):
            run_comparable_search_task(session_id)

        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        stored_narrative = session.step_results['COMPARABLE_SEARCH']['narrative']
        assert stored_narrative == narrative, (
            f"Narrative mismatch: expected {narrative!r}, got {stored_narrative!r}"
        )

        # Cleanup
        _cleanup_session(app, session_id)


# ---------------------------------------------------------------------------
# Unit tests for run_comparable_search_task
# ---------------------------------------------------------------------------

class TestRunComparableSearchTask:
    """Example unit tests for the updated run_comparable_search_task."""

    def test_task_creates_exactly_n_comparable_sale_records(self, app):
        """Task creates exactly N ComparableSale records when Gemini returns N comparables."""
        from app.models import ComparableSale, AnalysisSession
        from celery_worker import run_comparable_search_task

        with app.app_context():
            session_id = _create_session_with_property(app)
            n = 5
            mock_result = _make_gemini_result(n)

            with _task_context(app, mock_result):
                run_comparable_search_task(session_id)

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            count = ComparableSale.query.filter_by(session_id=session.id).count()
            assert count == n

    def test_task_stores_narrative_in_step_results(self, app):
        """Task stores narrative in step_results['COMPARABLE_SEARCH']['narrative']."""
        from app.models import AnalysisSession
        from celery_worker import run_comparable_search_task

        with app.app_context():
            session_id = _create_session_with_property(app)
            expected_narrative = 'This is a detailed AI narrative about the comparables.'
            mock_result = _make_gemini_result(3, narrative=expected_narrative)

            with _task_context(app, mock_result):
                run_comparable_search_task(session_id)

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert 'COMPARABLE_SEARCH' in session.step_results
            assert session.step_results['COMPARABLE_SEARCH']['narrative'] == expected_narrative

    def test_task_sets_loading_false_on_success(self, app):
        """Task sets session.loading = False on successful completion."""
        from app.models import AnalysisSession
        from celery_worker import run_comparable_search_task

        with app.app_context():
            session_id = _create_session_with_property(app)
            mock_result = _make_gemini_result(2)

            with _task_context(app, mock_result):
                run_comparable_search_task(session_id)

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.loading is False

    def test_task_sets_loading_false_and_stores_error_on_gemini_api_error(self, app):
        """Task sets session.loading = False and stores error in step_results['COMPARABLE_SEARCH_ERROR'] on GeminiAPIError."""
        from app.models import AnalysisSession
        from app.exceptions import GeminiAPIError
        from celery_worker import run_comparable_search_task

        with app.app_context():
            session_id = _create_session_with_property(app)
            exc = GeminiAPIError('Gemini API returned 503 Service Unavailable')

            with _task_context_with_error(app, exc):
                result = run_comparable_search_task(session_id)

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.loading is False
            assert 'COMPARABLE_SEARCH_ERROR' in session.step_results
            assert 'Gemini API returned 503' in session.step_results['COMPARABLE_SEARCH_ERROR']
            assert 'error' in result

    def test_task_stores_comparable_count_in_step_results(self, app):
        """Task stores comparable_count in step_results['COMPARABLE_SEARCH']."""
        from app.models import AnalysisSession
        from celery_worker import run_comparable_search_task

        with app.app_context():
            session_id = _create_session_with_property(app)
            n = 7
            mock_result = _make_gemini_result(n)

            with _task_context(app, mock_result):
                run_comparable_search_task(session_id)

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.step_results['COMPARABLE_SEARCH']['comparable_count'] == n

    def test_task_sets_status_complete_in_step_results(self, app):
        """Task sets status='complete' in step_results['COMPARABLE_SEARCH'] on success."""
        from app.models import AnalysisSession
        from celery_worker import run_comparable_search_task

        with app.app_context():
            session_id = _create_session_with_property(app)
            mock_result = _make_gemini_result(3)

            with _task_context(app, mock_result):
                run_comparable_search_task(session_id)

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session.step_results['COMPARABLE_SEARCH']['status'] == 'complete'

    def test_task_returns_error_dict_for_missing_session(self, app):
        """Task returns {'error': 'session not found'} when session_id does not exist."""
        from celery_worker import run_comparable_search_task

        with app.app_context():
            with patch('app.create_app', return_value=app):
                result = run_comparable_search_task('nonexistent-session-id-xyz')
            assert result == {'error': 'session not found'}

    def test_task_creates_zero_records_when_gemini_returns_empty_list(self, app):
        """Task creates 0 ComparableSale records when Gemini returns an empty comparables list."""
        from app.models import ComparableSale, AnalysisSession
        from celery_worker import run_comparable_search_task

        with app.app_context():
            session_id = _create_session_with_property(app)
            mock_result = _make_gemini_result(0)

            with _task_context(app, mock_result):
                run_comparable_search_task(session_id)

            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            count = ComparableSale.query.filter_by(session_id=session.id).count()
            assert count == 0
