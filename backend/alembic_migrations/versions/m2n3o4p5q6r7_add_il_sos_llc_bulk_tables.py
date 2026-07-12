"""Illinois SOS LLC bulk entity / manager / agent tables.

Revision ID: m2n3o4p5q6r7
Revises: l1m2n3o4p5q6
Create Date: 2026-07-12

Free Business Data Transparency Act dumps (llcallnam/mgr/agt/mst) loaded
locally for Illinois LLC entity resolution.
"""
from alembic import op

revision = 'm2n3o4p5q6r7'
down_revision = 'l1m2n3o4p5q6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS il_sos_llc_entities (
            file_number VARCHAR(8) PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            normalized_name VARCHAR(200) NOT NULL,
            status_code VARCHAR(2),
            management_type VARCHAR(1),
            juris_organized VARCHAR(2),
            imported_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_il_sos_llc_entities_normalized_name
        ON il_sos_llc_entities (normalized_name)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS il_sos_llc_managers (
            id SERIAL PRIMARY KEY,
            file_number VARCHAR(8) NOT NULL
                REFERENCES il_sos_llc_entities(file_number) ON DELETE CASCADE,
            mm_name VARCHAR(120) NOT NULL,
            mm_street VARCHAR(60),
            mm_city VARCHAR(40),
            mm_juris VARCHAR(2),
            mm_zip VARCHAR(10),
            mm_file_date VARCHAR(8),
            mm_type_code VARCHAR(1),
            is_company BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_il_sos_llc_managers_file_number
        ON il_sos_llc_managers (file_number)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS il_sos_llc_agents (
            file_number VARCHAR(8) PRIMARY KEY
                REFERENCES il_sos_llc_entities(file_number) ON DELETE CASCADE,
            agent_name VARCHAR(120) NOT NULL,
            agent_street VARCHAR(60),
            agent_city VARCHAR(40),
            agent_zip VARCHAR(10),
            agent_code VARCHAR(1)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS il_sos_import_runs (
            id SERIAL PRIMARY KEY,
            source VARCHAR(100) NOT NULL,
            status VARCHAR(40) NOT NULL,
            started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            finished_at TIMESTAMP WITHOUT TIME ZONE,
            row_counts JSONB,
            error TEXT
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS il_sos_import_runs")
    op.execute("DROP TABLE IF EXISTS il_sos_llc_agents")
    op.execute("DROP INDEX IF EXISTS ix_il_sos_llc_managers_file_number")
    op.execute("DROP TABLE IF EXISTS il_sos_llc_managers")
    op.execute("DROP INDEX IF EXISTS ix_il_sos_llc_entities_normalized_name")
    op.execute("DROP TABLE IF EXISTS il_sos_llc_entities")
