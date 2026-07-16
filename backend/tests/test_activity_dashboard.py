"""Tests for activity dashboard service and API."""
from datetime import datetime, timedelta

import pytest

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.activity_dashboard_service import (
    ActivityDashboardService,
    period_bounds,
    previous_period_bounds,
)


_AUTH = {'X-User-Id': 'dash-user-1'}
_OTHER = {'X-User-Id': 'dash-user-2'}


def _make_lead(**kwargs):
    defaults = dict(
        property_street='100 Dashboard St',
        property_city='Chicago',
        property_state='IL',
        property_zip='60601',
        lead_status='mailing_no_contact_made',
        has_phone=True,
        has_email=True,
        has_property_match=True,
        analysis_complete=True,
        follow_up_overdue=False,
        is_warm=False,
        lead_score=50.0,
        data_completeness_score=60.0,
        recommended_action=None,
        review_required=False,
        unanswered_call_count=0,
        owner_user_id='dash-user-1',
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.flush()
    return lead


def _add_entry(lead_id, event_type, actor, occurred_at, is_deleted=False):
    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type=event_type,
        occurred_at=occurred_at,
        source='manual',
        actor=actor,
        summary=f'{event_type} by {actor}',
        is_deleted=is_deleted,
    )
    db.session.add(entry)
    return entry


class TestPeriodBounds:
    def test_week_starts_monday_chicago_as_utc(self):
        # Wednesday 2026-07-15 Chicago → week Mon Jul 13 00:00 CDT = 05:00 UTC
        now = datetime(2026, 7, 15, 14, 30, 0)
        start, end, period_type = period_bounds('week', now=now)
        assert period_type == 'weekly'
        assert start == datetime(2026, 7, 13, 5, 0, 0)
        assert end == datetime(2026, 7, 20, 5, 0, 0)

    def test_month_calendar_chicago_as_utc(self):
        now = datetime(2026, 7, 15, 14, 30, 0)
        start, end, period_type = period_bounds('month', now=now)
        assert period_type == 'monthly'
        assert start == datetime(2026, 7, 1, 5, 0, 0)
        assert end == datetime(2026, 8, 1, 5, 0, 0)

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            period_bounds('year')

    def test_previous_month_bounds(self):
        start, end, period_type = period_bounds('month', now=datetime(2026, 7, 15, 12, 0, 0))
        prev_start, prev_end = previous_period_bounds(start, end, period_type)
        assert prev_start == datetime(2026, 6, 1, 5, 0, 0)
        assert prev_end == start


class TestActivityDashboardService:
    def test_counts_by_actor_and_period(self, app):
        with app.app_context():
            lead = _make_lead()
            now = datetime(2026, 7, 15, 12, 0, 0)
            # Store occurred_at in UTC-naive matching Chicago-week UTC window
            in_week = datetime(2026, 7, 14, 15, 0, 0)  # after Jul 13 05:00 UTC
            before_week = datetime(2026, 7, 12, 12, 0, 0)

            _add_entry(lead.id, 'call_logged', 'dash-user-1', in_week)
            _add_entry(lead.id, 'call_logged', 'dash-user-1', in_week + timedelta(hours=1))
            _add_entry(lead.id, 'mail_sent', 'dash-user-1', in_week + timedelta(hours=2))
            _add_entry(lead.id, 'email_logged', 'dash-user-1', in_week + timedelta(hours=3))
            _add_entry(lead.id, 'note_added', 'dash-user-1', in_week + timedelta(hours=4))
            _add_entry(lead.id, 'task_completed', 'dash-user-1', in_week + timedelta(hours=5))
            _add_entry(lead.id, 'call_logged', 'dash-user-2', in_week)
            _add_entry(
                lead.id, 'call_logged', 'dash-user-1',
                in_week + timedelta(hours=6), is_deleted=True,
            )
            _add_entry(lead.id, 'call_logged', 'dash-user-1', before_week)
            db.session.commit()

            svc = ActivityDashboardService()
            result = svc.get_activity('dash-user-1', period='week', now=now)

            assert result['counts'] == {
                'calls': 2,
                'mailers': 1,
                'emails': 1,
                'notes': 1,
                'tasks': 1,
            }
            assert result['period'] == 'week'
            assert result['goals']['calls'] is None
            assert result['progress']['calls'] is None

    def test_progress_with_goals_uncapped(self, app):
        with app.app_context():
            lead = _make_lead(property_street='101 Dashboard St')
            now = datetime(2026, 7, 15, 12, 0, 0)
            in_week = datetime(2026, 7, 14, 15, 0, 0)
            for i in range(5):
                _add_entry(
                    lead.id, 'call_logged', 'dash-user-1',
                    in_week + timedelta(hours=i),
                )
            db.session.commit()

            svc = ActivityDashboardService()
            svc.upsert_goals('dash-user-1', 'weekly', {'calls': 4})
            result = svc.get_activity('dash-user-1', period='week', now=now)
            assert result['goals']['calls'] == 4
            assert result['progress']['calls'] == 125.0

    def test_wow_uses_same_elapsed_window(self, app):
        with app.app_context():
            lead = _make_lead(property_street='103 Dashboard St')
            # Wed Jul 15 noon Chicago → comparable through Wed; prior week Mon–Wed only
            now = datetime(2026, 7, 15, 12, 0, 0)
            this_week = datetime(2026, 7, 14, 15, 0, 0)
            last_week_in_window = datetime(2026, 7, 7, 15, 0, 0)
            last_week_after_window = datetime(2026, 7, 10, 15, 0, 0)  # Fri — outside comparable
            _add_entry(lead.id, 'call_logged', 'dash-user-1', this_week)
            _add_entry(lead.id, 'call_logged', 'dash-user-1', this_week + timedelta(hours=1))
            _add_entry(lead.id, 'call_logged', 'dash-user-1', this_week + timedelta(hours=2))
            _add_entry(lead.id, 'call_logged', 'dash-user-1', last_week_in_window)
            _add_entry(lead.id, 'call_logged', 'dash-user-1', last_week_after_window)
            db.session.commit()

            svc = ActivityDashboardService()
            result = svc.get_activity('dash-user-1', period='week', now=now)

            assert result['trend_label'] == 'WoW'
            assert result['counts']['calls'] == 3
            # Prior full week has 2, but comparable window should only include 1
            assert result['previous_counts']['calls'] == 1
            assert result['trends']['calls']['delta'] == 2
            assert result['trends']['calls']['pct_change'] == 200.0
            assert len(result['series']['daily']) == 7
            assert len(result['series']['previous_daily']) == 7

    def test_mom_previous_month(self, app):
        with app.app_context():
            lead = _make_lead(property_street='104 Dashboard St')
            now = datetime(2026, 7, 15, 12, 0, 0)
            _add_entry(lead.id, 'mail_sent', 'dash-user-1', datetime(2026, 7, 2, 12, 0, 0))
            _add_entry(lead.id, 'mail_sent', 'dash-user-1', datetime(2026, 6, 10, 12, 0, 0))
            _add_entry(lead.id, 'mail_sent', 'dash-user-1', datetime(2026, 6, 20, 12, 0, 0))
            db.session.commit()

            svc = ActivityDashboardService()
            result = svc.get_activity('dash-user-1', period='month', now=now)
            assert result['trend_label'] == 'MoM'
            assert result['counts']['mailers'] == 1
            # June 10 is within comparable MTD window (through Jul 15); June 20 is not
            assert result['previous_counts']['mailers'] == 1
            assert result['trends']['mailers']['delta'] == 0
            assert result['previous_range']['start'].startswith('2026-06-01')

    def test_upsert_goals_rejects_unknown_metric(self, app):
        with app.app_context():
            svc = ActivityDashboardService()
            with pytest.raises(ValueError, match='Unknown metrics'):
                svc.upsert_goals('dash-user-1', 'weekly', {'sms': 10})

    def test_upsert_goals_rejects_bool_and_float(self, app):
        with app.app_context():
            svc = ActivityDashboardService()
            with pytest.raises(ValueError, match='must be an integer'):
                svc.upsert_goals('dash-user-1', 'weekly', {'calls': True})
            with pytest.raises(ValueError, match='must be an integer'):
                svc.upsert_goals('dash-user-1', 'weekly', {'calls': 12.9})


class TestDashboardApi:
    def test_get_activity_requires_auth(self, client):
        resp = client.get('/api/dashboard/activity')
        assert resp.status_code == 401

    def test_put_goals_requires_auth(self, client):
        resp = client.put(
            '/api/dashboard/goals',
            json={'period_type': 'weekly', 'targets': {'calls': 1}},
        )
        assert resp.status_code == 401

    def test_get_invalid_period(self, client):
        resp = client.get('/api/dashboard/activity?period=year', headers=_AUTH)
        assert resp.status_code == 400

    def test_get_and_put_goals(self, client, app):
        with app.app_context():
            lead = _make_lead(property_street='102 Dashboard St')
            _add_entry(
                lead.id, 'call_logged', 'dash-user-1',
                datetime.utcnow() - timedelta(hours=1),
            )
            db.session.commit()

        put = client.put(
            '/api/dashboard/goals',
            headers=_AUTH,
            json={'period_type': 'week', 'targets': {'calls': 25, 'mailers': 10}},
        )
        assert put.status_code == 200
        assert put.get_json()['period_type'] == 'weekly'
        assert put.get_json()['goals']['calls'] == 25
        assert put.get_json()['goals']['mailers'] == 10

        get = client.get('/api/dashboard/activity?period=week', headers=_AUTH)
        assert get.status_code == 200
        body = get.get_json()
        assert body['period'] == 'week'
        assert body['counts']['calls'] >= 1
        assert body['goals']['calls'] == 25
        assert body['progress']['calls'] is not None
        assert 'series' in body
        assert 'trends' in body
        assert body['trend_label'] == 'WoW'

        other = client.get('/api/dashboard/activity?period=week', headers=_OTHER)
        assert other.status_code == 200
        assert other.get_json()['goals']['calls'] is None
        assert other.get_json()['counts']['calls'] == 0

    def test_put_goals_validation(self, client):
        resp = client.put(
            '/api/dashboard/goals',
            headers=_AUTH,
            json={'period_type': 'weekly', 'targets': {'calls': -1}},
        )
        assert resp.status_code == 400

        resp = client.put(
            '/api/dashboard/goals',
            headers=_AUTH,
            json={'period_type': 'weekly', 'targets': {'calls': True}},
        )
        assert resp.status_code == 400

        resp = client.put(
            '/api/dashboard/goals',
            headers=_AUTH,
            json={'period_type': 'weekly', 'targets': {}},
        )
        assert resp.status_code == 400
