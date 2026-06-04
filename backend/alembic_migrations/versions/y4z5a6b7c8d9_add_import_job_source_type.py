"""Add source_type column to import_jobs table.

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-06-01 00:00:00.000000

Changes:
  - Add source_type VARCHAR(50) nullable column to import_jobs

Requirements: 9.1
"""
from alembic import op

revision = 'y4z5a6b7c8d9'
down_revision = 'x3y4z5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE import_jobs
        ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)
    """)


def downgrade():
    op.execute("ALTER TABLE import_jobs DROP COLUMN IF EXISTS source_type")
