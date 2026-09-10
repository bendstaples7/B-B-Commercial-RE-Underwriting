"""Unit tests for host memory health helpers and entity-research fan-out caps."""
from __future__ import annotations

from app.services.entity_research_lifecycle_service import (
    ENTITY_RESEARCH_BATCH_SIZE,
    reconcile_pending_entity_research,
)
from app.services.helpers.host_memory import (
    _is_celery_worker_cmdline,
    evaluate_host_memory_health,
    host_memory_snapshot,
    memory_shed_skip_payload,
    read_meminfo,
    should_shed_background_work,
)


def test_entity_research_batch_size_caps_fan_out():
    """Hourly mark_overdue must not enqueue unbounded resolve_lead tasks."""
    assert ENTITY_RESEARCH_BATCH_SIZE <= 25
    assert ENTITY_RESEARCH_BATCH_SIZE > 0


def test_reconcile_respects_zero_limit(app):
    with app.app_context():
        outcome = reconcile_pending_entity_research(
            actor='test', limit=0, commit=False,
        )
        assert outcome['processed_lead_count'] == 0
        assert outcome['queued_count'] == 0
        assert outcome['limit'] == 0
        assert outcome['results'] == []
        assert outcome['processed_lead_ids'] == []
        assert outcome['retired_task_count'] == 0


def test_reconcile_effective_limit_matches_batch_constant():
    """Document the contract mark_overdue relies on."""
    from app.services.entity_research_lifecycle_service import ENTITY_RESEARCH_BATCH_SIZE as n
    assert n == 15


def test_mark_overdue_passes_batch_limit(app, monkeypatch):
    """mark_tasks_overdue must pass ENTITY_RESEARCH_BATCH_SIZE into reconcile."""
    captured: dict = {}

    def fake_reconcile(**kwargs):
        captured.update(kwargs)
        return {
            'processed_lead_count': 0,
            'queued_count': 0,
            'retired_task_count': 0,
        }

    monkeypatch.setattr(
        'app.services.entity_research_lifecycle_service.reconcile_pending_entity_research',
        fake_reconcile,
    )
    monkeypatch.setattr(
        'app.services.mail_task_lifecycle_service.reconcile_recent_sale_mail_tasks',
        lambda **kwargs: {'rescheduled_task_count': 0},
    )
    monkeypatch.setattr('app.create_app', lambda *a, **k: app)

    from celery_worker import mark_tasks_overdue

    with app.app_context():
        mark_tasks_overdue()

    assert captured.get('limit') == ENTITY_RESEARCH_BATCH_SIZE
    assert captured.get('actor') == 'tasks.mark_overdue'


def test_read_meminfo_parses_kib(tmp_path):
    path = tmp_path / 'meminfo'
    path.write_text(
        'MemTotal:       2000000 kB\n'
        'MemAvailable:    512000 kB\n'
        'SwapTotal:      2097152 kB\n'
        'SwapFree:        100000 kB\n',
        encoding='utf-8',
    )
    info = read_meminfo(path)
    assert info['MemAvailable'] == 512000
    snap = host_memory_snapshot(info)
    assert snap['available'] is True
    assert snap['mem_available_mib'] == round(512000 / 1024.0, 1)
    assert snap['swap_used_pct'] > 90


def test_evaluate_host_memory_health_warns_low_available():
    host = host_memory_snapshot({
        'MemTotal': 2_000_000,
        'MemAvailable': 50_000,  # ~48 MiB
        'SwapTotal': 2_000_000,
        'SwapFree': 2_000_000,
    })
    result = evaluate_host_memory_health(
        min_available_mib=150,
        max_swap_used_pct=85,
        max_celery_rss_mib=600,
        host=host,
        celery={'available': False, 'reason': 'skipped'},
    )
    assert result['ok'] is False
    assert result['detail'].startswith('WARN:')
    assert 'MemAvailable' in result['detail']


def test_evaluate_host_memory_health_warns_high_celery_rss():
    host = {
        'available': True,
        'mem_total_mib': 1900.0,
        'mem_available_mib': 800.0,
        'swap_total_mib': 2000.0,
        'swap_used_mib': 100.0,
        'swap_used_pct': 5.0,
    }
    result = evaluate_host_memory_health(
        min_available_mib=150,
        max_swap_used_pct=85,
        max_celery_rss_mib=600,
        host=host,
        celery={'available': True, 'celery_rss_mib': 1400.0, 'matched_processes': 1},
    )
    assert result['ok'] is False
    assert result['detail'].startswith('WARN:')
    assert 'Celery RSS' in result['detail']


def test_celery_worker_cmdline_filter():
    assert _is_celery_worker_cmdline(
        '/usr/bin/python3.11 celery -A celery_worker.celery worker --loglevel=info'
    )
    assert not _is_celery_worker_cmdline(
        '/usr/bin/python3.11 celery -A celery_worker.celery beat --loglevel=info'
    )
    assert not _is_celery_worker_cmdline('grep celery something')


def test_should_shed_background_work_when_mem_low():
    host = {
        'available': True,
        'mem_total_mib': 1900.0,
        'mem_available_mib': 120.0,
        'swap_total_mib': 2000.0,
        'swap_used_mib': 100.0,
        'swap_used_pct': 5.0,
    }
    decision = should_shed_background_work(min_available_mib=250, host=host)
    assert decision['shed'] is True
    assert 'MemAvailable' in (decision['reason'] or '')
    payload = memory_shed_skip_payload(min_available_mib=250, host=host)
    assert payload is not None
    assert payload['skipped'] is True
    assert payload['reason'] == 'host_memory_pressure'


def test_should_not_shed_when_mem_ok():
    host = {
        'available': True,
        'mem_total_mib': 1900.0,
        'mem_available_mib': 800.0,
        'swap_total_mib': 2000.0,
        'swap_used_mib': 100.0,
        'swap_used_pct': 5.0,
    }
    decision = should_shed_background_work(min_available_mib=250, host=host)
    assert decision['shed'] is False
    assert memory_shed_skip_payload(min_available_mib=250, host=host) is None


def test_memory_shed_task_names_include_channel_roi():
    from celery_worker import MEMORY_SHED_TASK_NAMES

    assert 'channel_roi.sync_facebook_campaigns' in MEMORY_SHED_TASK_NAMES


def test_should_shed_rejects_invalid_env_threshold(monkeypatch):
    """Malformed BB_SHED_MIN_AVAILABLE_MIB must fall back to 250, not crash/disable."""
    host = {
        'available': True,
        'mem_total_mib': 1900.0,
        'mem_available_mib': 200.0,
        'swap_total_mib': 0.0,
        'swap_used_mib': 0.0,
        'swap_used_pct': 0.0,
    }
    monkeypatch.setenv('BB_SHED_MIN_AVAILABLE_MIB', 'not-a-number')
    decision = should_shed_background_work(host=host)
    assert decision['shed'] is True  # 200 < default 250
    monkeypatch.setenv('BB_SHED_MIN_AVAILABLE_MIB', 'nan')
    decision = should_shed_background_work(host=host)
    assert decision['shed'] is True
    monkeypatch.setenv('BB_SHED_MIN_AVAILABLE_MIB', '-5')
    decision = should_shed_background_work(host=host)
    assert decision['shed'] is True

