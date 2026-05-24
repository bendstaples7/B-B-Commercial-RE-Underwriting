"""
Property-based tests for resource isolation — marketing lists and import jobs.

Feature: multi-user-lead-exclusivity

**Validates: Requirements 4.5, 6.1, 6.2, 6.3, 6.4**
"""
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models import MarketingList, ImportJob


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# User ID strategy: arbitrary non-empty lowercase alphanumeric strings
_user_id_strategy = st.text(
    alphabet='abcdefghijklmnopqrstuvwxyz0123456789-',
    min_size=4,
    max_size=36,
).filter(lambda s: s.strip() == s and len(s) >= 4)

# List name strategy — minimal valid name
_name_strategy = st.text(
    alphabet='abcdefghijklmnopqrstuvwxyz0123456789 ',
    min_size=3,
    max_size=50,
).map(str.strip).filter(lambda s: len(s) >= 3)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_marketing_list(user_id: str, name_suffix: str = '') -> MarketingList:
    """Create and persist a MarketingList owned by *user_id*."""
    ml = MarketingList(
        name=f'Test List{name_suffix}',
        user_id=user_id,
    )
    db.session.add(ml)
    db.session.commit()
    return ml


def _create_import_job(user_id: str) -> ImportJob:
    """Create and persist an ImportJob owned by *user_id*."""
    job = ImportJob(
        user_id=user_id,
        spreadsheet_id='test-spreadsheet-id',
        sheet_name='Sheet1',
        status='completed',
    )
    db.session.add(job)
    db.session.commit()
    return job


def _delete_resources_for_users(*user_ids: str) -> None:
    """Delete all MarketingList and ImportJob rows owned by any of the given user IDs."""
    for uid in user_ids:
        MarketingList.query.filter_by(user_id=uid).delete()
        ImportJob.query.filter_by(user_id=uid).delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# Property 14: Resource isolation — marketing lists and import jobs
# ---------------------------------------------------------------------------

@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    user_id_1=_user_id_strategy,
    user_id_2=_user_id_strategy,
)
def test_property_14_resource_isolation_marketing_lists_and_import_jobs(
    app, client, user_id_1, user_id_2
):
    """
    Property 14: Resource isolation — marketing lists and import jobs

    For any two distinct users ``u1`` and ``u2``, each with marketing lists
    and import jobs:

    1. ``GET /api/leads/marketing/lists`` as ``u1`` returns only records
       where ``user_id == u1``.
    2. ``GET /api/leads/marketing/lists/<id>`` for a list owned by ``u1``,
       authenticated as ``u2``, returns HTTP 404.
    3. ``GET /api/leads/import/jobs`` as ``u1`` returns only records
       where ``user_id == u1``.
    4. ``GET /api/leads/import/jobs/<id>`` for a job owned by ``u1``,
       authenticated as ``u2``, returns HTTP 404.

    **Validates: Requirements 4.5, 6.1, 6.2, 6.3, 6.4**
    """
    assume(user_id_1 != user_id_2)

    with app.app_context():
        _delete_resources_for_users(user_id_1, user_id_2)

        try:
            # Create one marketing list and one import job for each user
            ml1 = _create_marketing_list(user_id_1, name_suffix=' U1')
            ml2 = _create_marketing_list(user_id_2, name_suffix=' U2')
            job1 = _create_import_job(user_id_1)
            job2 = _create_import_job(user_id_2)

            ml1_id = ml1.id
            ml2_id = ml2.id
            job1_id = job1.id
            job2_id = job2.id

            # ------------------------------------------------------------------
            # 1. Marketing list isolation: u1's list query returns only u1's lists
            # ------------------------------------------------------------------
            resp = client.get(
                '/api/leads/marketing/lists',
                headers={'X-User-Id': user_id_1},
            )
            assert resp.status_code == 200, (
                f"GET /api/leads/marketing/lists as user_1={user_id_1!r} "
                f"should return 200, got {resp.status_code}: {resp.get_data(as_text=True)}"
            )
            data = resp.get_json()
            returned_ids = {ml['id'] for ml in data.get('lists', [])}
            assert ml1_id in returned_ids, (
                f"user_1={user_id_1!r}'s own list (id={ml1_id}) should appear "
                f"in their list query, but got ids: {returned_ids}"
            )
            assert ml2_id not in returned_ids, (
                f"user_2={user_id_2!r}'s list (id={ml2_id}) should NOT appear "
                f"in user_1={user_id_1!r}'s list query, but got ids: {returned_ids}"
            )
            # All returned lists must belong to user_1
            for ml in data.get('lists', []):
                assert ml['user_id'] == user_id_1, (
                    f"List id={ml['id']} has user_id={ml['user_id']!r}, "
                    f"expected {user_id_1!r}"
                )

            # ------------------------------------------------------------------
            # 2. Cross-user marketing list access returns 404
            # The marketing controller enforces ownership on the members endpoint
            # (GET /lists/<id>/members) and on PUT/DELETE /lists/<id>.
            # We use the members endpoint as the per-resource ownership check.
            # ------------------------------------------------------------------
            cross_ml_resp = client.get(
                f'/api/leads/marketing/lists/{ml1_id}/members',
                headers={'X-User-Id': user_id_2},
            )
            assert cross_ml_resp.status_code == 404, (
                f"GET /api/leads/marketing/lists/{ml1_id}/members as user_2={user_id_2!r} "
                f"(list owned by user_1={user_id_1!r}) should return 404, "
                f"got {cross_ml_resp.status_code}: {cross_ml_resp.get_data(as_text=True)}"
            )

            # Sanity check: u1 can access their own list's members (200)
            own_ml_resp = client.get(
                f'/api/leads/marketing/lists/{ml1_id}/members',
                headers={'X-User-Id': user_id_1},
            )
            assert own_ml_resp.status_code == 200, (
                f"GET /api/leads/marketing/lists/{ml1_id}/members as owner user_1={user_id_1!r} "
                f"should return 200, got {own_ml_resp.status_code}: "
                f"{own_ml_resp.get_data(as_text=True)}"
            )

            # ------------------------------------------------------------------
            # 3. Import job isolation: u1's job query returns only u1's jobs
            # ------------------------------------------------------------------
            jobs_resp = client.get(
                '/api/leads/import/jobs',
                headers={'X-User-Id': user_id_1},
            )
            assert jobs_resp.status_code == 200, (
                f"GET /api/leads/import/jobs as user_1={user_id_1!r} "
                f"should return 200, got {jobs_resp.status_code}: {jobs_resp.get_data(as_text=True)}"
            )
            jobs_data = jobs_resp.get_json()
            returned_job_ids = {j['id'] for j in jobs_data.get('jobs', [])}
            assert job1_id in returned_job_ids, (
                f"user_1={user_id_1!r}'s own job (id={job1_id}) should appear "
                f"in their jobs query, but got ids: {returned_job_ids}"
            )
            assert job2_id not in returned_job_ids, (
                f"user_2={user_id_2!r}'s job (id={job2_id}) should NOT appear "
                f"in user_1={user_id_1!r}'s jobs query, but got ids: {returned_job_ids}"
            )
            # All returned jobs must belong to user_1
            for job in jobs_data.get('jobs', []):
                assert job['user_id'] == user_id_1, (
                    f"Job id={job['id']} has user_id={job['user_id']!r}, "
                    f"expected {user_id_1!r}"
                )

            # ------------------------------------------------------------------
            # 4. Cross-user import job access returns 404
            # ------------------------------------------------------------------
            cross_job_resp = client.get(
                f'/api/leads/import/jobs/{job1_id}',
                headers={'X-User-Id': user_id_2},
            )
            assert cross_job_resp.status_code == 404, (
                f"GET /api/leads/import/jobs/{job1_id} as user_2={user_id_2!r} "
                f"(job owned by user_1={user_id_1!r}) should return 404, "
                f"got {cross_job_resp.status_code}: {cross_job_resp.get_data(as_text=True)}"
            )

            # Sanity check: u1 can access their own job
            own_job_resp = client.get(
                f'/api/leads/import/jobs/{job1_id}',
                headers={'X-User-Id': user_id_1},
            )
            assert own_job_resp.status_code == 200, (
                f"GET /api/leads/import/jobs/{job1_id} as owner user_1={user_id_1!r} "
                f"should return 200, got {own_job_resp.status_code}: "
                f"{own_job_resp.get_data(as_text=True)}"
            )

        finally:
            _delete_resources_for_users(user_id_1, user_id_2)
