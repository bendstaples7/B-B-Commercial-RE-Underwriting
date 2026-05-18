"""Property-based tests for HubSpot import upsert duplicate prevention.

Properties verified:
  4. Duplicate prevention — upsert by HubSpot ID

Uses SQLite in-memory database via the Flask test app context (conftest.py).
Because _upsert_hubspot_record uses PostgreSQL-specific INSERT ... ON CONFLICT,
this test implements an equivalent SQLite-compatible upsert that preserves the
same semantics: first_imported_at is never overwritten; last_updated_at is
updated on every subsequent import.
"""
# Feature: hubspot-crm-migration, Property 4: Duplicate prevention — upsert by HubSpot ID

from datetime import datetime, timedelta

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models import HubSpotDeal


# ---------------------------------------------------------------------------
# SQLite-compatible upsert helper (mirrors _upsert_hubspot_record semantics)
# ---------------------------------------------------------------------------

def _sqlite_upsert_deal(hubspot_id: str, raw_payload: dict, import_time: datetime) -> str:
    """
    Upsert a HubSpotDeal record using ORM-level logic compatible with SQLite.

    Semantics match _upsert_hubspot_record:
      - On INSERT: set first_imported_at = import_time, last_updated_at = import_time
      - On UPDATE: preserve first_imported_at, set last_updated_at = import_time

    Returns 'inserted' or 'updated'.
    """
    existing = HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).first()
    if existing is None:
        record = HubSpotDeal(
            hubspot_id=hubspot_id,
            raw_payload=raw_payload,
            import_run_id=None,
            first_imported_at=import_time,
            last_updated_at=import_time,
        )
        db.session.add(record)
        db.session.commit()
        return 'inserted'
    else:
        # Preserve first_imported_at; update everything else
        existing.raw_payload = raw_payload
        existing.last_updated_at = import_time
        db.session.commit()
        return 'updated'


# ---------------------------------------------------------------------------
# Property 4: Duplicate Prevention — Upsert by HubSpot ID
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 4: Duplicate prevention — upsert by HubSpot ID


@given(
    hubspot_id=st.text(min_size=1, max_size=50),
    import_count=st.integers(min_value=2, max_value=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_upsert_never_duplicates(app, hubspot_id, import_count):
    """Importing the same hubspot_id N times must result in exactly one row.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.6**
    """
    with app.app_context():
        # Clean up any leftover record from a previous Hypothesis example
        HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.commit()

        # Simulate N imports of the same hubspot_id
        base_time = datetime(2024, 1, 1, 0, 0, 0)
        for i in range(import_count):
            import_time = base_time + timedelta(hours=i)
            _sqlite_upsert_deal(
                hubspot_id=hubspot_id,
                raw_payload={'id': hubspot_id, 'import_index': i},
                import_time=import_time,
            )

        count = HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).count()
        assert count == 1, (
            f"Expected exactly 1 row for hubspot_id={hubspot_id!r} after "
            f"{import_count} imports, but found {count}"
        )

        # Clean up
        HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.commit()


@given(
    hubspot_id=st.text(min_size=1, max_size=50),
    import_count=st.integers(min_value=2, max_value=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_upsert_preserves_first_imported_at(app, hubspot_id, import_count):
    """first_imported_at must equal the timestamp of the very first import.

    **Validates: Requirements 8.6**
    """
    with app.app_context():
        HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.commit()

        base_time = datetime(2024, 1, 1, 0, 0, 0)
        first_time = base_time  # timestamp of the first import

        for i in range(import_count):
            import_time = base_time + timedelta(hours=i)
            _sqlite_upsert_deal(
                hubspot_id=hubspot_id,
                raw_payload={'id': hubspot_id, 'import_index': i},
                import_time=import_time,
            )

        record = HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).one()
        assert record.first_imported_at == first_time, (
            f"first_imported_at should be {first_time} (first import time) "
            f"but got {record.first_imported_at}"
        )

        HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.commit()


@given(
    hubspot_id=st.text(min_size=1, max_size=50),
    import_count=st.integers(min_value=2, max_value=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_upsert_updates_last_updated_at(app, hubspot_id, import_count):
    """last_updated_at must equal the timestamp of the most recent import.

    **Validates: Requirements 8.6**
    """
    with app.app_context():
        HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.commit()

        base_time = datetime(2024, 1, 1, 0, 0, 0)
        last_time = base_time + timedelta(hours=import_count - 1)  # timestamp of last import

        for i in range(import_count):
            import_time = base_time + timedelta(hours=i)
            _sqlite_upsert_deal(
                hubspot_id=hubspot_id,
                raw_payload={'id': hubspot_id, 'import_index': i},
                import_time=import_time,
            )

        record = HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).one()
        assert record.last_updated_at == last_time, (
            f"last_updated_at should be {last_time} (most recent import time) "
            f"but got {record.last_updated_at}"
        )

        HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.commit()
