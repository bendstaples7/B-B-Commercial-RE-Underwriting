"""Add nonprofit org_type and IRS EO BMF lookup table.

Revision ID: o6p7q8r9s0t1
Revises: n3o4p5q6r7s8
Create Date: 2026-07-12

Supports entity/nonprofit mail deprioritization: classify organizations as
nonprofit and look up IRS Exempt Organizations Business Master File rows.
"""
from alembic import op


revision = 'o6p7q8r9s0t1'
down_revision = 'n3o4p5q6r7s8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE org_type_enum ADD VALUE IF NOT EXISTS 'nonprofit'"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS irs_eo_organizations (
            ein VARCHAR(9) PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            normalized_name VARCHAR(200) NOT NULL,
            city VARCHAR(64),
            state VARCHAR(2),
            ntee_cd VARCHAR(10),
            subsection VARCHAR(4),
            status VARCHAR(2),
            imported_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_irs_eo_organizations_normalized_name
        ON irs_eo_organizations (normalized_name)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_irs_eo_organizations_state_normalized_name
        ON irs_eo_organizations (state, normalized_name)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_irs_eo_organizations_state_normalized_name")
    op.execute("DROP INDEX IF EXISTS ix_irs_eo_organizations_normalized_name")
    op.execute("DROP TABLE IF EXISTS irs_eo_organizations")
    # PostgreSQL cannot easily remove enum values; leave nonprofit in place.
