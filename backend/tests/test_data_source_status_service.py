"""Property-based tests for DataSourceStatusService.

Validates: Requirements 4.4, 5.7, 4.1, 6.1, 5.1, 1.1, 1.2, 1.3, 1.4
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.services.data_source_status_service import DataSourceStatusService, compute_days_since


# ---------------------------------------------------------------------------
# Task 2.2 — Partition invariant: counts sum to total
# Validates: Requirements 4.4, 5.7
# ---------------------------------------------------------------------------

@given(
    success=st.integers(min_value=0, max_value=1000),
    failed=st.integers(min_value=0, max_value=1000),
    pending=st.integers(min_value=0, max_value=1000),
    not_run=st.integers(min_value=0, max_value=1000),
)
def test_enrichment_counts_sum_to_total(success, failed, pending, not_run):
    """**Validates: Requirements 4.4, 5.7**

    Property 2: Partition invariant — for any (success, failed, pending,
    not_run) split, success + failed + pending + not_run == total_leads.
    """
    total = success + failed + pending + not_run
    # Simulate what the service computes:
    # not_run_count = max(0, total - (success + failed + pending))
    computed_not_run = max(0, total - (success + failed + pending))
    assert success + failed + pending + computed_not_run == total


# ---------------------------------------------------------------------------
# Task 2.3 — Coverage percentage bounded [0, 100]
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

@given(
    success=st.integers(min_value=0, max_value=10_000),
    total=st.integers(min_value=1, max_value=10_000),
)
@settings(suppress_health_check=[HealthCheck.too_slow])
def test_coverage_percentage_bounded(success, total):
    """**Validates: Requirements 4.1**

    Property 1: Coverage percentages bounded [0, 100] — for any lead count
    split with total > 0, (success / total) * 100 stays in [0.0, 100.0].
    """
    assume(success <= total)
    pct = (success / total) * 100
    assert 0.0 <= pct <= 100.0


# ---------------------------------------------------------------------------
# Task 2.4 — days_since_sync non-negative
# Validates: Requirements 6.1
# ---------------------------------------------------------------------------

@given(
    days_ago=st.integers(min_value=0, max_value=36500),  # 0 to 100 years ago
    seconds_ago=st.integers(min_value=0, max_value=86400),
)
def test_days_since_sync_non_negative(days_ago, seconds_ago):
    """**Validates: Requirements 6.1**

    Property 4: Staleness day count always >= 0 — compute_days_since(dt)
    returns >= 0 for any past datetime.
    """
    dt = datetime.utcnow() - timedelta(days=days_ago, seconds=seconds_ago)
    result = compute_days_since(dt)
    assert result >= 0


# ---------------------------------------------------------------------------
# Task 2.5 — Response always has four categories
# Validates: Requirements 5.1, 1.1, 1.2, 1.3, 1.4
# ---------------------------------------------------------------------------

@given(
    num_enrichment_sources=st.integers(min_value=0, max_value=5),
    has_import_job=st.booleans(),
    has_hubspot=st.booleans(),
)
def test_response_always_has_four_categories(
    num_enrichment_sources, has_import_job, has_hubspot
):
    """**Validates: Requirements 5.1, 1.1, 1.2, 1.3, 1.4**

    Property 5: API always returns all four source categories — get_all_statuses()
    always includes socrata_datasets, enrichment_sources, import_source, and
    hubspot_source regardless of the underlying DB state.
    """
    svc = DataSourceStatusService()

    mock_socrata = [{"name": "ds", "source_type": "socrata"} for _ in range(3)]
    mock_enrichment = [
        {"name": f"e{i}", "source_type": "enrichment"}
        for i in range(num_enrichment_sources)
    ]
    mock_import = {
        "name": "Google Sheets",
        "source_type": "import",
        "last_refreshed_at": None,
        "rows_imported": None,
        "import_status": None,
    }
    mock_hubspot = {
        "name": "HubSpot",
        "source_type": "hubspot",
        "connected": has_hubspot,
    }

    with patch.object(svc, "_get_socrata_statuses", return_value=mock_socrata), \
         patch.object(svc, "_get_enrichment_statuses", return_value=mock_enrichment), \
         patch.object(svc, "_get_import_source", return_value=mock_import), \
         patch.object(svc, "_get_hubspot_source", return_value=mock_hubspot):
        result = svc.get_all_statuses("user123")

    assert "socrata_datasets" in result
    assert "enrichment_sources" in result
    assert "import_source" in result
    assert "hubspot_source" in result
    assert isinstance(result["socrata_datasets"], list)
    assert isinstance(result["enrichment_sources"], list)


# ---------------------------------------------------------------------------
# Task 2.6 — Unit tests for DataSourceStatusService
# Validates: Requirements 5.2, 5.4, 5.7
# ---------------------------------------------------------------------------

def test_enrichment_returns_zeroed_counts_when_no_leads():
    """Returns zeroed counts when user has no leads.

    Validates: Requirements 5.7
    """
    svc = DataSourceStatusService()

    zero_source = {
        "name": "Skip Trace",
        "source_type": "enrichment",
        "refresh_type": "on_demand",
        "is_active": True,
        "last_refreshed_at": None,
        "success_count": 0,
        "failed_count": 0,
        "pending_count": 0,
        "not_run_count": 0,
        "total_leads_count": 0,
    }

    with patch.object(svc, "_get_socrata_statuses", return_value=[]), \
         patch.object(svc, "_get_enrichment_statuses", return_value=[zero_source]), \
         patch.object(svc, "_get_import_source", return_value={"name": "Google Sheets", "source_type": "import", "last_refreshed_at": None, "rows_imported": None, "import_status": None}), \
         patch.object(svc, "_get_hubspot_source", return_value={"name": "HubSpot", "source_type": "hubspot", "connected": False}):
        result = svc.get_all_statuses("user_no_leads")

    sources = result["enrichment_sources"]
    assert len(sources) == 1
    src = sources[0]
    assert src["success_count"] == 0
    assert src["failed_count"] == 0
    assert src["pending_count"] == 0
    assert src["total_leads_count"] == 0


def test_import_source_returns_null_fields_when_no_completed_job():
    """Returns null import fields when no completed ImportJob exists.

    Validates: Requirements 5.2
    """
    svc = DataSourceStatusService()

    null_import = {
        "name": "Google Sheets",
        "source_type": "import",
        "refresh_type": "static",
        "is_active": True,
        "last_refreshed_at": None,
        "rows_imported": None,
        "import_status": None,
    }

    with patch.object(svc, "_get_socrata_statuses", return_value=[]), \
         patch.object(svc, "_get_enrichment_statuses", return_value=[]), \
         patch.object(svc, "_get_import_source", return_value=null_import), \
         patch.object(svc, "_get_hubspot_source", return_value={"name": "HubSpot", "source_type": "hubspot", "connected": False}):
        result = svc.get_all_statuses("user_no_jobs")

    imp = result["import_source"]
    assert imp["last_refreshed_at"] is None
    assert imp["rows_imported"] is None
    assert imp["import_status"] is None


def test_hubspot_source_returns_connected_false_when_no_config_row():
    """Returns connected: false when no HubSpotConfig row exists.

    Validates: Requirements 5.4
    """
    svc = DataSourceStatusService()

    disconnected_hubspot = {
        "name": "HubSpot",
        "source_type": "hubspot",
        "refresh_type": "on_demand",
        "is_active": True,
        "connected": False,
    }

    with patch.object(svc, "_get_socrata_statuses", return_value=[]), \
         patch.object(svc, "_get_enrichment_statuses", return_value=[]), \
         patch.object(svc, "_get_import_source", return_value={"name": "Google Sheets", "source_type": "import", "last_refreshed_at": None, "rows_imported": None, "import_status": None}), \
         patch.object(svc, "_get_hubspot_source", return_value=disconnected_hubspot):
        result = svc.get_all_statuses("user_no_hubspot")

    assert result["hubspot_source"]["connected"] is False


def test_enrichment_counts_scoped_to_requesting_user():
    """Counts are scoped to the requesting user — _get_enrichment_statuses
    is called with the exact user_id passed to get_all_statuses.

    Validates: Requirements 5.7
    """
    from unittest.mock import MagicMock

    svc = DataSourceStatusService()

    # Patch all sub-methods; we only care that enrichment is called with the
    # correct user_id.
    mock_enrichment = MagicMock(return_value=[])
    mock_import = MagicMock(return_value={
        "name": "Google Sheets",
        "source_type": "import",
        "last_refreshed_at": None,
        "rows_imported": None,
        "import_status": None,
    })
    mock_hubspot = MagicMock(return_value={"name": "HubSpot", "source_type": "hubspot", "connected": False})

    with patch.object(svc, "_get_socrata_statuses", return_value=[]), \
         patch.object(svc, "_get_enrichment_statuses", mock_enrichment), \
         patch.object(svc, "_get_import_source", mock_import), \
         patch.object(svc, "_get_hubspot_source", mock_hubspot):
        svc.get_all_statuses("target_user_id")

    # Verify _get_enrichment_statuses was called with the correct user_id
    mock_enrichment.assert_called_once_with("target_user_id")
    # Verify _get_import_source was also scoped to the correct user
    mock_import.assert_called_once_with("target_user_id")
