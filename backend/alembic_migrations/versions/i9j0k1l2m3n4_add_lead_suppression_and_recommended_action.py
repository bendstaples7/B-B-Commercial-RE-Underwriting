"""add lead suppression_flag and recommended_action columns

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-05-14 00:00:00.000000

Changes:
  - Create PostgreSQL enum type `recommended_action_enum` with values:
      CONTACT_NOW, FOLLOW_UP_LATER, REVISIT_OFFER, DO_NOT_CONTACT
  - Add `suppression_flag` column (Boolean, NOT NULL, default False) to `leads`
  - Add `recommended_action` column (recommended_action_enum, nullable) to `leads`

Requirements: 16.3, 17.3, 17.4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError, InternalError, ProgrammingError

# Suppress "already exists" / "does not exist" errors for idempotent DDL
_DDL_CONFLICT = (OperationalError, InternalError, ProgrammingError)

revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None

# The enum type name and its allowed values
_ENUM_NAME = 'recommended_action_enum'
_ENUM_VALUES = ('CONTACT_NOW', 'FOLLOW_UP_LATER', 'REVISIT_OFFER', 'DO_NOT_CONTACT')


def upgrade():
    # Create the PostgreSQL enum type.
    # Use checkfirst=True so re-running the migration on a DB that already has
    # the type (e.g. from a partial run) does not raise an error.
    recommended_action_enum = postgresql.ENUM(
        *_ENUM_VALUES,
        name=_ENUM_NAME,
    )
    recommended_action_enum.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('leads', schema=None) as batch_op:
        # Add suppression_flag: NOT NULL with server-side default of FALSE so
        # existing rows are backfilled automatically without a separate UPDATE.
        batch_op.add_column(
            sa.Column(
                'suppression_flag',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('FALSE'),
            )
        )
        # Add recommended_action: nullable enum column
        batch_op.add_column(
            sa.Column(
                'recommended_action',
                sa.Enum(*_ENUM_VALUES, name=_ENUM_NAME),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('recommended_action')
        batch_op.drop_column('suppression_flag')

    # Drop the enum type.  Use checkfirst=True so a partial downgrade (where
    # the type was already removed) does not raise an error.
    recommended_action_enum = postgresql.ENUM(
        *_ENUM_VALUES,
        name=_ENUM_NAME,
    )
    recommended_action_enum.drop(op.get_bind(), checkfirst=True)
