"""Create lead_tasks table for Actionable Lead Command Center.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-05-20 00:01:00.000000

Changes:
  - Create PostgreSQL enum `lead_task_type_enum` with 7 values
  - Create PostgreSQL enum `lead_task_status_enum` with 3 values
  - Create `lead_tasks` table with all columns:
      id (PK), lead_id (FK → leads.id CASCADE), task_type, title,
      status, due_date, created_at, completed_at, created_by
  - Create single-column index on lead_id (ix_lead_tasks_lead_id)
  - Create single-column index on status (ix_lead_tasks_status)
  - Create composite index ix_lead_tasks_lead_status (lead_id, status)
  - Create composite index ix_lead_tasks_status_due_date (status, due_date)

Requirements: Phase 1, Task 1.2 — Actionable Lead Command Center
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'n4o5p6q7r8s9'
down_revision = 'm3n4o5p6q7r8'
branch_labels = None
depends_on = None

# Enum definitions
_TASK_TYPE_ENUM_NAME = 'lead_task_type_enum'
_TASK_TYPE_VALUES = (
    'call_owner_today', 'research_missing_pin', 'match_hubspot_deal',
    'run_property_analysis', 'add_to_mail_batch', 'skip_trace_owner', 'custom',
)

_TASK_STATUS_ENUM_NAME = 'lead_task_status_enum'
_TASK_STATUS_VALUES = ('open', 'completed', 'cancelled')


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Create enum types
    # ------------------------------------------------------------------
    task_type_enum = postgresql.ENUM(*_TASK_TYPE_VALUES, name=_TASK_TYPE_ENUM_NAME)
    task_type_enum.create(bind, checkfirst=True)

    task_status_enum = postgresql.ENUM(*_TASK_STATUS_VALUES, name=_TASK_STATUS_ENUM_NAME)
    task_status_enum.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Create lead_tasks table
    # ------------------------------------------------------------------
    op.create_table(
        'lead_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'lead_id',
            sa.Integer(),
            sa.ForeignKey('leads.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'task_type',
            sa.Enum(*_TASK_TYPE_VALUES, name=_TASK_TYPE_ENUM_NAME),
            nullable=False,
            server_default='custom',
        ),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column(
            'status',
            sa.Enum(*_TASK_STATUS_VALUES, name=_TASK_STATUS_ENUM_NAME),
            nullable=False,
            server_default='open',
        ),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column(
            'created_by',
            sa.String(100),
            nullable=False,
            server_default='anonymous',
        ),
        sa.PrimaryKeyConstraint('id'),
    )

    # ------------------------------------------------------------------
    # 3. Single-column indexes (on lead_id and status individually)
    # ------------------------------------------------------------------
    op.create_index('ix_lead_tasks_lead_id', 'lead_tasks', ['lead_id'])
    op.create_index('ix_lead_tasks_status', 'lead_tasks', ['status'])

    # ------------------------------------------------------------------
    # 4. Composite indexes as specified in the design
    # ------------------------------------------------------------------
    op.create_index('ix_lead_tasks_lead_status', 'lead_tasks', ['lead_id', 'status'])
    op.create_index('ix_lead_tasks_status_due_date', 'lead_tasks', ['status', 'due_date'])


def downgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Drop composite indexes
    # ------------------------------------------------------------------
    op.drop_index('ix_lead_tasks_status_due_date', table_name='lead_tasks')
    op.drop_index('ix_lead_tasks_lead_status', table_name='lead_tasks')

    # ------------------------------------------------------------------
    # 2. Drop single-column indexes
    # ------------------------------------------------------------------
    op.drop_index('ix_lead_tasks_status', table_name='lead_tasks')
    op.drop_index('ix_lead_tasks_lead_id', table_name='lead_tasks')

    # ------------------------------------------------------------------
    # 3. Drop the table
    # ------------------------------------------------------------------
    op.drop_table('lead_tasks')

    # ------------------------------------------------------------------
    # 4. Drop enum types
    # ------------------------------------------------------------------
    task_status_enum = postgresql.ENUM(*_TASK_STATUS_VALUES, name=_TASK_STATUS_ENUM_NAME)
    task_status_enum.drop(bind, checkfirst=True)

    task_type_enum = postgresql.ENUM(*_TASK_TYPE_VALUES, name=_TASK_TYPE_ENUM_NAME)
    task_type_enum.drop(bind, checkfirst=True)
