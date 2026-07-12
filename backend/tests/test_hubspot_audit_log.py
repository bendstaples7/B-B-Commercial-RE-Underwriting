"""Property-based tests for the Organization audit log growth invariant.

Property verified:
  20. Organization Audit Log Grows on Every Mutation — for any sequence of N
      create/update operations on an Organization record, the audit log for
      that organization must contain at least N entries after all operations
      complete.

This test requires a Flask app context because it creates Organization records
and calls OrganizationService.create() / OrganizationService.update() which
write to the in-memory SQLite database.
"""
# Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.organization import Organization
from app.models.organization_audit_log import OrganizationAuditLog
from app.services.organization_service import OrganizationService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# N: number of create/update operations (1..20)
_n_st = st.integers(min_value=1, max_value=20)

# Non-empty org names (ASCII-safe for SQLite)
_name_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ",
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())  # ensure at least one non-whitespace character

# Org types allowed by the model enum
_org_type_st = st.sampled_from([
    "llc", "trust", "corporation", "brokerage",
    "law_firm", "property_management", "nonprofit", "unknown",
])

# Status values
_status_st = st.sampled_from(["active", "inactive", "unknown"])

# Changed-by identifiers
_changed_by_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    min_size=3,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Property 20: Organization Audit Log Grows on Every Mutation
# ---------------------------------------------------------------------------


class TestProperty20AuditLogGrowsOnMutation:
    """Property 20 — audit log contains at least N entries after N create/update operations.

    **Validates: Requirements 1.4**
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(n=_n_st, name=_name_st)
    def test_audit_log_has_at_least_n_entries_after_n_updates(
        self, app, n: int, name: str
    ) -> None:
        """After N update operations on an Organization, the audit log must have >= N entries.

        The create() call itself writes one audit entry (__created__), so after
        1 create + (N-1) updates the log must have at least N entries.

        # Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation
        **Validates: Requirements 1.4**
        """
        with app.app_context():
            svc = OrganizationService()

            # Operation 1: create (writes 1 audit entry for __created__)
            org = svc.create({"name": name}, changed_by="test_user")
            org_id = org.id

            # Operations 2..N: update the name each time (each writes 1 audit entry)
            for i in range(1, n):
                new_name = f"{name[:40]} v{i}"
                svc.update(org_id, {"name": new_name}, changed_by=f"user_{i}")

            # Verify audit log has at least N entries
            log_entries = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).all()

            assert len(log_entries) >= n, (
                f"Expected at least {n} audit log entries after {n} operations, "
                f"but found {len(log_entries)}"
            )

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(n=_n_st, name=_name_st, org_type=_org_type_st)
    def test_audit_log_grows_with_multi_field_updates(
        self, app, n: int, name: str, org_type: str
    ) -> None:
        """Audit log grows when multiple fields are updated in a single update() call.

        Each changed field produces its own audit entry, so updating 2 fields
        in one call produces 2 entries for that call.

        # Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation
        **Validates: Requirements 1.4**
        """
        with app.app_context():
            svc = OrganizationService()

            # Create (1 audit entry)
            org = svc.create({"name": name, "org_type": org_type}, changed_by="creator")
            org_id = org.id

            count_before = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).count()

            # Perform N update operations, each changing the name
            for i in range(n):
                svc.update(
                    org_id,
                    {"name": f"{name[:38]} u{i}"},
                    changed_by=f"updater_{i}",
                )

            count_after = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).count()

            # Each update that changes a field adds at least 1 entry
            assert count_after >= count_before + n, (
                f"Expected at least {count_before + n} entries after {n} updates, "
                f"but found {count_after}"
            )

            db.session.rollback()

    def test_create_writes_exactly_one_audit_entry(self, app) -> None:
        """OrganizationService.create() must write exactly one audit entry (__created__).

        # Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation
        **Validates: Requirements 1.4**
        """
        with app.app_context():
            svc = OrganizationService()
            org = svc.create({"name": "Test Org LLC"}, changed_by="test_user")

            entries = OrganizationAuditLog.query.filter_by(
                organization_id=org.id
            ).all()

            assert len(entries) == 1
            assert entries[0].field_name == "__created__"
            assert entries[0].changed_by == "test_user"

            db.session.rollback()

    def test_update_with_no_field_changes_writes_no_audit_entries(self, app) -> None:
        """OrganizationService.update() with no actual field changes must not add audit entries.

        The audit log only grows when a field value actually changes.

        # Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation
        **Validates: Requirements 1.4**
        """
        with app.app_context():
            svc = OrganizationService()
            org = svc.create({"name": "Stable Org"}, changed_by="creator")
            org_id = org.id

            count_before = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).count()

            # Update with the same name — no actual change
            svc.update(org_id, {"name": "Stable Org"}, changed_by="updater")

            count_after = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).count()

            assert count_after == count_before, (
                f"Expected no new audit entries when no fields changed, "
                f"but count went from {count_before} to {count_after}"
            )

            db.session.rollback()

    def test_each_update_adds_entry_per_changed_field(self, app) -> None:
        """Each changed field in a single update() call produces its own audit entry.

        # Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation
        **Validates: Requirements 1.4**
        """
        with app.app_context():
            svc = OrganizationService()
            org = svc.create(
                {"name": "Multi Field Org", "org_type": "llc", "status": "active"},
                changed_by="creator",
            )
            org_id = org.id

            count_before = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).count()

            # Update two fields at once
            svc.update(
                org_id,
                {"name": "Multi Field Org Updated", "status": "inactive"},
                changed_by="updater",
            )

            count_after = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).count()

            # Two fields changed → two new audit entries
            assert count_after == count_before + 2, (
                f"Expected {count_before + 2} entries after updating 2 fields, "
                f"but found {count_after}"
            )

            db.session.rollback()

    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(n=st.integers(min_value=1, max_value=20))
    def test_audit_log_count_is_monotonically_non_decreasing(
        self, app, n: int
    ) -> None:
        """The audit log count must never decrease after any sequence of mutations.

        # Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation
        **Validates: Requirements 1.4**
        """
        with app.app_context():
            svc = OrganizationService()
            org = svc.create({"name": "Monotone Org"}, changed_by="creator")
            org_id = org.id

            previous_count = OrganizationAuditLog.query.filter_by(
                organization_id=org_id
            ).count()

            for i in range(n):
                svc.update(
                    org_id,
                    {"name": f"Monotone Org Step {i}"},
                    changed_by=f"user_{i}",
                )
                current_count = OrganizationAuditLog.query.filter_by(
                    organization_id=org_id
                ).count()

                assert current_count >= previous_count, (
                    f"Audit log count decreased from {previous_count} to "
                    f"{current_count} after update {i}"
                )
                previous_count = current_count

            db.session.rollback()
