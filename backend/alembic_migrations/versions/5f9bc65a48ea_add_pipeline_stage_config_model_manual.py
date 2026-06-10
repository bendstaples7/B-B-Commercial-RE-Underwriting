"""Add Pipeline Stage Config model (manual)

Revision ID: 5f9bc65a48ea
Revises: q7r8s9t0u1v2
Create Date: 2026-05-23 14:17:55.795736

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '5f9bc65a48ea'
down_revision = 'q7r8s9t0u1v2'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_stage_configs (
            id SERIAL PRIMARY KEY,
            stage_name VARCHAR(255) NOT NULL UNIQUE,
            "order" INTEGER NOT NULL UNIQUE,
            weight NUMERIC(10, 2) NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS pipeline_stage_configs")