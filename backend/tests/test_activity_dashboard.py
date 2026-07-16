"""Tests for activity dashboard service and API."""
from datetime import datetime, timedelta

import pytest

from app import db
from app.models import Lead, LeadTimelineEntry
from app.models.user import User
from app.services.activity_dashboard_service import (
    ActivityDashboardService,
    period_bounds,
    previous_period_bounds,
)


_AUTH = {'X-User-Id': 'dash-user-1'}
_OTHER = {'X-User-Id': 'dash-user-2'}


def _ensure_user(user_id: str, email_prefix: str = 'dash') -> User:
    existing = User.query.filter_by(user_id=user_id).first()
    if existing:
        return existing
    email = f'{email_prefix}-{user_id[:8]}@test.com'
    user = User(
        user_id=user_id,
        email=email,
        email_lower=email.lower(),
        password_hash='$2b$12$fakehashfakehashfakehashfakehashfakehashfakehash',
        display_name=email_prefix,
        is_active=True,
        password_set=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


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

    def test_previous_week_uses_chicago_local_midnights(self):
        start, end, period_type = period_bounds('week', now=datetime(2026, 7, 15, 12, 0, 0))
        prev_start, prev_end = previous_period_bounds(start, end, period_type)
        assert prev_start == datetime(2026, 7, 6, 5, 0, 0)
        assert prev_end == start

    def test_previous_month_bounds(self):
        start, end, period_type = period_bounds('month', now=datetime(2026, 7, 15, 12, 0, 0))
        prev_start, prev_end = previous_period_bounds(start, end, period_type)
        assert prev_start == datetime(2026, 6, 1, 5, 0, 0)
        assert prev_end == start


class TestActivityDashboardService:
    def test_counts_by_actor_and_period(self, app):
        with app.app_context():
            _ensure_user('dash-user-1')
            lead = _make_lead()
            now = datetime(2026, 7, 15, 12, 0, 0)
            in_week = datetime(2026, 7, 14, 15, 0, 0)
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
            _ensure_user('dash-user-1')
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
            _ensure_user('dash-user-1')
            lead = _make_lead(property_street='103 Dashboard St')
            now = datetime(2026, 7, 15, 12, 0, 0)
            this_week = datetime(2026, 7, 14, 15, 0, 0)
            last_week_in_window = datetime(2026, 7, 7, 15, 0, 0)
            last_week_after_window = datetime(2026, 7, 10, 15, 0, 0)
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
            assert result['previous_counts']['calls'] == 1
            assert result['trends']['calls']['delta'] == 2
            assert result['trends']['calls']['pct_change'] == 200.0
            assert len(result['series']['daily']) == 7
            assert len(result['series']['previous_daily']) == 7

    def test_daily_buckets_use_chicago_calendar_day(self, app):
        """Late Chicago evening UTC should land on the Chicago calendar date."""
        with app.app_context():
            _ensure_user('dash-user-1')
            lead = _make_lead(property_street='105 Dashboard St')
            now = datetime(2026, 7, 15, 12, 0, 0)
            # 2026-07-14 23:30 CDT = 2026-07-15 04:30 UTC
            late_chicago_evening = datetime(2026, 7, 15, 4, 30, 0)
            _add_entry(lead.id, 'call_logged', 'dash-user-1', late_chicago_evening)
            db.session.commit()

            svc = ActivityDashboardService()
            result = svc.get_activity('dash-user-1', period='week', now=now)
            by_date = {row['date']: row['calls'] for row in result['series']['daily']}
            assert by_date.get('2026-07-14') == 1
            assert by_date.get('2026-07-15', 0) == 0

    def test_mom_previous_month(self, app):
        with app.app_context():
            _ensure_user('dash-user-1')
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
            assert result['previous_counts']['mailers'] == 1
            assert result['trends']['mailers']['delta'] == 0
            assert result['previous_range']['start'].startswith('2026-06-01')

    def test_upsert_goals_rejects_unknown_metric(self, app):
        with app.app_context():
            _ensure_user('dash-user-1')
            svc = ActivityDashboardService()
            with pytest.raises(ValueError, match='Unknown metrics'):
                svc.upsert_goals('dash-user-1', 'weekly', {'sms': 10})

    def test_upsert_goals_rejects_bool_and_float(self, app):
        with app.app_context():
            _ensure_user('dash-user-1')
            svc = ActivityDashboardService()
            with pytest.raises(ValueError, match='must be an integer'):
                svc.upsert_goals('dash-user-1', 'weekly', {'calls': True})
            with pytest.raises(ValueError, match='must be an integer'):
                svc.upsert_goals('dash-user-1', 'weekly', {'calls': 12.9})

    def test_upsert_rejects_mixed_payload_without_partial_write(self, app):
        with app.app_context():
            _ensure_user('dash-user-1')
            svc = ActivityDashboardService()
            svc.upsert_goals('dash-user-1', 'weekly', {'calls': 10})
            with pytest.raises(ValueError, match='must be an integer'):
                svc.upsert_goals('dash-user-1', 'weekly', {'calls': 20, 'mailers': True})
            # Failed mixed payload must not change existing goals
            assert svc.get_goals('dash-user-1', 'weekly')['calls'] == 10
            assert svc.get_goals('dash-user-1', 'weekly')['mailers'] is None

    def test_clear_goal_with_null(self, app):
        with app.app_context():
            _ensure_user('dash-user-1')
            svc = ActivityDashboardService()
            svc.upsert_goals('dash-user-1', 'weekly', {'calls': 10})
            assert svc.get_goals('dash-user-1', 'weekly')['calls'] == 10
            svc.upsert_goals('dash-user-1', 'weekly', {'calls': None})
            assert svc.get_goals('dash-user-1', 'weekly')['calls'] is None


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

    def test_get_invalid_period(self, client, app):
        with app.app_context():
            _ensure_user('dash-user-1')
            db.session.commit()
        resp = client.get('/api/dashboard/activity?period=year', headers=_AUTH)
        assert resp.status_code == 400

    def test_get_and_put_goals(self, client, app):
        from unittest.mock import patch

        fixed_now = datetime(2026, 7, 15, 12, 0, 0)
        with app.app_context():
            _ensure_user('dash-user-1')
            _ensure_user('dash-user-2', email_prefix='other')
            lead = _make_lead(property_street='102 Dashboard St')
            # Naive `now` is Chicago local; noon CDT => 17:00Z comparable_end.
            # Entry must be strictly before that exclusive bound.
            _add_entry(
                lead.id, 'call_logged', 'dash-user-1',
                datetime(2026, 7, 15, 14, 0, 0),
            )
            db.session.commit()

        real_get = ActivityDashboardService.get_activity

        def _frozen_get(self, user_id, period='week', now=None):
            return real_get(self, user_id, period=period, now=fixed_now)

        with patch.object(ActivityDashboardService, 'get_activity', _frozen_get):
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

    def test_put_goals_validation(self, client, app):
        with app.app_context():
            _ensure_user('dash-user-1')
            db.session.commit()

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

        resp = client.put(
            '/api/dashboard/goals',
            headers=_AUTH,
            json=['not', 'an', 'object'],
        )
        assert resp.status_code == 400

        resp = client.put(
            '/api/dashboard/goals',
            headers=_AUTH,
            json={'period_type': 12, 'targets': {'calls': 1}},
        )
        assert resp.status_code == 400
