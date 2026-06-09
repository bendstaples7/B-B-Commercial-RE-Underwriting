"""add loading column to analysis_session

Revision ID: fd5451087f07
Revises: f6g7h8i9j0k1
Create Date: 2026-05-08 09:40:25.005545

Rewritten to guarded, idempotent raw SQL (no ``batch_alter_table``).

The original implementation used ``batch_alter_table`` with ``try/except``
guards around ``drop_constraint`` / ``drop_index``.  That pattern is broken on
PostgreSQL: inside a ``batch_alter_table`` block the operations are *buffered*
and only executed when the ``with`` block exits, so the ``try/except`` around
each ``batch_op.*`` call never catches the execution error.  On a fresh
database — where the clean-baseline revisions (``267725fe7017`` /
``a2b3c4d5e6f7``) have already dropped the legacy ``*_key`` UNIQUE constraints
and renamed ``idx_*`` indexes to ``ix_*`` — the buffered ``DROP CONSTRAINT`` /
``DROP INDEX`` statements referenced objects that no longer exist and aborted
the whole upgrade (``constraint ... does not exist``).

This rewrite performs the same end-state transformation using raw
``op.execute`` statements with ``IF EXISTS`` / ``IF NOT EXISTS`` guards, so the
revision is a safe no-op regardless of whether the indexes/constraints were
already normalised by an earlier revision.  The revision id and down_revision
pointer are unchanged, so the production chain is preserved.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'fd5451087f07'
down_revision = 'f6g7h8i9j0k1'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # analysis_sessions: add `loading`, drop legacy UNIQUE constraint,
    # normalise idx_* -> ix_* (unique on session_id).
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE analysis_sessions "
        "ADD COLUMN IF NOT EXISTS loading BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE analysis_sessions DROP CONSTRAINT IF EXISTS analysis_sessions_session_id_key")
    op.execute("DROP INDEX IF EXISTS idx_analysis_sessions_session_id")
    op.execute("DROP INDEX IF EXISTS idx_analysis_sessions_user_id")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_analysis_sessions_session_id ON analysis_sessions(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_sessions_user_id ON analysis_sessions(user_id)")

    # ------------------------------------------------------------------
    # leads: normalise lead_category index, drop legacy condo index.
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_leads_lead_category")
    op.execute("DROP INDEX IF EXISTS ix_leads_condo_analysis_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_leads_lead_category ON leads(lead_category)")

    # ------------------------------------------------------------------
    # comparable_sales
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_comparable_sales_address")
    op.execute("DROP INDEX IF EXISTS idx_comparable_sales_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_comparable_sales_address ON comparable_sales(address)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_comparable_sales_session_id ON comparable_sales(session_id)")

    # ------------------------------------------------------------------
    # comparable_valuations
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_comparable_valuations_valuation_result_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_comparable_valuations_valuation_result_id ON comparable_valuations(valuation_result_id)")

    # ------------------------------------------------------------------
    # property_facts
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_property_facts_address")
    op.execute("DROP INDEX IF EXISTS idx_property_facts_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_facts_address ON property_facts(address)")

    # ------------------------------------------------------------------
    # ranked_comparables
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_ranked_comparables_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ranked_comparables_session_id ON ranked_comparables(session_id)")

    # ------------------------------------------------------------------
    # scenarios
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_scenarios_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_scenarios_session_id ON scenarios(session_id)")

    # ------------------------------------------------------------------
    # valuation_results: drop legacy UNIQUE constraint, unique ix on session_id.
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_valuation_results_session_id")
    op.execute("ALTER TABLE valuation_results DROP CONSTRAINT IF EXISTS valuation_results_session_id_key")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_valuation_results_session_id ON valuation_results(session_id)")


def downgrade():
    # Reverse: restore idx_* indexes and legacy UNIQUE constraints, drop `loading`.
    # All statements are guarded so the downgrade is idempotent.

    # valuation_results
    op.execute("DROP INDEX IF EXISTS ix_valuation_results_session_id")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'valuation_results_session_id_key') THEN
                ALTER TABLE valuation_results ADD CONSTRAINT valuation_results_session_id_key UNIQUE (session_id);
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_valuation_results_session_id ON valuation_results(session_id)")

    # scenarios
    op.execute("DROP INDEX IF EXISTS ix_scenarios_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_session_id ON scenarios(session_id)")

    # ranked_comparables
    op.execute("DROP INDEX IF EXISTS ix_ranked_comparables_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ranked_comparables_session_id ON ranked_comparables(session_id)")

    # property_facts
    op.execute("DROP INDEX IF EXISTS ix_property_facts_address")
    op.execute("CREATE INDEX IF NOT EXISTS idx_property_facts_session_id ON property_facts(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_property_facts_address ON property_facts(address)")

    # comparable_valuations
    op.execute("DROP INDEX IF EXISTS ix_comparable_valuations_valuation_result_id")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_valuations_valuation_result_id ON comparable_valuations(valuation_result_id)")

    # comparable_sales
    op.execute("DROP INDEX IF EXISTS ix_comparable_sales_session_id")
    op.execute("DROP INDEX IF EXISTS ix_comparable_sales_address")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_sales_session_id ON comparable_sales(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_sales_address ON comparable_sales(address)")

    # leads
    op.execute("DROP INDEX IF EXISTS ix_leads_lead_category")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_lead_category ON leads(lead_category)")
    # Restore the condo-analysis index that upgrade() dropped, so the earlier
    # condo-filter migration's downgrade can drop it again (round-trip symmetry).
    op.execute("CREATE INDEX IF NOT EXISTS ix_leads_condo_analysis_id ON leads(condo_analysis_id)")

    # analysis_sessions
    op.execute("DROP INDEX IF EXISTS ix_analysis_sessions_user_id")
    op.execute("DROP INDEX IF EXISTS ix_analysis_sessions_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sessions_user_id ON analysis_sessions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sessions_session_id ON analysis_sessions(session_id)")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'analysis_sessions_session_id_key') THEN
                ALTER TABLE analysis_sessions ADD CONSTRAINT analysis_sessions_session_id_key UNIQUE (session_id);
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE analysis_sessions DROP COLUMN IF EXISTS loading")
