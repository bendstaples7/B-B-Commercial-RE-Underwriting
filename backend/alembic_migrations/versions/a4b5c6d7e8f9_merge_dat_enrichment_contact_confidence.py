"""Merge data-enrichment-scoring and contact-phone-confidence heads

Revision ID: a4b5c6d7e8f9
Revises: ('97321ab5e710', 'j4k5l6m7n8o9')
Create Date: 2026-06-27

This merge consolidates two migration heads:
  1. 97321ab5e710 — add violation_data, permit_data columns (feature/data-enrichment-scoring)
  2. j4k5l6m7n8o9 — add contact phone confidence columns (PR #76)

After this merge, the migration chain has a single head, satisfying the
single-head requirement enforced by the pre-upgrade guard.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a4b5c6d7e8f9'
down_revision = ('97321ab5e710', 'j4k5l6m7n8o9')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass