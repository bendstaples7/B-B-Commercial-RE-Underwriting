"""Create lead_timeline_entries table for Actionable Lead Command Center.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-05-20 00:02:00.000000

Changes:
  - Create PostgreSQL enum `timeline_event_type_enum` with 13 values
  - Create `lead_timeline_entries` table with all columns:
      id (PK), lead_id (FK → leads.id CASCADE), event_type,
      occurred_at, source, actor, summary, metadata,
      hubspot_activity_id, is_deleted, created_at
  - Create single-column index on lead_id (ix_timeline_lead_id)
  - Create single-column index on event_type (ix_timeline_event_type)
  - Create single-column index on occurred_at (ix_timeline_occurred_at)
  - Create composite index ix_timeline_lead_occurred (lead_id, occurred_at)
  - Create unique index ix_timeline_hubspot_activity_id (hubspot_activity_id)

Requirements: Phase 1, Task 1.3 — Actionable Lead Command Center
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'o5p6q7r8s9t0'
down_revision = 'n4o5p6q7r8s9'
branch_labels = None
depends_on = None

# Enum definition
_EVENT_TYPE_ENUM_NAME = 'timeline_event_type_enum'
_EVENT_TYPE_VALUES = (
    'note_added', 'call_logged', 'task_created', 'task_completed',
    'task_snoozed', 'recommended_action_changed', 'status_changed',
    'hubspot_note', 'hubspot_call', 'hubspot_task', 'hubspot_deal_stage',
    'property_analysis_completed', 'lead_imported',
)


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Create enum type
    # ------------------------------------------------------------------
    event_type_enum = postgresql.ENUM(*_EVENT_TYPE_VALUES, name=_EVENT_TYPE_ENUM_NAME)
    event_type_enum.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Create lead_timeline_entries table
    # ------------------------------------------------------------------
    op.create_table(
        'lead_timeline_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'lead_id',
            sa.Integer(),
            sa.ForeignKey('leads.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'event_type',
            sa.Enum(*_EVENT_TYPE_VALUES, name=_EVENT_TYPE_ENUM_NAME),
            nullable=False,
        ),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column(
            'source',
            sa.String(20),
            nullable=False,
            server_default='manual',
        ),
        sa.Column('actor', sa.String(100), nullable=False),
        sa.Column('summary', sa.String(500), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('hubspot_activity_id', sa.String(50), nullable=True),
        sa.Column(
            'is_deleted',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
        sa.PrimaryKeyConstraint('id'),
    )

    # ------------------------------------------------------------------
    # 3. Single-column indexes (on lead_id, event_type, occurred_at)
    # ------------------------------------------------------------------
    op.create_index('ix_timeline_lead_id', 'lead_timeline_entries', ['lead_id'])
    op.create_index('ix_timeline_event_type', 'lead_timeline_entries', ['event_type'])
    op.create_index('ix_timeline_occurred_at', 'lead_timeline_entries', ['occurred_at'])

    # ------------------------------------------------------------------
    # 4. Composite index as specified in the design
    # ------------------------------------------------------------------
    op.create_index(
        'ix_timeline_lead_occurred',
        'lead_timeline_entries',
        ['lead_id', 'occurred_at'],
    )

    # ------------------------------------------------------------------
    # 5. Unique index on hubspot_activity_id for deduplication
    # ------------------------------------------------------------------
    op.create_index(
        'ix_timeline_hubspot_activity_id',
        'lead_timeline_entries',
        ['hubspot_activity_id'],
        unique=True,
    )


def downgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Drop unique index on hubspot_activity_id
    # ------------------------------------------------------------------
    op.drop_index('ix_timeline_hubspot_activity_id', table_name='lead_timeline_entries')

    # ------------------------------------------------------------------
    # 2. Drop composite index
    # ------------------------------------------------------------------
    op.drop_index('ix_timeline_lead_occurred', table_name='lead_timeline_entries')

    # ------------------------------------------------------------------
    # 3. Drop single-column indexes
    # ------------------------------------------------------------------
    op.drop_index('ix_timeline_occurred_at', table_name='lead_timeline_entries')
    op.drop_index('ix_timeline_event_type', table_name='lead_timeline_entries')
    op.drop_index('ix_timeline_lead_id', table_name='lead_timeline_entries')

    # ------------------------------------------------------------------
    # 4. Drop the table
    # ------------------------------------------------------------------
    op.drop_table('lead_timeline_entries')

    # ------------------------------------------------------------------
    # 5. Drop enum type
    # ------------------------------------------------------------------
    event_type_enum = postgresql.ENUM(*_EVENT_TYPE_VALUES, name=_EVENT_TYPE_ENUM_NAME)
    event_type_enum.drop(bind, checkfirst=True)
