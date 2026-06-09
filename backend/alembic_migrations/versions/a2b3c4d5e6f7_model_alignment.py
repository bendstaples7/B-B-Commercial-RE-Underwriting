"""Model-alignment: converge enum and column types to model-aligned form.

Revision ID: a2b3c4d5e6f7
Revises: z5a6b7c8d9e0
Create Date: 2026-06-12 00:00:00.000000

Purpose
-------
``000000000000_initial_schema`` creates *legacy* enum types (lowercase names
and values: ``property_type``, ``construction_type``, ``interior_condition``,
``workflow_step``, ``scenario_type``) because those names matched the raw SQL
files that were applied outside Alembic.

The SQLAlchemy models expect *model-aligned* enum types (PascalCase names,
UPPER values: ``propertytype``, ``constructiontype``, ``interiorcondition``,
``workflowstep``, ``scenariotype``).

``267725fe7017_baseline_schema`` bridged the two, but uses ``batch_alter_table``
which fails on fresh PostgreSQL databases.  This revision replaces that role
with guarded, idempotent raw SQL:

- Creates the model-aligned enum types (guarded by EXCEPTION WHEN
  duplicate_object so fresh AND already-migrated databases are safe).
- Converts every enum column to the model-aligned type, but ONLY when the
  column still uses the old type (checked via information_schema.columns /
  pg_type).  If the column already uses the new type (e.g. after
  267725fe7017 ran on an existing DB) the block is a no-op.
- Converts JSONB/ARRAY columns to JSON where still needed, guarded by the
  same information_schema check.
- Renames legacy ``idx_*`` indexes to ``ix_*`` format, guarded with
  IF NOT EXISTS / IF EXISTS.

Fresh databases and existing databases (already at the 267725fe7017 state)
both converge to the same schema after this revision runs.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # Step 1: Ensure model-aligned enum types exist.
    # The DO $$ ... EXCEPTION WHEN duplicate_object block is a no-op when
    # the type was already created by 267725fe7017 on an existing database.
    # On a fresh database the types are created here for the first time.
    # ------------------------------------------------------------------

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE workflowstep AS ENUM (
                'PROPERTY_FACTS', 'COMPARABLE_SEARCH', 'COMPARABLE_REVIEW',
                'WEIGHTED_SCORING', 'VALUATION_MODELS', 'REPORT_GENERATION'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE propertytype AS ENUM (
                'SINGLE_FAMILY', 'MULTI_FAMILY', 'COMMERCIAL'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE constructiontype AS ENUM ('FRAME', 'BRICK', 'MASONRY');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE interiorcondition AS ENUM (
                'NEEDS_GUT', 'POOR', 'AVERAGE', 'NEW_RENO', 'HIGH_END'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE scenariotype AS ENUM ('WHOLESALE', 'FIX_FLIP', 'BUY_HOLD');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Step 2: Convert enum columns to model-aligned types.
    # Each block checks information_schema.columns.udt_name to see if the
    # column still uses the old (legacy) type.  If so, it converts.  If
    # the column already uses the new type the block is a no-op.
    # ------------------------------------------------------------------

    # analysis_sessions.current_step: workflow_step → workflowstep
    # Must drop the server_default first because PostgreSQL validates the
    # default expression against the new type before completing ALTER COLUMN.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'analysis_sessions'
                  AND column_name = 'current_step'
                  AND udt_name = 'workflow_step'
            ) THEN
                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step DROP DEFAULT;

                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step TYPE workflowstep
                    USING current_step::text::workflowstep;

                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step
                    SET DEFAULT 'PROPERTY_FACTS'::workflowstep;
            END IF;
        END $$;
    """)

    # comparable_sales.property_type: property_type → propertytype
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'comparable_sales'
                  AND column_name = 'property_type'
                  AND udt_name = 'property_type'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN property_type TYPE propertytype
                    USING upper(property_type::text)::propertytype;
            END IF;
        END $$;
    """)

    # comparable_sales.construction_type: construction_type → constructiontype
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'comparable_sales'
                  AND column_name = 'construction_type'
                  AND udt_name = 'construction_type'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN construction_type TYPE constructiontype
                    USING upper(construction_type::text)::constructiontype;
            END IF;
        END $$;
    """)

    # comparable_sales.interior_condition: interior_condition → interiorcondition
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'comparable_sales'
                  AND column_name = 'interior_condition'
                  AND udt_name = 'interior_condition'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN interior_condition TYPE interiorcondition
                    USING upper(interior_condition::text)::interiorcondition;
            END IF;
        END $$;
    """)

    # property_facts.property_type: property_type → propertytype
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'property_facts'
                  AND column_name = 'property_type'
                  AND udt_name = 'property_type'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN property_type TYPE propertytype
                    USING upper(property_type::text)::propertytype;
            END IF;
        END $$;
    """)

    # property_facts.construction_type: construction_type → constructiontype
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'property_facts'
                  AND column_name = 'construction_type'
                  AND udt_name = 'construction_type'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN construction_type TYPE constructiontype
                    USING upper(construction_type::text)::constructiontype;
            END IF;
        END $$;
    """)

    # property_facts.interior_condition: interior_condition → interiorcondition
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'property_facts'
                  AND column_name = 'interior_condition'
                  AND udt_name = 'interior_condition'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN interior_condition TYPE interiorcondition
                    USING upper(interior_condition::text)::interiorcondition;
            END IF;
        END $$;
    """)

    # property_facts.user_modified_fields: TEXT[] → JSON
    # Check data_type = 'ARRAY' (TEXT[] shows as 'ARRAY' in information_schema).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'property_facts'
                  AND column_name = 'user_modified_fields'
                  AND data_type = 'ARRAY'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN user_modified_fields TYPE JSON
                    USING array_to_json(user_modified_fields);
            END IF;
        END $$;
    """)

    # scenarios.scenario_type: scenario_type → scenariotype
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'scenarios'
                  AND column_name = 'scenario_type'
                  AND udt_name = 'scenario_type'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN scenario_type TYPE scenariotype
                    USING upper(scenario_type::text)::scenariotype;
            END IF;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Step 3: Convert JSONB/ARRAY columns to JSON.
    # Guarded by information_schema.columns data_type checks.
    # ------------------------------------------------------------------

    # buy_hold_scenarios.capital_structures: JSONB → JSON
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'buy_hold_scenarios'
                  AND column_name = 'capital_structures'
                  AND udt_name = 'jsonb'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN capital_structures TYPE JSON
                    USING capital_structures::json;
            END IF;
        END $$;
    """)

    # buy_hold_scenarios.price_points: JSONB → JSON
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'buy_hold_scenarios'
                  AND column_name = 'price_points'
                  AND udt_name = 'jsonb'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN price_points TYPE JSON
                    USING price_points::json;
            END IF;
        END $$;
    """)

    # comparable_valuations.adjustments: JSONB → JSON
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'comparable_valuations'
                  AND column_name = 'adjustments'
                  AND udt_name = 'jsonb'
            ) THEN
                ALTER TABLE comparable_valuations
                    ALTER COLUMN adjustments TYPE JSON
                    USING adjustments::json;
            END IF;
        END $$;
    """)

    # scenarios.summary: JSONB → JSON
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'scenarios'
                  AND column_name = 'summary'
                  AND udt_name = 'jsonb'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN summary TYPE JSON
                    USING summary::json;
            END IF;
        END $$;
    """)

    # valuation_results.all_valuations: ARRAY → JSON
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'valuation_results'
                  AND column_name = 'all_valuations'
                  AND data_type = 'ARRAY'
            ) THEN
                ALTER TABLE valuation_results
                    ALTER COLUMN all_valuations TYPE JSON
                    USING array_to_json(all_valuations);
            END IF;
        END $$;
    """)

    # valuation_results.key_drivers: ARRAY → JSON
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'valuation_results'
                  AND column_name = 'key_drivers'
                  AND data_type = 'ARRAY'
            ) THEN
                ALTER TABLE valuation_results
                    ALTER COLUMN key_drivers TYPE JSON
                    USING array_to_json(key_drivers);
            END IF;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Step 4: Rename idx_* indexes to ix_* format.
    # Uses IF NOT EXISTS / IF EXISTS guards so the rename is a no-op when
    # the ix_* index already exists (267725fe7017 already did the rename).
    # ------------------------------------------------------------------

    # analysis_sessions
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'ix_analysis_sessions_session_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'idx_analysis_sessions_session_id'
            ) THEN
                ALTER INDEX idx_analysis_sessions_session_id
                    RENAME TO ix_analysis_sessions_session_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'ix_analysis_sessions_user_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'idx_analysis_sessions_user_id'
            ) THEN
                ALTER INDEX idx_analysis_sessions_user_id
                    RENAME TO ix_analysis_sessions_user_id;
            END IF;
        END $$;
    """)

    # comparable_sales
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'ix_comparable_sales_address'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'idx_comparable_sales_address'
            ) THEN
                ALTER INDEX idx_comparable_sales_address
                    RENAME TO ix_comparable_sales_address;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'ix_comparable_sales_session_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'idx_comparable_sales_session_id'
            ) THEN
                ALTER INDEX idx_comparable_sales_session_id
                    RENAME TO ix_comparable_sales_session_id;
            END IF;
        END $$;
    """)

    # comparable_valuations
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_valuations'
                  AND indexname = 'ix_comparable_valuations_valuation_result_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_valuations'
                  AND indexname = 'idx_comparable_valuations_valuation_result_id'
            ) THEN
                ALTER INDEX idx_comparable_valuations_valuation_result_id
                    RENAME TO ix_comparable_valuations_valuation_result_id;
            END IF;
        END $$;
    """)

    # property_facts
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'ix_property_facts_address'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'idx_property_facts_address'
            ) THEN
                ALTER INDEX idx_property_facts_address
                    RENAME TO ix_property_facts_address;
            END IF;
        END $$;
    """)

    # ranked_comparables
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'ranked_comparables'
                  AND indexname = 'ix_ranked_comparables_session_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'ranked_comparables'
                  AND indexname = 'idx_ranked_comparables_session_id'
            ) THEN
                ALTER INDEX idx_ranked_comparables_session_id
                    RENAME TO ix_ranked_comparables_session_id;
            END IF;
        END $$;
    """)

    # scenarios
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'scenarios'
                  AND indexname = 'ix_scenarios_session_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'scenarios'
                  AND indexname = 'idx_scenarios_session_id'
            ) THEN
                ALTER INDEX idx_scenarios_session_id
                    RENAME TO ix_scenarios_session_id;
            END IF;
        END $$;
    """)

    # valuation_results
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'valuation_results'
                  AND indexname = 'ix_valuation_results_session_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'valuation_results'
                  AND indexname = 'idx_valuation_results_session_id'
            ) THEN
                ALTER INDEX idx_valuation_results_session_id
                    RENAME TO ix_valuation_results_session_id;
            END IF;
        END $$;
    """)

    # property_facts session_id index (also idx_ → ix_)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'ix_property_facts_session_id'
            ) AND EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'idx_property_facts_session_id'
            ) THEN
                ALTER INDEX idx_property_facts_session_id
                    RENAME TO ix_property_facts_session_id;
            END IF;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Step 5: Drop the unique constraint on analysis_sessions.session_id
    # and valuation_results.session_id that 267725fe7017 renamed, if the
    # old constraint name still exists (guarded).
    # ------------------------------------------------------------------

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'analysis_sessions'
                  AND constraint_name = 'analysis_sessions_session_id_key'
                  AND constraint_type = 'UNIQUE'
            ) THEN
                ALTER TABLE analysis_sessions
                    DROP CONSTRAINT analysis_sessions_session_id_key;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'ix_analysis_sessions_session_id'
            ) THEN
                CREATE UNIQUE INDEX ix_analysis_sessions_session_id
                    ON analysis_sessions(session_id);
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'valuation_results'
                  AND constraint_name = 'valuation_results_session_id_key'
                  AND constraint_type = 'UNIQUE'
            ) THEN
                ALTER TABLE valuation_results
                    DROP CONSTRAINT valuation_results_session_id_key;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'valuation_results'
                  AND indexname = 'ix_valuation_results_session_id'
            ) THEN
                CREATE UNIQUE INDEX ix_valuation_results_session_id
                    ON valuation_results(session_id);
            END IF;
        END $$;
    """)


def downgrade():
    # ------------------------------------------------------------------
    # Reverse the index renames: ix_* → idx_* where the ix_ version exists.
    # ------------------------------------------------------------------

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'ix_analysis_sessions_session_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'idx_analysis_sessions_session_id'
            ) THEN
                ALTER INDEX ix_analysis_sessions_session_id
                    RENAME TO idx_analysis_sessions_session_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'ix_analysis_sessions_user_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'analysis_sessions'
                  AND indexname = 'idx_analysis_sessions_user_id'
            ) THEN
                ALTER INDEX ix_analysis_sessions_user_id
                    RENAME TO idx_analysis_sessions_user_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'ix_comparable_sales_address'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'idx_comparable_sales_address'
            ) THEN
                ALTER INDEX ix_comparable_sales_address
                    RENAME TO idx_comparable_sales_address;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'ix_comparable_sales_session_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_sales'
                  AND indexname = 'idx_comparable_sales_session_id'
            ) THEN
                ALTER INDEX ix_comparable_sales_session_id
                    RENAME TO idx_comparable_sales_session_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_valuations'
                  AND indexname = 'ix_comparable_valuations_valuation_result_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'comparable_valuations'
                  AND indexname = 'idx_comparable_valuations_valuation_result_id'
            ) THEN
                ALTER INDEX ix_comparable_valuations_valuation_result_id
                    RENAME TO idx_comparable_valuations_valuation_result_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'ix_property_facts_address'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'idx_property_facts_address'
            ) THEN
                ALTER INDEX ix_property_facts_address
                    RENAME TO idx_property_facts_address;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'ix_property_facts_session_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'property_facts'
                  AND indexname = 'idx_property_facts_session_id'
            ) THEN
                ALTER INDEX ix_property_facts_session_id
                    RENAME TO idx_property_facts_session_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'ranked_comparables'
                  AND indexname = 'ix_ranked_comparables_session_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'ranked_comparables'
                  AND indexname = 'idx_ranked_comparables_session_id'
            ) THEN
                ALTER INDEX ix_ranked_comparables_session_id
                    RENAME TO idx_ranked_comparables_session_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'scenarios'
                  AND indexname = 'ix_scenarios_session_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'scenarios'
                  AND indexname = 'idx_scenarios_session_id'
            ) THEN
                ALTER INDEX ix_scenarios_session_id
                    RENAME TO idx_scenarios_session_id;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'valuation_results'
                  AND indexname = 'ix_valuation_results_session_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'valuation_results'
                  AND indexname = 'idx_valuation_results_session_id'
            ) THEN
                ALTER INDEX ix_valuation_results_session_id
                    RENAME TO idx_valuation_results_session_id;
            END IF;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Drop the model-aligned enum types IF no column references them.
    # Uses DROP TYPE IF EXISTS — safe as a no-op if already dropped.
    # Note: these types may still be referenced by columns on existing DBs
    # that were migrated by 267725fe7017.  The DROP will fail if columns
    # still use them; the DO block swallows that as a no-op.
    # ------------------------------------------------------------------

    op.execute("""
        DO $$
        BEGIN
            DROP TYPE IF EXISTS scenariotype;
        EXCEPTION WHEN dependent_objects_still_exist THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            DROP TYPE IF EXISTS interiorcondition;
        EXCEPTION WHEN dependent_objects_still_exist THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            DROP TYPE IF EXISTS constructiontype;
        EXCEPTION WHEN dependent_objects_still_exist THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            DROP TYPE IF EXISTS propertytype;
        EXCEPTION WHEN dependent_objects_still_exist THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            DROP TYPE IF EXISTS workflowstep;
        EXCEPTION WHEN dependent_objects_still_exist THEN NULL;
        END $$;
    """)
