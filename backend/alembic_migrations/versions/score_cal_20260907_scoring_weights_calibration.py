"""Add outcome-calibration metadata to scoring_weights.

Revision ID: score_cal_20260907
Revises: chan_roi_cascade_0831
Create Date: 2026-09-07

Stores last calibration run (lifts, sample sizes, prior weights) and timestamp
so outcome-calibrated weight nudges are auditable.
"""
from alembic import op

revision = 'score_cal_20260907'
down_revision = 'chan_roi_cascade_0831'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE scoring_weights
        ADD COLUMN IF NOT EXISTS calibration_meta JSON
    """)
    op.execute("""
        ALTER TABLE scoring_weights
        ADD COLUMN IF NOT EXISTS last_calibrated_at TIMESTAMP WITHOUT TIME ZONE
    """)


def downgrade():
    op.execute(
        "ALTER TABLE scoring_weights DROP COLUMN IF EXISTS last_calibrated_at"
    )
    op.execute(
        "ALTER TABLE scoring_weights DROP COLUMN IF EXISTS calibration_meta"
    )
