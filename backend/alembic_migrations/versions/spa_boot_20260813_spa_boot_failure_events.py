"""Add spa_boot_failure_events for blank-SPA phone-home beacons.

Revision ID: spa_boot_20260813
Revises: note_pf_20260812
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'spa_boot_20260813'
down_revision = 'note_pf_20260812'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'spa_boot_failure_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column('href', sa.String(length=1024), nullable=True),
        sa.Column('reason', sa.String(length=128), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('asset_hints', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        'ix_spa_boot_failure_events_created_at',
        'spa_boot_failure_events',
        ['created_at'],
    )
    op.create_index(
        'ix_spa_boot_failure_events_ip_hash',
        'spa_boot_failure_events',
        ['ip_hash'],
    )


def downgrade():
    op.drop_index('ix_spa_boot_failure_events_ip_hash', table_name='spa_boot_failure_events')
    op.drop_index('ix_spa_boot_failure_events_created_at', table_name='spa_boot_failure_events')
    op.drop_table('spa_boot_failure_events')
