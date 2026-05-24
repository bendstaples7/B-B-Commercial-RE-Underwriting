"""
Property-based tests for the Alembic migration that adds owner_user_id to leads.

Feature: multi-user-lead-exclusivity
"""
import uuid
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a positive integer count of leads to create (1–50 per example).
# Using min_value=1 ensures we always have at least one lead to check.
_lead_count_strategy = st.integers(min_value=1, max_value=50)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_lead_without_owner(db):
    """Insert a single Lead row with owner_user_id=NULL (pre-migration state).

    All non-nullable columns on the Property model are given minimal valid
    values.  owner_user_id is intentionally left as NULL to simulate the
    state of the database before the migration runs.
    """
    from app.models.lead import Lead

    lead = Lead(
        # owner_user_id deliberately omitted → NULL
        lead_category='residential',
        lead_status='new',
        has_phone=False,
        has_email=False,
        has_property_match=False,
        analysis_complete=False,
        follow_up_overdue=False,
        is_warm=False,
        data_completeness_score=0.0,
        unanswered_call_count=0,
        review_required=False,
        suppression_flag=False,
        lead_score=0.0,
    )
    db.session.add(lead)
    db.session.flush()  # assign an id without committing
    return lead


def _create_ben_user(db):
    """Create Ben's User record (simulating the migration seeding step).

    Returns the User instance with a freshly generated user_id.
    """
    from app.models.user import User
    import bcrypt

    ben_user_id = str(uuid.uuid4())
    # Use a minimal bcrypt hash — work factor 4 is the minimum and keeps
    # tests fast while still exercising the real bcrypt code path.
    password_hash = bcrypt.hashpw(b'test_password', bcrypt.gensalt(rounds=4)).decode('utf-8')

    ben = User(
        user_id=ben_user_id,
        email='ben.d.staples.7@gmail.com',
        email_lower='ben.d.staples.7@gmail.com',
        password_hash=password_hash,
        display_name='Ben',
        is_active=True,
    )
    db.session.add(ben)
    db.session.flush()
    return ben


def _simulate_migration(db, ben_user_id: str) -> None:
    """Simulate the migration logic from s9t0u1v2w3x4 using SQLAlchemy ORM.

    The actual Alembic migration runs raw SQL against PostgreSQL.  For the
    in-memory SQLite test DB we replicate the same logic:

      UPDATE leads
      SET owner_user_id = <ben_user_id>
      WHERE owner_user_id IS NULL
    """
    from app.models.lead import Lead

    Lead.query.filter(Lead.owner_user_id.is_(None)).update(
        {'owner_user_id': ben_user_id},
        synchronize_session='fetch',
    )
    db.session.flush()


def _cleanup(db) -> None:
    """Remove all Lead and User rows created during a Hypothesis example."""
    from app.models.lead import Lead
    from app.models.user import User

    Lead.query.delete()
    User.query.filter_by(email_lower='ben.d.staples.7@gmail.com').delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# Property 15: Post-migration lead ownership invariant
# ---------------------------------------------------------------------------

@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(lead_count=_lead_count_strategy)
def test_property_15_post_migration_lead_ownership_invariant(app, lead_count):
    """
    Property 15: Post-migration lead ownership invariant

    After running the migration logic against a database that contains
    ``lead_count`` Lead rows with NULL ``owner_user_id`` values (simulating
    the pre-migration state), EVERY lead row SHALL have a non-NULL
    ``owner_user_id``.

    The migration logic is simulated directly via SQLAlchemy ORM operations
    because the actual Alembic migration targets PostgreSQL, not the SQLite
    in-memory test database.

    **Validates: Requirements 5.3**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Lead

        try:
            # ------------------------------------------------------------------
            # Step 1: Create ``lead_count`` Lead rows WITHOUT owner_user_id
            #         (simulating the pre-migration state of the database).
            # ------------------------------------------------------------------
            for _ in range(lead_count):
                _create_lead_without_owner(db)

            # Verify the pre-condition: all newly created leads have NULL owner.
            null_owner_count = Lead.query.filter(Lead.owner_user_id.is_(None)).count()
            assert null_owner_count == lead_count, (
                f"Pre-condition failed: expected {lead_count} leads with NULL "
                f"owner_user_id, found {null_owner_count}"
            )

            # ------------------------------------------------------------------
            # Step 2: Create Ben's User record (simulating the migration seeding
            #         step that inserts Ben's account before assigning leads).
            # ------------------------------------------------------------------
            ben = _create_ben_user(db)

            # ------------------------------------------------------------------
            # Step 3: Run the migration logic — assign all NULL-owner leads to Ben.
            # ------------------------------------------------------------------
            _simulate_migration(db, ben.user_id)

            # ------------------------------------------------------------------
            # Step 4: Assert the invariant — every lead has a non-NULL owner.
            # ------------------------------------------------------------------
            all_leads = Lead.query.all()
            assert len(all_leads) == lead_count, (
                f"Expected {lead_count} leads after migration, found {len(all_leads)}"
            )

            for lead in all_leads:
                assert lead.owner_user_id is not None, (
                    f"Lead id={lead.id} has NULL owner_user_id after migration "
                    f"(lead_count={lead_count})"
                )
                assert lead.owner_user_id == ben.user_id, (
                    f"Lead id={lead.id} has owner_user_id={lead.owner_user_id!r} "
                    f"but expected Ben's user_id={ben.user_id!r}"
                )

        finally:
            # Always clean up so the next Hypothesis example starts with a
            # clean DB state regardless of whether assertions passed or failed.
            _cleanup(db)
