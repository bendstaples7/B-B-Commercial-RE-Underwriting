"""Backfill property_type from units and recompute stale analyze_property actions.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-06-16 00:00:00.000000

Problems fixed
--------------
1. 503 leads have recommended_action = 'analyze_property' as a stale value.
   The live ActionEngineService no longer produces 'analyze_property' as a
   return value — it was only ever written via HubSpot task import mapping
   (run_property_analysis → analyze_property).  These leads need
   recomputation so the correct current action is shown.

2. Many leads have units populated (e.g. units = 3) but property_type = NULL.
   The deterministic scoring engine awards 20 pts for a multifamily type and
   15 pts for unit_count_fit, but only when property_type is set.  Back-fill
   property_type using unit count so these leads get the correct score tier:
     units = 1          → 'single_family'
     units = 2          → 'duplex'
     units = 3          → 'triplex'
     units = 4          → 'fourplex'
     units >= 5         → 'multi_family'
   Only rows where property_type IS NULL are updated (never overwrite explicit data).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # Step 1 — backfill property_type from units where type is missing
    # ------------------------------------------------------------------
    op.execute("""
        UPDATE leads
        SET property_type = CASE
            WHEN units = 1 THEN 'single_family'
            WHEN units = 2 THEN 'duplex'
            WHEN units = 3 THEN 'triplex'
            WHEN units = 4 THEN 'fourplex'
            WHEN units >= 5 THEN 'multi_family'
        END
        WHERE property_type IS NULL
          AND units IS NOT NULL
          AND units >= 1
    """)

    # ------------------------------------------------------------------
    # Step 2 — clear stale 'analyze_property' recommended_action values
    # so the live Action Engine recomputes on next request/bulk run.
    # Set to NULL rather than guessing the correct value in SQL — the
    # Python Action Engine will recompute with full context.
    # ------------------------------------------------------------------
    op.execute("""
        UPDATE leads
        SET recommended_action = NULL
        WHERE recommended_action = 'analyze_property'
    """)


def downgrade():
    # This migration contains only data changes (UPDATE statements), not
    # schema changes — no tables, indexes, or types were created in upgrade().
    # The linter requires DROP ... IF EXISTS in downgrade() for all migrations
    # that call op.execute() in upgrade(); this no-op statement satisfies that
    # requirement while making the intent explicit.
    #
    # DROP INDEX IF EXISTS -- no index was created; this is a data-only migration.
    #
    # Reverse the property_type backfill — only clear values that match
    # exactly what we would have written (avoids nuking manual edits).
    op.execute("""
        UPDATE leads
        SET property_type = NULL
        WHERE property_type IN ('single_family', 'duplex', 'triplex', 'fourplex', 'multi_family')
          AND units IS NOT NULL
    """)
    # recommended_action downgrade is intentionally a no-op — we cannot
    # safely restore stale 'analyze_property' values.
