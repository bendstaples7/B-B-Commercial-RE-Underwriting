"""baseline schema

Revision ID: 267725fe7017
Revises: 
Create Date: 2026-04-30 16:54:10.117775

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '267725fe7017'
down_revision = '000000000000'
branch_labels = None
depends_on = None


def upgrade():
    # The initial schema (analysis pipeline + lead management tables) is now
    # created by the 000000000000_initial_schema migration which runs first.
    # This migration renames enum types and normalises column types to match
    # what SQLAlchemy's model layer expects.

    # Target enum types: create if not already present (idempotent guard).
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
            CREATE TYPE propertytype AS ENUM ('SINGLE_FAMILY', 'MULTI_FAMILY', 'COMMERCIAL');
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

    # ---------------------------------------------------------------------------
    # analysis_sessions.current_step: workflow_step -> workflowstep
    # Guard: only convert if column is still using the old 'workflow_step' type.
    # On a fresh DB (task 3.1 already created it as workflowstep) this is a no-op.
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'analysis_sessions'
                  AND column_name = 'current_step'
                  AND udt_name = 'workflow_step'
            ) THEN
                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step DROP DEFAULT;
                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step TYPE workflowstep
                    USING current_step::text::workflowstep;
                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step SET DEFAULT 'PROPERTY_FACTS'::workflowstep;
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # comparable_sales enum renames
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'property_type'
                  AND udt_name = 'property_type'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN property_type TYPE propertytype
                    USING upper(property_type::text)::propertytype;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'construction_type'
                  AND udt_name = 'construction_type'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN construction_type TYPE constructiontype
                    USING upper(construction_type::text)::constructiontype;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'interior_condition'
                  AND udt_name = 'interior_condition'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN interior_condition TYPE interiorcondition
                    USING upper(interior_condition::text)::interiorcondition;
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # property_facts enum renames
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'property_facts'
                  AND column_name = 'property_type'
                  AND udt_name = 'property_type'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN property_type TYPE propertytype
                    USING upper(property_type::text)::propertytype;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'property_facts'
                  AND column_name = 'construction_type'
                  AND udt_name = 'construction_type'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN construction_type TYPE constructiontype
                    USING upper(construction_type::text)::constructiontype;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'property_facts'
                  AND column_name = 'interior_condition'
                  AND udt_name = 'interior_condition'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN interior_condition TYPE interiorcondition
                    USING upper(interior_condition::text)::interiorcondition;
            END IF;
        END $$;
    """)

    # property_facts.user_modified_fields: TEXT[] -> JSON
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'property_facts'
                  AND column_name = 'user_modified_fields'
                  AND data_type = 'ARRAY'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN user_modified_fields TYPE JSON
                    USING array_to_json(user_modified_fields);
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # scenarios.scenario_type: scenario_type -> scenariotype
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'scenarios'
                  AND column_name = 'scenario_type'
                  AND udt_name = 'scenario_type'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN scenario_type TYPE scenariotype
                    USING upper(scenario_type::text)::scenariotype;
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # JSONB -> JSON and ARRAY -> JSON conversions
    # Guard each on data_type so they are no-ops when already JSON.
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'buy_hold_scenarios'
                  AND column_name = 'capital_structures'
                  AND data_type = 'jsonb'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN capital_structures TYPE JSON
                    USING capital_structures::json;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'buy_hold_scenarios'
                  AND column_name = 'price_points'
                  AND data_type = 'jsonb'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN price_points TYPE JSON
                    USING price_points::json;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_valuations'
                  AND column_name = 'adjustments'
                  AND data_type = 'jsonb'
            ) THEN
                ALTER TABLE comparable_valuations
                    ALTER COLUMN adjustments TYPE JSON
                    USING adjustments::json;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'scenarios'
                  AND column_name = 'summary'
                  AND data_type = 'jsonb'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN summary TYPE JSON
                    USING summary::json;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'valuation_results'
                  AND column_name = 'all_valuations'
                  AND data_type = 'ARRAY'
            ) THEN
                ALTER TABLE valuation_results
                    ALTER COLUMN all_valuations TYPE JSON
                    USING array_to_json(all_valuations);
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'valuation_results'
                  AND column_name = 'key_drivers'
                  AND data_type = 'ARRAY'
            ) THEN
                ALTER TABLE valuation_results
                    ALTER COLUMN key_drivers TYPE JSON
                    USING array_to_json(key_drivers);
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # analysis_sessions: index/constraint normalisation
    # Replace batch_alter_table with guarded raw SQL.
    # ---------------------------------------------------------------------------
    op.execute("ALTER TABLE analysis_sessions DROP CONSTRAINT IF EXISTS analysis_sessions_session_id_key")
    op.execute("DROP INDEX IF EXISTS idx_analysis_sessions_session_id")
    op.execute("DROP INDEX IF EXISTS idx_analysis_sessions_user_id")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_analysis_sessions_session_id ON analysis_sessions(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_sessions_user_id ON analysis_sessions(user_id)")

    # ---------------------------------------------------------------------------
    # buy_hold_scenarios: NUMERIC -> Float
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'buy_hold_scenarios'
                  AND column_name = 'market_rent'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN market_rent TYPE FLOAT USING market_rent::float;
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # comparable_sales: NUMERIC -> Float + index normalisation
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'sale_price'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN sale_price TYPE FLOAT USING sale_price::float;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'bathrooms'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN bathrooms TYPE FLOAT USING bathrooms::float;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'distance_miles'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN distance_miles TYPE FLOAT USING distance_miles::float;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'latitude'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN latitude TYPE FLOAT USING latitude::float;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_sales'
                  AND column_name = 'longitude'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_sales
                    ALTER COLUMN longitude TYPE FLOAT USING longitude::float;
            END IF;
        END $$;
    """)
    op.execute("DROP INDEX IF EXISTS idx_comparable_sales_address")
    op.execute("DROP INDEX IF EXISTS idx_comparable_sales_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_comparable_sales_address ON comparable_sales(address)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_comparable_sales_session_id ON comparable_sales(session_id)")

    # ---------------------------------------------------------------------------
    # comparable_valuations: NUMERIC -> Float + index normalisation
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_valuations'
                  AND column_name = 'price_per_sqft'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_valuations
                    ALTER COLUMN price_per_sqft TYPE FLOAT USING price_per_sqft::float;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_valuations'
                  AND column_name = 'price_per_unit'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_valuations
                    ALTER COLUMN price_per_unit TYPE FLOAT USING price_per_unit::float;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_valuations'
                  AND column_name = 'price_per_bedroom'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_valuations
                    ALTER COLUMN price_per_bedroom TYPE FLOAT USING price_per_bedroom::float;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_valuations'
                  AND column_name = 'adjusted_value'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE comparable_valuations
                    ALTER COLUMN adjusted_value TYPE FLOAT USING adjusted_value::float;
            END IF;
        END $$;
    """)
    op.execute("DROP INDEX IF EXISTS idx_comparable_valuations_valuation_result_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_comparable_valuations_valuation_result_id ON comparable_valuations(valuation_result_id)")

    # ---------------------------------------------------------------------------
    # fix_flip_scenarios: NUMERIC -> Float
    # ---------------------------------------------------------------------------
    for col in [
        'acquisition_cost', 'renovation_cost', 'holding_costs', 'financing_costs',
        'closing_costs', 'total_cost', 'exit_value', 'net_profit', 'roi',
    ]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'fix_flip_scenarios'
                      AND column_name = '{col}'
                      AND data_type = 'numeric'
                ) THEN
                    ALTER TABLE fix_flip_scenarios
                        ALTER COLUMN {col} TYPE FLOAT USING {col}::float;
                END IF;
            END $$;
        """)

    # ---------------------------------------------------------------------------
    # property_facts: NUMERIC -> Float + index normalisation
    # ---------------------------------------------------------------------------
    for col in ['bathrooms', 'last_sale_price', 'assessed_value', 'annual_taxes', 'latitude', 'longitude']:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'property_facts'
                      AND column_name = '{col}'
                      AND data_type = 'numeric'
                ) THEN
                    ALTER TABLE property_facts
                        ALTER COLUMN {col} TYPE FLOAT USING {col}::float;
                END IF;
            END $$;
        """)
    op.execute("DROP INDEX IF EXISTS idx_property_facts_address")
    op.execute("DROP INDEX IF EXISTS idx_property_facts_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_facts_address ON property_facts(address)")

    # ---------------------------------------------------------------------------
    # ranked_comparables: NUMERIC -> Float + index normalisation
    # ---------------------------------------------------------------------------
    for col in [
        'total_score', 'recency_score', 'proximity_score', 'units_score',
        'beds_baths_score', 'sqft_score', 'construction_score', 'interior_score',
    ]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'ranked_comparables'
                      AND column_name = '{col}'
                      AND data_type = 'numeric'
                ) THEN
                    ALTER TABLE ranked_comparables
                        ALTER COLUMN {col} TYPE FLOAT USING {col}::float;
                END IF;
            END $$;
        """)
    op.execute("DROP INDEX IF EXISTS idx_ranked_comparables_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ranked_comparables_session_id ON ranked_comparables(session_id)")

    # ---------------------------------------------------------------------------
    # scenarios: NUMERIC -> Float + index normalisation
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'scenarios'
                  AND column_name = 'purchase_price'
                  AND data_type = 'numeric'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN purchase_price TYPE FLOAT USING purchase_price::float;
            END IF;
        END $$;
    """)
    op.execute("DROP INDEX IF EXISTS idx_scenarios_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_scenarios_session_id ON scenarios(session_id)")

    # ---------------------------------------------------------------------------
    # valuation_results: NUMERIC -> Float + index/constraint normalisation
    # ---------------------------------------------------------------------------
    for col in ['conservative_arv', 'likely_arv', 'aggressive_arv']:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'valuation_results'
                      AND column_name = '{col}'
                      AND data_type = 'numeric'
                ) THEN
                    ALTER TABLE valuation_results
                        ALTER COLUMN {col} TYPE FLOAT USING {col}::float;
                END IF;
            END $$;
        """)
    op.execute("DROP INDEX IF EXISTS idx_valuation_results_session_id")
    op.execute("ALTER TABLE valuation_results DROP CONSTRAINT IF EXISTS valuation_results_session_id_key")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_valuation_results_session_id ON valuation_results(session_id)")

    # ---------------------------------------------------------------------------
    # wholesale_scenarios: NUMERIC -> Float
    # ---------------------------------------------------------------------------
    for col in ['mao', 'contract_price', 'assignment_fee_low', 'assignment_fee_high', 'estimated_repairs']:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'wholesale_scenarios'
                      AND column_name = '{col}'
                      AND data_type = 'numeric'
                ) THEN
                    ALTER TABLE wholesale_scenarios
                        ALTER COLUMN {col} TYPE FLOAT USING {col}::float;
                END IF;
            END $$;
        """)


def downgrade():
    # Reverse each operation with guards so the downgrade is also idempotent.
    # Float -> NUMERIC casts are lossless for the precisions involved.

    # ---------------------------------------------------------------------------
    # wholesale_scenarios: Float -> NUMERIC
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'wholesale_scenarios'
                  AND column_name = 'mao'
                  AND data_type = 'double precision'
            ) THEN
                ALTER TABLE wholesale_scenarios
                    ALTER COLUMN mao TYPE NUMERIC(12,2) USING mao::numeric;
                ALTER TABLE wholesale_scenarios
                    ALTER COLUMN contract_price TYPE NUMERIC(12,2) USING contract_price::numeric;
                ALTER TABLE wholesale_scenarios
                    ALTER COLUMN assignment_fee_low TYPE NUMERIC(12,2) USING assignment_fee_low::numeric;
                ALTER TABLE wholesale_scenarios
                    ALTER COLUMN assignment_fee_high TYPE NUMERIC(12,2) USING assignment_fee_high::numeric;
                ALTER TABLE wholesale_scenarios
                    ALTER COLUMN estimated_repairs TYPE NUMERIC(12,2) USING estimated_repairs::numeric;
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # valuation_results: Float -> NUMERIC, index/constraint reversal
    # ---------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_valuation_results_session_id")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'valuation_results_session_id_key'
            ) THEN
                ALTER TABLE valuation_results
                    ADD CONSTRAINT valuation_results_session_id_key UNIQUE (session_id);
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_valuation_results_session_id ON valuation_results(session_id)")
    for col, prec in [('conservative_arv', '(12,2)'), ('likely_arv', '(12,2)'), ('aggressive_arv', '(12,2)')]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'valuation_results'
                      AND column_name = '{col}'
                      AND data_type = 'double precision'
                ) THEN
                    ALTER TABLE valuation_results
                        ALTER COLUMN {col} TYPE NUMERIC{prec} USING {col}::numeric;
                END IF;
            END $$;
        """)
    # JSON -> ARRAY reversal for valuation_results
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'valuation_results'
                  AND column_name = 'all_valuations'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE valuation_results
                    ALTER COLUMN all_valuations TYPE NUMERIC(12,2)[]
                    USING ARRAY(SELECT jsonb_array_elements_text(all_valuations::jsonb)::numeric);
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'valuation_results'
                  AND column_name = 'key_drivers'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE valuation_results
                    ALTER COLUMN key_drivers TYPE TEXT[]
                    USING ARRAY(SELECT jsonb_array_elements_text(key_drivers::jsonb));
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # scenarios: NUMERIC reversal, JSON -> JSONB, index swap
    # ---------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_scenarios_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_session_id ON scenarios(session_id)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'scenarios'
                  AND column_name = 'purchase_price'
                  AND data_type = 'double precision'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN purchase_price TYPE NUMERIC(12,2) USING purchase_price::numeric;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'scenarios'
                  AND column_name = 'summary'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN summary TYPE JSONB USING summary::jsonb;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'scenarios'
                  AND column_name = 'scenario_type'
                  AND udt_name = 'scenariotype'
            ) THEN
                ALTER TABLE scenarios
                    ALTER COLUMN scenario_type TYPE TEXT USING lower(scenario_type::text);
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # ranked_comparables: Float -> NUMERIC, index swap
    # ---------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_ranked_comparables_session_id")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ranked_comparables_session_id ON ranked_comparables(session_id)")
    for col in [
        'total_score', 'recency_score', 'proximity_score', 'units_score',
        'beds_baths_score', 'sqft_score', 'construction_score', 'interior_score',
    ]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'ranked_comparables'
                      AND column_name = '{col}'
                      AND data_type = 'double precision'
                ) THEN
                    ALTER TABLE ranked_comparables
                        ALTER COLUMN {col} TYPE NUMERIC(5,2) USING {col}::numeric;
                END IF;
            END $$;
        """)

    # ---------------------------------------------------------------------------
    # property_facts: Float -> NUMERIC, JSON -> ARRAY, enum reversal, index swap
    # ---------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_property_facts_address")
    op.execute("CREATE INDEX IF NOT EXISTS idx_property_facts_address ON property_facts(address)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_property_facts_session_id ON property_facts(session_id)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'property_facts'
                  AND column_name = 'user_modified_fields'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE property_facts
                    ALTER COLUMN user_modified_fields TYPE TEXT[]
                    USING ARRAY(SELECT jsonb_array_elements_text(user_modified_fields::jsonb));
            END IF;
        END $$;
    """)
    for col, prec in [
        ('bathrooms', '(3,1)'), ('last_sale_price', '(12,2)'), ('assessed_value', '(12,2)'),
        ('annual_taxes', '(10,2)'), ('latitude', '(10,8)'), ('longitude', '(11,8)'),
    ]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'property_facts'
                      AND column_name = '{col}'
                      AND data_type = 'double precision'
                ) THEN
                    ALTER TABLE property_facts
                        ALTER COLUMN {col} TYPE NUMERIC{prec} USING {col}::numeric;
                END IF;
            END $$;
        """)

    # ---------------------------------------------------------------------------
    # fix_flip_scenarios: Float -> NUMERIC
    # ---------------------------------------------------------------------------
    for col, prec in [
        ('acquisition_cost', '(12,2)'), ('renovation_cost', '(12,2)'), ('holding_costs', '(12,2)'),
        ('financing_costs', '(12,2)'), ('closing_costs', '(12,2)'), ('total_cost', '(12,2)'),
        ('exit_value', '(12,2)'), ('net_profit', '(12,2)'), ('roi', '(5,2)'),
    ]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'fix_flip_scenarios'
                      AND column_name = '{col}'
                      AND data_type = 'double precision'
                ) THEN
                    ALTER TABLE fix_flip_scenarios
                        ALTER COLUMN {col} TYPE NUMERIC{prec} USING {col}::numeric;
                END IF;
            END $$;
        """)

    # ---------------------------------------------------------------------------
    # comparable_valuations: Float -> NUMERIC, JSON -> JSONB, index swap
    # ---------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_comparable_valuations_valuation_result_id")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_valuations_valuation_result_id ON comparable_valuations(valuation_result_id)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'comparable_valuations'
                  AND column_name = 'adjustments'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE comparable_valuations
                    ALTER COLUMN adjustments TYPE JSONB USING adjustments::jsonb;
            END IF;
        END $$;
    """)
    for col, prec in [
        ('price_per_sqft', '(10,2)'), ('price_per_unit', '(12,2)'),
        ('price_per_bedroom', '(12,2)'), ('adjusted_value', '(12,2)'),
    ]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'comparable_valuations'
                      AND column_name = '{col}'
                      AND data_type = 'double precision'
                ) THEN
                    ALTER TABLE comparable_valuations
                        ALTER COLUMN {col} TYPE NUMERIC{prec} USING {col}::numeric;
                END IF;
            END $$;
        """)

    # ---------------------------------------------------------------------------
    # comparable_sales: Float -> NUMERIC, enum reversal, index swap
    # ---------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_comparable_sales_session_id")
    op.execute("DROP INDEX IF EXISTS ix_comparable_sales_address")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_sales_session_id ON comparable_sales(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_sales_address ON comparable_sales(address)")
    for col, prec in [
        ('sale_price', '(12,2)'), ('bathrooms', '(3,1)'), ('distance_miles', '(5,2)'),
        ('latitude', '(10,8)'), ('longitude', '(11,8)'),
    ]:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'comparable_sales'
                      AND column_name = '{col}'
                      AND data_type = 'double precision'
                ) THEN
                    ALTER TABLE comparable_sales
                        ALTER COLUMN {col} TYPE NUMERIC{prec} USING {col}::numeric;
                END IF;
            END $$;
        """)

    # ---------------------------------------------------------------------------
    # buy_hold_scenarios: Float -> NUMERIC, JSON -> JSONB
    # ---------------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'buy_hold_scenarios'
                  AND column_name = 'market_rent'
                  AND data_type = 'double precision'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN market_rent TYPE NUMERIC(10,2) USING market_rent::numeric;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'buy_hold_scenarios'
                  AND column_name = 'capital_structures'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN capital_structures TYPE JSONB USING capital_structures::jsonb;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'buy_hold_scenarios'
                  AND column_name = 'price_points'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE buy_hold_scenarios
                    ALTER COLUMN price_points TYPE JSONB USING price_points::jsonb;
            END IF;
        END $$;
    """)

    # ---------------------------------------------------------------------------
    # analysis_sessions: index/constraint reversal, current_step enum reversal
    # ---------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_analysis_sessions_session_id")
    op.execute("DROP INDEX IF EXISTS ix_analysis_sessions_user_id")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'analysis_sessions_session_id_key'
            ) THEN
                ALTER TABLE analysis_sessions
                    ADD CONSTRAINT analysis_sessions_session_id_key UNIQUE (session_id);
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sessions_session_id ON analysis_sessions(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sessions_user_id ON analysis_sessions(user_id)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'analysis_sessions'
                  AND column_name = 'current_step'
                  AND udt_name = 'workflowstep'
            ) THEN
                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step DROP DEFAULT;
                ALTER TABLE analysis_sessions
                    ALTER COLUMN current_step TYPE TEXT USING current_step::text;
            END IF;
        END $$;
    """)
