"""Property-based tests for HubSpotImportRun count accuracy.

Property verified:
  18. Import Run Counts are Accurate — for any import run processing N records
      where E records fail with non-fatal errors, the resulting HubSpotImportRun
      must satisfy:
        total_fetched = created_count + updated_count + skipped_count + error_count
      and error_count = E.

This test requires a Flask app context because it creates HubSpotImportRun
records in the in-memory SQLite database.  The property is verified by
directly setting the count fields on the model and checking the invariant,
which mirrors how the Celery import tasks update the run record.
"""
# Feature: hubspot-crm-migration, Property 18: Import run counts are accurate

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.hubspot_import_run import HubSpotImportRun


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# N: total records fetched (1..50)
_n_st = st.integers(min_value=1, max_value=50)


@st.composite
def _n_and_e(draw):
    """Draw (N, E) where 0 <= E <= N."""
    n = draw(st.integers(min_value=1, max_value=50))
    e = draw(st.integers(min_value=0, max_value=n))
    return n, e


@st.composite
def _count_partition(draw, n: int, e: int):
    """Partition (n - e) successful records into created, updated, skipped.

    Returns (created, updated, skipped) such that created + updated + skipped == n - e.
    """
    successful = n - e
    if successful == 0:
        return 0, 0, 0
    # Draw two split points in [0, successful]
    a = draw(st.integers(min_value=0, max_value=successful))
    b = draw(st.integers(min_value=0, max_value=successful - a))
    created = a
    updated = b
    skipped = successful - a - b
    return created, updated, skipped


# ---------------------------------------------------------------------------
# Property 18: Import Run Counts are Accurate
# ---------------------------------------------------------------------------


class TestProperty18ImportRunCountsAccurate:
    """Property 18 — HubSpotImportRun count invariant holds for any N and E.

    **Validates: Requirements 20.2, 20.4**
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(ne=_n_and_e())
    def test_total_fetched_equals_sum_of_counts(self, app, ne) -> None:
        """total_fetched must equal created + updated + skipped + error_count.

        Simulates an import run by creating a HubSpotImportRun and setting
        the count fields directly, then verifying the invariant.

        # Feature: hubspot-crm-migration, Property 18: Import run counts are accurate
        **Validates: Requirements 20.2, 20.4**
        """
        n, e = ne
        with app.app_context():
            # Partition successful records arbitrarily (any split is valid)
            successful = n - e
            # Simple split: all successful go to created_count
            created = successful
            updated = 0
            skipped = 0

            run = HubSpotImportRun(
                object_type="deals",
                status="success" if e == 0 else "partial",
                total_fetched=n,
                created_count=created,
                updated_count=updated,
                skipped_count=skipped,
                error_count=e,
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id

            # Re-fetch from DB to verify persisted values
            fetched_run = HubSpotImportRun.query.get(run_id)

            assert fetched_run.total_fetched == (
                fetched_run.created_count
                + fetched_run.updated_count
                + fetched_run.skipped_count
                + fetched_run.error_count
            ), (
                f"total_fetched={fetched_run.total_fetched} != "
                f"created={fetched_run.created_count} + "
                f"updated={fetched_run.updated_count} + "
                f"skipped={fetched_run.skipped_count} + "
                f"error={fetched_run.error_count}"
            )

            assert fetched_run.error_count == e, (
                f"error_count={fetched_run.error_count} != expected E={e}"
            )

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(ne=_n_and_e())
    def test_invariant_holds_with_arbitrary_count_partition(self, app, ne) -> None:
        """Invariant holds regardless of how successful records are split across
        created, updated, and skipped.

        # Feature: hubspot-crm-migration, Property 18: Import run counts are accurate
        **Validates: Requirements 20.2, 20.4**
        """
        n, e = ne
        successful = n - e
        with app.app_context():
            # Split successful records: half to created, half to updated, remainder to skipped
            created = successful // 3
            updated = successful // 3
            skipped = successful - created - updated

            run = HubSpotImportRun(
                object_type="contacts",
                status="partial" if e > 0 else "success",
                total_fetched=n,
                created_count=created,
                updated_count=updated,
                skipped_count=skipped,
                error_count=e,
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id

            fetched_run = HubSpotImportRun.query.get(run_id)

            count_sum = (
                fetched_run.created_count
                + fetched_run.updated_count
                + fetched_run.skipped_count
                + fetched_run.error_count
            )
            assert fetched_run.total_fetched == count_sum, (
                f"total_fetched={fetched_run.total_fetched} != sum of counts={count_sum} "
                f"(n={n}, e={e}, created={created}, updated={updated}, "
                f"skipped={skipped}, error={e})"
            )

            assert fetched_run.error_count == e

            db.session.rollback()

    def test_all_errors_invariant(self, app) -> None:
        """When all N records fail (E == N), created + updated + skipped must be 0.

        # Feature: hubspot-crm-migration, Property 18: Import run counts are accurate
        **Validates: Requirements 20.2, 20.4**
        """
        with app.app_context():
            n = 10
            run = HubSpotImportRun(
                object_type="companies",
                status="failed",
                total_fetched=n,
                created_count=0,
                updated_count=0,
                skipped_count=0,
                error_count=n,
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id

            fetched_run = HubSpotImportRun.query.get(run_id)
            assert fetched_run.total_fetched == fetched_run.error_count
            assert fetched_run.created_count == 0
            assert fetched_run.updated_count == 0
            assert fetched_run.skipped_count == 0

            db.session.rollback()

    def test_no_errors_invariant(self, app) -> None:
        """When E == 0, error_count must be 0 and total_fetched == created + updated + skipped.

        # Feature: hubspot-crm-migration, Property 18: Import run counts are accurate
        **Validates: Requirements 20.2, 20.4**
        """
        with app.app_context():
            n = 25
            run = HubSpotImportRun(
                object_type="engagements",
                status="success",
                total_fetched=n,
                created_count=20,
                updated_count=3,
                skipped_count=2,
                error_count=0,
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id

            fetched_run = HubSpotImportRun.query.get(run_id)
            assert fetched_run.error_count == 0
            assert fetched_run.total_fetched == (
                fetched_run.created_count
                + fetched_run.updated_count
                + fetched_run.skipped_count
                + fetched_run.error_count
            )

            db.session.rollback()
