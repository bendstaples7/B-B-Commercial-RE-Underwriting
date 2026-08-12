"""Tests for scripts/lead_cc_mount_health.py threshold logic."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_HC_PATH = _ROOT / "scripts" / "lead_cc_mount_health.py"


def _load():
    name = "lead_cc_mount_health"
    spec = importlib.util.spec_from_file_location(name, _HC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


hc = _load()

NOW = datetime(2026, 8, 11, 20, 0, 0, tzinfo=timezone.utc)


def _line(ts: str, path: str) -> str:
    return (
        f'1.2.3.4 - - [{ts}] "GET {path} HTTP/1.1" 200 1234 '
        f'"-" "Mozilla/5.0"\n'
    )


def test_count_ulcc_and_command_center_in_window():
    lines = [
        _line(
            "11/Aug/2026:19:00:00 +0000",
            "/assets/UnifiedLeadCommandCenter-abc123.js",
        ),
        _line(
            "11/Aug/2026:19:01:00 +0000",
            "/api/leads/643/command-center",
        ),
        # Outside window
        _line(
            "09/Aug/2026:19:00:00 +0000",
            "/assets/UnifiedLeadCommandCenter-old.js",
        ),
        # Unrelated
        _line("11/Aug/2026:19:02:00 +0000", "/api/queues/counts"),
    ]
    counts = hc.count_mount_health(lines, now=NOW, window_hours=24)
    assert counts.ulcc_loads == 1
    assert counts.command_center_hits == 1


def test_decide_insufficient_traffic_is_healthy():
    counts = hc.MountHealthCounts(
        ulcc_loads=4,
        command_center_hits=0,
        window_start=NOW,
        window_end=NOW,
    )
    decision = hc.decide_mount_health(counts)
    assert decision.unhealthy is False
    assert "insufficient" in decision.reason


def test_decide_zero_cc_with_enough_ulcc_is_unhealthy():
    counts = hc.MountHealthCounts(
        ulcc_loads=5,
        command_center_hits=0,
        window_start=NOW,
        window_end=NOW,
    )
    decision = hc.decide_mount_health(counts)
    assert decision.unhealthy is True
    assert "hits=0" in decision.reason


def test_decide_low_ratio_with_enough_ulcc_is_unhealthy():
    counts = hc.MountHealthCounts(
        ulcc_loads=20,
        command_center_hits=1,  # ratio 0.05 < 0.1
        window_start=NOW,
        window_end=NOW,
    )
    decision = hc.decide_mount_health(counts)
    assert decision.unhealthy is True
    assert "ratio" in decision.reason


def test_decide_healthy_ratio():
    counts = hc.MountHealthCounts(
        ulcc_loads=20,
        command_center_hits=5,  # ratio 0.25
        window_start=NOW,
        window_end=NOW,
    )
    decision = hc.decide_mount_health(counts)
    assert decision.unhealthy is False
    assert "healthy" in decision.reason


def test_end_to_end_fixture_log_triggers_alert():
    """Prod-shaped: many ULCC loads, zero command-center."""
    lines = [
        _line(
            f"11/Aug/2026:1{i}:00:00 +0000",
            f"/assets/UnifiedLeadCommandCenter-deadbeef{i}.js",
        )
        for i in range(5, 10)
    ]
    counts = hc.count_mount_health(lines, now=NOW, window_hours=24)
    assert counts.ulcc_loads == 5
    assert counts.command_center_hits == 0
    assert hc.decide_mount_health(counts).unhealthy is True


def test_js_map_and_css_are_not_ulcc_loads():
    lines = [
        _line(
            "11/Aug/2026:19:00:00 +0000",
            "/assets/UnifiedLeadCommandCenter-abc123.js.map",
        ),
        _line(
            "11/Aug/2026:19:00:01 +0000",
            "/assets/UnifiedLeadCommandCenter-abc123.js?v=1",
        ),
        _line(
            "11/Aug/2026:19:00:02 +0000",
            "/assets/UnifiedLeadCommandCenter-abc123.js",
        ),
    ]
    counts = hc.count_mount_health(lines, now=NOW, window_hours=24)
    assert counts.ulcc_loads == 2  # bare .js + .js?v= — not .map


def test_classify_path_rejects_map():
    assert hc.classify_path("/assets/UnifiedLeadCommandCenter-x.js.map") is None
    assert hc.classify_path("/assets/UnifiedLeadCommandCenter-x.js") == "ulcc"


def test_decide_boundaries_4_vs_5_and_9_vs_10():
    c4 = hc.MountHealthCounts(4, 0, NOW, NOW)
    c5 = hc.MountHealthCounts(5, 0, NOW, NOW)
    assert hc.decide_mount_health(c4).unhealthy is False
    assert hc.decide_mount_health(c5).unhealthy is True

    # ulcc=9 with 1 cc → ratio ~0.11, above 0.1, and below min_ulcc_ratio for ratio rule
    c9 = hc.MountHealthCounts(9, 1, NOW, NOW)
    assert hc.decide_mount_health(c9).unhealthy is False

    # ulcc=10 with 0 cc already caught by zero rule; with 1 cc ratio=0.1 is NOT < 0.1
    c10_eq = hc.MountHealthCounts(10, 1, NOW, NOW)
    assert hc.decide_mount_health(c10_eq).unhealthy is False
    c10_low = hc.MountHealthCounts(10, 0, NOW, NOW)
    assert hc.decide_mount_health(c10_low).unhealthy is True
    c11_low = hc.MountHealthCounts(11, 1, NOW, NOW)  # 1/11 < 0.1
    assert hc.decide_mount_health(c11_low).unhealthy is True
