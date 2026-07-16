"""Aggregate completed outreach activity and goals for the CRM home dashboard."""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.user_activity_goal import METRICS, PERIOD_TYPES, UserActivityGoal

# Timeline event_type → dashboard metric key
EVENT_TO_METRIC = {
    'call_logged': 'calls',
    'mail_sent': 'mailers',
    'email_logged': 'emails',
    'note_added': 'notes',
    'task_completed': 'tasks',
}

PERIOD_ALIASES = {
    'week': 'weekly',
    'weekly': 'weekly',
    'month': 'monthly',
    'monthly': 'monthly',
}

# CRM operates on Chicago local calendar days for week/month boundaries.
BUSINESS_TZ = ZoneInfo('America/Chicago')


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_utc_naive(dt: datetime) -> datetime:
    """Convert aware datetime to UTC-naive for DB comparisons."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """Return (start_inclusive, end_exclusive, normalized_period_type) as UTC-naive.

    Weeks are ISO (Monday–Sunday) in America/Chicago. Months are calendar months
    in America/Chicago. Bounds are converted to UTC-naive for DB filters.
    """
    normalized = PERIOD_ALIASES.get((period or '').strip().lower())
    if normalized is None:
        raise ValueError("period must be 'week'/'weekly' or 'month'/'monthly'")

    if now is None:
        local_now = datetime.now(BUSINESS_TZ)
    elif now.tzinfo is None:
        # Treat naive test clocks as Chicago local wall time.
        local_now = now.replace(tzinfo=BUSINESS_TZ)
    else:
        local_now = now.astimezone(BUSINESS_TZ)

    if normalized == 'weekly':
        local_start = local_now.replace(
            hour=0, minute=0, second=0, microsecond=0,
        ) - timedelta(days=local_now.weekday())
        local_end = local_start + timedelta(days=7)
    else:
        local_start = local_now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        days_in_month = monthrange(local_now.year, local_now.month)[1]
        local_end = local_start + timedelta(days=days_in_month)

    return _to_utc_naive(local_start), _to_utc_naive(local_end), normalized


def previous_period_bounds(
    start: datetime,
    end: datetime,
    period_type: str,
) -> tuple[datetime, datetime]:
    """Return the immediately prior week or calendar month (UTC-naive)."""
    if period_type == 'weekly':
        return start - timedelta(days=7), end - timedelta(days=7)

    # Previous calendar month in business TZ, derived from current UTC bounds.
    start_local = start.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TZ)
    prev_month_last = start_local - timedelta(days=1)
    prev_start_local = prev_month_last.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    return _to_utc_naive(prev_start_local), start


def _empty_counts() -> dict[str, int]:
    return {metric: 0 for metric in METRICS}


def _trend_for(current: int, previous: int) -> dict[str, Any]:
    delta = current - previous
    if previous == 0:
        pct_change = None
    else:
        pct_change = round((delta / previous) * 100, 1)
    return {
        'delta': delta,
        'pct_change': pct_change,
        'previous': previous,
    }


def _day_key(dt: datetime) -> str:
    return dt.date().isoformat()


def _parse_strict_int(raw: Any, metric: str) -> int:
    """Accept only JSON integers (not bool/float/str)."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f'target for {metric} must be an integer')
    if raw < 0:
        raise ValueError(f'target for {metric} must be >= 0')
    return raw


class ActivityDashboardService:
    """Counts timeline activity for a user and manages their goals."""

    def get_activity(
        self,
        user_id: str,
        period: str = 'week',
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not user_id or user_id == 'anonymous':
            raise ValueError('Authentication required')

        start, end, period_type = period_bounds(period, now=now)
        prev_start, prev_end = previous_period_bounds(start, end, period_type)

        # Compare same elapsed window (WTD/MTD vs same span in prior period).
        if now is None:
            clock = _utcnow_naive()
        elif now.tzinfo is None:
            clock = _to_utc_naive(now.replace(tzinfo=BUSINESS_TZ))
        else:
            clock = _to_utc_naive(now)
        comparable_end = min(clock, end)
        elapsed = comparable_end - start
        if elapsed.total_seconds() < 0:
            elapsed = timedelta(0)
        prev_comparable_end = min(prev_start + elapsed, prev_end)

        current_events = self._fetch_events(user_id, start, end)
        previous_events = self._fetch_events(user_id, prev_start, prev_end)

        counts = self._counts_from_events(current_events, start, comparable_end)
        previous_counts = self._counts_from_events(
            previous_events, prev_start, prev_comparable_end,
        )
        goals = self.get_goals(user_id, period_type)
        progress = {}
        trends = {}
        for metric in METRICS:
            count = counts[metric]
            goal = goals.get(metric)
            if goal is None or goal <= 0:
                progress[metric] = None
            else:
                # Uncapped so overachievement is visible to the UI.
                progress[metric] = round((count / goal) * 100, 1)
            trends[metric] = _trend_for(count, previous_counts[metric])

        comparison = [
            {
                'metric': metric,
                'current': counts[metric],
                'previous': previous_counts[metric],
            }
            for metric in METRICS
        ]
        daily = self._daily_series_from_events(current_events, start, end)
        previous_daily = self._daily_series_from_events(
            previous_events, prev_start, prev_end,
        )

        trend_label = 'WoW' if period_type == 'weekly' else 'MoM'

        return {
            'period': 'week' if period_type == 'weekly' else 'month',
            'period_type': period_type,
            'trend_label': trend_label,
            'range': {
                'start': start.isoformat() + 'Z',
                'end': end.isoformat() + 'Z',
            },
            'previous_range': {
                'start': prev_start.isoformat() + 'Z',
                'end': prev_end.isoformat() + 'Z',
            },
            'comparable_range': {
                'start': start.isoformat() + 'Z',
                'end': comparable_end.isoformat() + 'Z',
            },
            'counts': counts,
            'previous_counts': previous_counts,
            'goals': goals,
            'progress': progress,
            'trends': trends,
            'series': {
                'comparison': comparison,
                'daily': daily,
                'previous_daily': previous_daily,
            },
        }

    def _fetch_events(
        self,
        user_id: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, str]]:
        rows = (
            db.session.query(
                LeadTimelineEntry.occurred_at,
                LeadTimelineEntry.event_type,
            )
            .filter(
                LeadTimelineEntry.actor == user_id,
                LeadTimelineEntry.is_deleted.is_(False),
                LeadTimelineEntry.occurred_at >= start,
                LeadTimelineEntry.occurred_at < end,
                LeadTimelineEntry.event_type.in_(tuple(EVENT_TO_METRIC.keys())),
            )
            .all()
        )
        return [(occurred_at, event_type) for occurred_at, event_type in rows]

    def _counts_from_events(
        self,
        events: list[tuple[datetime, str]],
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        counts = _empty_counts()
        for occurred_at, event_type in events:
            if occurred_at < start or occurred_at >= end:
                continue
            metric = EVENT_TO_METRIC.get(event_type)
            if metric:
                counts[metric] += 1
        return counts

    def _daily_series_from_events(
        self,
        events: list[tuple[datetime, str]],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return one bucket per calendar day in [start, end) (UTC date keys)."""
        buckets: dict[str, dict[str, int]] = {}
        day = start
        while day < end:
            key = _day_key(day)
            buckets[key] = _empty_counts()
            day += timedelta(days=1)

        for occurred_at, event_type in events:
            metric = EVENT_TO_METRIC.get(event_type)
            if not metric:
                continue
            key = _day_key(occurred_at)
            if key in buckets:
                buckets[key][metric] += 1

        series = []
        for key in sorted(buckets.keys()):
            row = dict(buckets[key])
            row['date'] = key
            row['total'] = sum(buckets[key].values())
            series.append(row)
        return series

    def get_goals(self, user_id: str, period_type: str) -> dict[str, int | None]:
        if period_type not in PERIOD_TYPES:
            raise ValueError(f'period_type must be one of {PERIOD_TYPES}')

        rows = UserActivityGoal.query.filter_by(
            user_id=user_id,
            period_type=period_type,
        ).all()
        goals: dict[str, int | None] = {metric: None for metric in METRICS}
        for row in rows:
            if row.metric in goals:
                goals[row.metric] = int(row.target)
        return goals

    def upsert_goals(
        self,
        user_id: str,
        period_type: str,
        targets: dict[str, Any],
    ) -> dict[str, int | None]:
        if not user_id or user_id == 'anonymous':
            raise ValueError('Authentication required')

        normalized = PERIOD_ALIASES.get((period_type or '').strip().lower())
        if normalized is None:
            raise ValueError("period_type must be 'weekly' or 'monthly'")

        if not isinstance(targets, dict) or not targets:
            raise ValueError('targets must be a non-empty object')

        unknown = set(targets) - set(METRICS)
        if unknown:
            raise ValueError(f'Unknown metrics: {sorted(unknown)}')

        parsed = {
            metric: _parse_strict_int(raw, metric)
            for metric, raw in targets.items()
        }

        for metric, value in parsed.items():
            self._upsert_one_goal(user_id, normalized, metric, value)

        db.session.commit()
        return self.get_goals(user_id, normalized)

    def _upsert_one_goal(
        self,
        user_id: str,
        period_type: str,
        metric: str,
        value: int,
    ) -> None:
        row = UserActivityGoal.query.filter_by(
            user_id=user_id,
            period_type=period_type,
            metric=metric,
        ).first()
        if row is not None:
            row.target = value
            row.updated_at = _utcnow_naive()
            return

        row = UserActivityGoal(
            user_id=user_id,
            period_type=period_type,
            metric=metric,
            target=value,
        )
        try:
            with db.session.begin_nested():
                db.session.add(row)
                db.session.flush()
        except IntegrityError:
            existing = UserActivityGoal.query.filter_by(
                user_id=user_id,
                period_type=period_type,
                metric=metric,
            ).first()
            if existing is None:
                raise
            existing.target = value
            existing.updated_at = _utcnow_naive()
