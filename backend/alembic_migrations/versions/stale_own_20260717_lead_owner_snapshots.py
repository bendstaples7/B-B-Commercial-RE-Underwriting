"""Add former_owner role, superseded_at, and lead_owner_snapshots.

Revision ID: stale_own_20260717
Revises: act_goals_fk_20260716
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'stale_own_20260717'
down_revision = 'act_goals_fk_20260716'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE property_contact_role_enum "
        "ADD VALUE IF NOT EXISTS 'former_owner'"
    )
    op.add_column(
        'property_contacts',
        sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'lead_owner_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'lead_id',
            sa.Integer(),
            sa.ForeignKey('leads.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'captured_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
        sa.Column('reason', sa.String(40), nullable=False),
        sa.Column('sale_date', sa.Date(), nullable=True),
        sa.Column(
            'payload',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        'ix_lead_owner_snapshots_lead_sale',
        'lead_owner_snapshots',
        ['lead_id', 'sale_date'],
    )
    # One recent_sale snapshot per lead+sale (concurrent CC GET safety).
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_owner_snapshots_recent_sale
        ON lead_owner_snapshots (lead_id, sale_date)
        WHERE reason = 'recent_sale' AND sale_date IS NOT NULL
        """
    )


def downgrade():
    op.drop_index('ix_lead_owner_snapshots_lead_sale', table_name='lead_owner_snapshots')
    op.drop_table('lead_owner_snapshots')
    op.drop_column('property_contacts', 'superseded_at')
    # Postgres cannot easily remove enum values; leave former_owner in place.
