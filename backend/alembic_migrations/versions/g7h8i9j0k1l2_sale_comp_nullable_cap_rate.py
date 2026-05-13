"""sale_comp: make cap_rate nullable, add noi and cap_rate_confidence

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-05-13 00:00:00.000000

Changes:
  - observed_cap_rate: NOT NULL → nullable (many comps don't have cap rates)
  - Remove CHECK constraint ck_sale_comps_cap_rate_range
  - Add noi column (nullable Numeric) — annual NOI if known, used to derive cap rate
  - Add cap_rate_confidence column (nullable Float 0.0–1.0):
      1.0 = cap rate stated directly
      0.5 = cap rate derived from NOI / sale_price
      0.0 = cap rate unknown
"""
from alembic import op
import sqlalchemy as sa


revision = 'g7h8i9j0k1l2'
down_revision = 'f6g7h8i9j0k1'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the CHECK constraint that requires cap_rate > 0
    # (constraint name varies by DB; use batch_alter_table for SQLite compat)
    with op.batch_alter_table('sale_comps', schema=None) as batch_op:
        # Make observed_cap_rate nullable
        batch_op.alter_column(
            'observed_cap_rate',
            existing_type=sa.Numeric(precision=8, scale=6),
            nullable=True,
        )
        # Add noi column (annual net operating income, if known)
        batch_op.add_column(
            sa.Column('noi', sa.Numeric(precision=14, scale=2), nullable=True)
        )
        # Add cap_rate_confidence column
        batch_op.add_column(
            sa.Column('cap_rate_confidence', sa.Float(), nullable=True)
        )
        # Drop the cap_rate range CHECK constraint
        try:
            batch_op.drop_constraint('ck_sale_comps_cap_rate_range', type_='check')
        except Exception:
            # Constraint may not exist in all DB backends (SQLite ignores named constraints)
            pass


def downgrade():
    with op.batch_alter_table('sale_comps', schema=None) as batch_op:
        batch_op.drop_column('cap_rate_confidence')
        batch_op.drop_column('noi')

    # Backfill NULL cap rates before restoring NOT NULL constraint.
    # Use 0.065 (6.5%) as a safe default that satisfies the restored CHECK constraint.
    op.execute("UPDATE sale_comps SET observed_cap_rate = 0.065 WHERE observed_cap_rate IS NULL")

    with op.batch_alter_table('sale_comps', schema=None) as batch_op:
        batch_op.alter_column(
            'observed_cap_rate',
            existing_type=sa.Numeric(precision=8, scale=6),
            nullable=False,
        )
        batch_op.create_check_constraint(
            'ck_sale_comps_cap_rate_range',
            'observed_cap_rate > 0 AND observed_cap_rate <= 0.25',
        )
