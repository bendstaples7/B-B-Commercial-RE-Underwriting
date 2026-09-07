"""Add outcome-calibration metadata to scoring_weights.

Revision ID: score_cal_20260907
Revises: c5d6e7f8a9b0, mail_cad_20260905
Create Date: 2026-09-07

Stores last calibration run (lifts, sample sizes, prior weights) and timestamp
so outcome-calibrated weight nudges are auditable.
"""
from alembic import op
import sqlalchemy as sa

revision = 'score_cal_20260907'
down_revision = ('c5d6e7f8a9b0', 'mail_cad_20260905')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'scoring_weights',
        sa.Column('calibration_meta', sa.JSON(), nullable=True),
    )
    op.add_column(
        'scoring_weights',
        sa.Column('last_calibrated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column('scoring_weights', 'last_calibrated_at')
    op.drop_column('scoring_weights', 'calibration_meta')
