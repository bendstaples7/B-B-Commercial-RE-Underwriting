"""Add a uniqueness constraint for HubSpot signal dedup (race-safe).

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-06-18

Problem:
    HubSpotSignalExtractorService dedups signals in application code
    (``_signal_already_exists``) before inserting, but WITHOUT a database-level
    uniqueness constraint two extraction workers running in parallel can both
    pass that pre-check and INSERT duplicate ``hubspot_signals`` rows for the
    same dedup key — re-introducing the duplicate-signal bug under a race
    (e.g. a single re-extracted PRIOR_WARM_CONVERSATION stacking its score
    bonus multiple times).

Fix:
    Create a UNIQUE index on
    ``(lead_id, signal_type, source_engagement_id)`` using PostgreSQL 15
    ``NULLS NOT DISTINCT`` so a NULL ``source_engagement_id`` (the
    FOLLOW_UP_OVERDUE lead-level signal) is treated as equal — giving
    lead-level uniqueness for those rows while keeping per-engagement
    uniqueness for every other signal type. This mirrors the application
    dedup key exactly and makes parallel extraction race-safe: the second
    concurrent INSERT now fails with an IntegrityError that the extractor
    catches and skips.

    Any pre-existing duplicate rows are removed first — keeping the earliest
    row (MIN(id)) per dedup group — so the unique index can be built. NULL
    source engagements are treated as equal in the dedupe via a COALESCE
    sentinel (the column is VARCHAR(50), so a string sentinel is used).

Idempotent — the dedupe DELETE is naturally a no-op once duplicates are gone
and the index uses ``CREATE UNIQUE INDEX IF NOT EXISTS``, so the whole
migration is safe to re-run. Requires PostgreSQL 15+ for ``NULLS NOT
DISTINCT`` (CI and production both run PostgreSQL 15).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd6e7f8a9b0c1'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Remove pre-existing duplicate rows so the unique index can be created.
    #    Keep the earliest row (MIN(id)) per dedup group. A NULL
    #    source_engagement_id is treated as a single distinct value via the
    #    COALESCE sentinel, matching the NULLS NOT DISTINCT semantics of the
    #    index created below.
    op.execute(
        """
        DELETE FROM hubspot_signals
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM hubspot_signals
            GROUP BY lead_id, signal_type, COALESCE(source_engagement_id, '__NULL__')
        )
        """
    )

    # 2. Enforce the dedup key at the database level. NULLS NOT DISTINCT
    #    (PostgreSQL 15+) collapses NULL source_engagement_id rows to one per
    #    (lead_id, signal_type) — exactly the FOLLOW_UP_OVERDUE lead-level
    #    rule — while non-NULL sources remain unique per engagement.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_hubspot_signals_dedup "
        "ON hubspot_signals (lead_id, signal_type, source_engagement_id) "
        "NULLS NOT DISTINCT"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_hubspot_signals_dedup")
