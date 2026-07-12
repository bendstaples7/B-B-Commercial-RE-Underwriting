"""Widen il_sos_llc_managers.mm_file_date for ISO CSV dates.

Revision ID: n3o4p5q6r7s8
Revises: m2n3o4p5q6r7
Create Date: 2026-07-12
"""
from alembic import op

revision = 'n3o4p5q6r7s8'
down_revision = 'm2n3o4p5q6r7'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE il_sos_llc_managers
        ALTER COLUMN mm_file_date TYPE VARCHAR(20)
    """)


def downgrade():
    op.execute("""
        ALTER TABLE il_sos_llc_managers
        ALTER COLUMN mm_file_date TYPE VARCHAR(8) USING LEFT(mm_file_date, 8)
    """)
