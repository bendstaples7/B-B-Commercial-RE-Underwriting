"""Property-based tests for HubSpot CRM validation — Property 3.

Verifies that empty and whitespace-only inputs are always rejected by the
OrganizationService, InteractionService, and TaskService, and that no
database record is created when validation fails.

# Feature: hubspot-crm-migration, Property 3: Empty and whitespace inputs are always rejected
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.organization import Organization
from app.models.interaction import Interaction
from app.models.task import Task
from app.services.organization_service import OrganizationService
from app.services.interaction_service import InteractionService
from app.services.task_service import TaskService
from app.exceptions import (
    OrganizationValidationError,
    InteractionValidationError,
    TaskValidationError,
)

# ---------------------------------------------------------------------------
# Whitespace-only string strategy
# ---------------------------------------------------------------------------

# Generates strings composed entirely of Unicode whitespace characters
# (space separators Zs and control characters Cc), including the empty string.
whitespace_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('Zs', 'Cc')),
    min_size=0,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property 3a: Whitespace-only Organization name is always rejected
# ---------------------------------------------------------------------------


class TestOrganizationWhitespaceRejected:
    """Property 3a: Whitespace-only Organization name raises OrganizationValidationError.

    For any whitespace-only (or empty) string submitted as the Organization
    name, OrganizationService.create() SHALL raise OrganizationValidationError
    and no Organization record SHALL be created in the database.

    **Validates: Requirements 1.5**
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(name=whitespace_strategy)
    def test_whitespace_org_name_raises_validation_error(self, app, name: str) -> None:
        """Whitespace-only Organization name always raises OrganizationValidationError.

        # Feature: hubspot-crm-migration, Property 3: Empty and whitespace inputs are always rejected
        **Validates: Requirements 1.5**
        """
        with app.app_context():
            service = OrganizationService()
            count_before = Organization.query.count()

            with pytest.raises(OrganizationValidationError):
                service.create({'name': name}, changed_by='test_user')

            # No record should have been created
            count_after = Organization.query.count()
            assert count_after == count_before, (
                f"Expected no new Organization records after validation failure, "
                f"but count changed from {count_before} to {count_after} "
                f"(input name={name!r})"
            )


# ---------------------------------------------------------------------------
# Property 3b: Whitespace-only Interaction body is always rejected
# ---------------------------------------------------------------------------


class TestInteractionWhitespaceRejected:
    """Property 3b: Whitespace-only Interaction body raises InteractionValidationError.

    For any whitespace-only (or empty) string submitted as the Interaction
    body, InteractionService.create() SHALL raise InteractionValidationError
    and no Interaction record SHALL be created in the database.

    **Validates: Requirements 2.3**
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(body=whitespace_strategy)
    def test_whitespace_interaction_body_raises_validation_error(self, app, body: str) -> None:
        """Whitespace-only Interaction body always raises InteractionValidationError.

        # Feature: hubspot-crm-migration, Property 3: Empty and whitespace inputs are always rejected
        **Validates: Requirements 2.3**
        """
        with app.app_context():
            service = InteractionService()
            count_before = Interaction.query.count()

            with pytest.raises(InteractionValidationError):
                service.create({
                    'body': body,
                    'interaction_type': 'note',
                    'associations': [{'target_type': 'lead', 'target_id': 1}],
                })

            # No record should have been created
            count_after = Interaction.query.count()
            assert count_after == count_before, (
                f"Expected no new Interaction records after validation failure, "
                f"but count changed from {count_before} to {count_after} "
                f"(input body={body!r})"
            )


# ---------------------------------------------------------------------------
# Property 3c: Whitespace-only Task title is always rejected
# ---------------------------------------------------------------------------


class TestTaskWhitespaceRejected:
    """Property 3c: Whitespace-only Task title raises TaskValidationError.

    For any whitespace-only (or empty) string submitted as the Task title,
    TaskService.create() SHALL raise TaskValidationError and no Task record
    SHALL be created in the database.

    **Validates: Requirements 3.3**
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(title=whitespace_strategy)
    def test_whitespace_task_title_raises_validation_error(self, app, title: str) -> None:
        """Whitespace-only Task title always raises TaskValidationError.

        # Feature: hubspot-crm-migration, Property 3: Empty and whitespace inputs are always rejected
        **Validates: Requirements 3.3**
        """
        with app.app_context():
            service = TaskService()
            count_before = Task.query.count()

            with pytest.raises(TaskValidationError):
                service.create({
                    'title': title,
                    'associations': [{'target_type': 'lead', 'target_id': 1}],
                })

            # No record should have been created
            count_after = Task.query.count()
            assert count_after == count_before, (
                f"Expected no new Task records after validation failure, "
                f"but count changed from {count_before} to {count_after} "
                f"(input title={title!r})"
            )
