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
        # Drop the old cap_rate range CHECK constraint (was NOT NULL > 0).
        # Use raw SQL IF EXISTS so we don't swallow real errors while tolerating
        # the case where the constraint doesn't exist (e.g. fresh DB, SQLite).
        op.execute("ALTER TABLE sale_comps DROP CONSTRAINT IF EXISTS ck_sale_comps_cap_rate_range")
        # Re-create cap_rate range constraint allowing NULL (nullable column)
        batch_op.create_check_constraint(
            'ck_sale_comps_cap_rate_range',
            'observed_cap_rate IS NULL OR (observed_cap_rate > 0 AND observed_cap_rate <= 0.25)',
        )
        # Add confidence constraint — must be one of the documented sentinel values
        batch_op.create_check_constraint(
            'ck_sale_comps_cap_rate_confidence_values',
            'cap_rate_confidence IS NULL OR cap_rate_confidence IN (0.0, 0.5, 1.0)',
        )


def downgrade():
    with op.batch_alter_table('sale_comps', schema=None) as batch_op:
        # Drop constraints BEFORE dropping the columns they reference.
        # Use raw SQL IF EXISTS so we don't swallow real errors while still
        # tolerating the case where the constraint was never created (e.g. SQLite).
        op.execute("ALTER TABLE sale_comps DROP CONSTRAINT IF EXISTS ck_sale_comps_cap_rate_confidence_values")
        op.execute("ALTER TABLE sale_comps DROP CONSTRAINT IF EXISTS ck_sale_comps_cap_rate_range")
        batch_op.drop_column('cap_rate_confidence')
        batch_op.drop_column('noi')

    # Fail fast if any rows have NULL observed_cap_rate — restoring NOT NULL
    # would invent data. The operator must remediate those rows first.
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT COUNT(*) FROM sale_comps WHERE observed_cap_rate IS NULL"))
    null_count = result.scalar()
    if null_count:
        raise RuntimeError(
            f"Cannot downgrade: {null_count} row(s) in sale_comps have NULL observed_cap_rate. "
            "Set observed_cap_rate to a valid value (0 < x <= 0.25) for all affected rows "
            "before running this downgrade."
        )

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
