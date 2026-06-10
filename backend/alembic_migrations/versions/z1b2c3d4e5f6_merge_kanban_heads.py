"""Merge kanban view scoring branch heads into a single migration chain.

Revision ID: z1b2c3d4e5f6
Revises: b3c4d5e6f7a1, z0a9b8c7d6e5
Create Date: 2026-06-10 01:10:00.000000

This merge consolidates two migration heads:
  1. b3c4d5e6f7a1 — squash/marker head from main
  2. z0a9b8c7d6e5 — pipeline stage config merge head from
     feat/kanban-view-scoring

After this merge, the migration chain has a single head, satisfying the
idempotency prerequisite enforced by test_property8_migration_idempotency.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'z1b2c3d4e5f6'
down_revision = ('b3c4d5e6f7a1', 'z0a9b8c7d6e5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass