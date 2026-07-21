"""Tests for analysis completion wiring and defensive resolve."""
from types import SimpleNamespace
from unittest.mock import patch

from app.services.analysis_completion_service import (
    ANALYSIS_COMPLETE_STEP,
    mark_lead_analysis_complete,
    mark_lead_analysis_complete_for_session,
    resolve_analysis_complete,
)
from app.services.action_engine_service import ActionEngineService
from app.services.lead_scoring_engine import LeadScoringEngine


_AE_PATCH = 'app.services.action_engine_service.ActionEngineService.recompute_and_persist'


def _make_lead(app, **kwargs):
    from app import db
    from app.models import Lead

    defaults = dict(
        property_street='100 Test St',
        lead_status='mailing_no_contact_made',
        has_phone=True,
        has_email=True,
        has_property_match=True,
        analysis_complete=False,
        follow_up_overdue=False,
        is_warm=False,
        lead_score=75.0,
        data_completeness_score=80.0,
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _make_session(app, *, completed_steps=None):
    from app import db
    from app.models import AnalysisSession, WorkflowStep

    session = AnalysisSession(
        session_id='test-session-1',
        user_id='test-user',
        current_step=WorkflowStep.WEIGHTED_SCORING,
        completed_steps=completed_steps or [ANALYSIS_COMPLETE_STEP],
    )
    db.session.add(session)
    db.session.commit()
    return session


# ---------------------------------------------------------------------------
# resolve_analysis_complete
# ---------------------------------------------------------------------------

def test_resolve_analysis_complete_true_when_flag_set(app):
    with app.app_context():
        lead = _make_lead(app, analysis_complete=True)
        assert resolve_analysis_complete(lead) is True


def test_resolve_analysis_complete_false_without_flag_or_session(app):
    with app.app_context():
        lead = _make_lead(app, analysis_complete=False)
        assert resolve_analysis_complete(lead) is False


def test_resolve_analysis_complete_true_from_session_completed_steps(app):
    with app.app_context():
        from app import db

        session = _make_session(app)
        lead = _make_lead(app, analysis_complete=False, analysis_session_id=session.id)
        db.session.refresh(lead)
        assert resolve_analysis_complete(lead) is True


def test_compute_recommended_action_never_returns_analyze_property(app):
    with app.app_context():
        from app import db

        session = _make_session(app)
        lead = _make_lead(app, analysis_complete=False, analysis_session_id=session.id)
        db.session.refresh(lead)

        with patch('app.services.lead_scoring_engine._count_open_tasks', return_value=0), \
             patch.object(LeadScoringEngine, '_has_recent_email', return_value=False):
            result = ActionEngineService.compute_recommended_action(lead)

        assert result != 'analyze_property'


# ---------------------------------------------------------------------------
# mark_lead_analysis_complete
# ---------------------------------------------------------------------------

def test_mark_lead_analysis_complete_sets_flag_and_timeline(app):
    with app.app_context():
        from app import db
        from app.models import LeadTimelineEntry

        lead = _make_lead(app, analysis_complete=False, recommended_action='analyze_property')

        with patch('app.services.lead_scoring_engine.LeadScoringEngine.score_and_persist'):
            mark_lead_analysis_complete(
                lead.id, source='test', actor='Tester', recompute_action=False,
            )

        db.session.refresh(lead)
        assert lead.analysis_complete is True

        entry = (
            LeadTimelineEntry.query
            .filter_by(lead_id=lead.id, event_type='property_analysis_completed')
            .first()
        )
        assert entry is not None
        assert entry.source == 'test'


def test_mark_lead_analysis_complete_for_session_links_lead(app):
    with app.app_context():
        from app import db

        session = _make_session(app, completed_steps=['COMPARABLE_REVIEW'])
        lead = _make_lead(app, analysis_complete=False, analysis_session_id=session.id)

        with patch(
            'app.services.lead_scoring_engine.LeadScoringEngine.score_and_persist',
            side_effect=lambda lead_id, commit=True: db.session.commit(),
        ):
            result = mark_lead_analysis_complete_for_session(session.id)

        assert result is not None
        assert result.id == lead.id
        db.session.refresh(lead)
        assert lead.analysis_complete is True


def test_mark_lead_analysis_complete_rescores_lead(app):
    with app.app_context():
        lead = _make_lead(app, analysis_complete=False)

        with patch(
            'app.services.lead_scoring_engine.LeadScoringEngine.score_and_persist',
        ) as mock_score:
            mark_lead_analysis_complete(lead.id)

        mock_score.assert_called_once_with(lead.id, commit=True)


# ---------------------------------------------------------------------------
# LeadTaskService — run_property_analysis completion
# ---------------------------------------------------------------------------

def test_complete_run_property_analysis_sets_analysis_complete(app):
    with app.app_context():
        from app import db
        from app.services.lead_task_service import LeadTaskService

        lead = _make_lead(
            app,
            analysis_complete=False,
            recommended_action='analyze_property',
            lead_score=75.0,
            data_completeness_score=80.0,
        )
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(
                lead.id,
                {'title': 'Run analysis', 'task_type': 'run_property_analysis'},
                recompute_action=False,
            )

        completed = svc.complete(task.id, lead.id, recompute_action=True)
        assert completed.status == 'completed'

        db.session.refresh(lead)
        assert lead.analysis_complete is True
        assert lead.recommended_action != 'analyze_property'


def test_skip_trace_chore_clear_marks_hubspot_analysis_task_complete(app):
    with app.app_context():
        from datetime import date, timedelta

        from app import db
        from app.models import LeadTask
        from app.services.skip_trace_enqueue import clear_dated_due_chores_entering_skip_trace

        lead = _make_lead(app, analysis_complete=False, recommended_action='analyze_property')
        task = LeadTask(
            lead_id=lead.id,
            task_type='run_property_analysis',
            title='Run property analysis',
            status='open',
            due_date=date.today() - timedelta(days=1),
            created_by='test',
            hubspot_task_id='hs-analysis-1',
        )
        db.session.add(task)
        db.session.commit()

        with patch(
            'app.services.hubspot_task_completion_service.mark_hubspot_task_completed_local',
            return_value=SimpleNamespace(hubspot_task_id='hs-analysis-1'),
        ), patch(
            'app.services.analysis_completion_service.mark_lead_analysis_complete',
        ) as mark_complete:
            completed_ids, pending_hubspot_ids = clear_dated_due_chores_entering_skip_trace(
                lead.id,
                actor='test',
            )

        assert completed_ids == [task.id]
        assert pending_hubspot_ids == {'hs-analysis-1'}
        mark_complete.assert_called_once_with(
            lead.id,
            source='manual',
            actor='test',
            recompute_action=False,
            commit=False,
        )


# ---------------------------------------------------------------------------
# Backfill script eligibility
# ---------------------------------------------------------------------------

def test_backfill_eligible_lead_ids(app):
    with app.app_context():
        from app.services.analysis_completion_service import (
            query_lead_ids_for_analysis_complete_backfill,
        )

        session = _make_session(app)
        stuck = _make_lead(app, analysis_complete=False, analysis_session_id=session.id)
        no_session = _make_lead(app, analysis_complete=False)

        eligible = query_lead_ids_for_analysis_complete_backfill()
        assert stuck.id in eligible
        assert no_session.id not in eligible
