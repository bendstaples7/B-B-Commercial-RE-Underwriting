"""Add deal_source_options for user-created Source dropdown values.

Revision ID: deal_src_20260924
Revises: mail_attr_20260919
Create Date: 2026-09-24

Lets Quick Add / Contact capture add sources like \"Facebook Ad\" without a
code deploy. Builtins stay in DEAL_SOURCE_OPTIONS; this table holds customs.
"""
from alembic import op

revision = 'deal_src_20260924'
down_revision = 'mail_attr_20260919'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deal_source_options (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            created_by VARCHAR(255),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_deal_source_options_name UNIQUE (name)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_deal_source_options_name_lower
        ON deal_source_options (lower(name))
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_deal_source_options_name_lower')
    op.execute('DROP TABLE IF EXISTS deal_source_options')
