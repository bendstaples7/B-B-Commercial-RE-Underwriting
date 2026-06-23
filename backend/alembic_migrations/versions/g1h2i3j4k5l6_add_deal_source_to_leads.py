"""Add deal_source and deal_description to leads.

Revision ID: g1h2i3j4k5l6
Revises: f9a0b1c2d3e4
Create Date: 2026-06-23

General deal context (where the lead was found / why it matters), populated
from HubSpot and other sources — not HubSpot-specific columns.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'g1h2i3j4k5l6'
down_revision = 'f9a0b1c2d3e4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('leads', sa.Column('deal_source', sa.String(255), nullable=True))
    op.add_column('leads', sa.Column('deal_description', sa.Text(), nullable=True))

    # Backfill from linked HubSpot deals where available
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE leads l
        SET deal_source = NULLIF(TRIM(hd.raw_payload->'properties'->>'deal_source'), ''),
            deal_description = NULLIF(TRIM(hd.raw_payload->'properties'->>'description'), '')
        FROM hubspot_matches hm
        JOIN hubspot_deals hd ON hd.hubspot_id = hm.hubspot_id
        WHERE hm.internal_record_type = 'lead'
          AND hm.internal_record_id = l.id
          AND hm.hubspot_record_type = 'deal'
          AND hm.status = 'confirmed'
          AND (
            NULLIF(TRIM(hd.raw_payload->'properties'->>'deal_source'), '') IS NOT NULL
            OR NULLIF(TRIM(hd.raw_payload->'properties'->>'description'), '') IS NOT NULL
          )
    """))


def downgrade():
    op.drop_column('leads', 'deal_description')
    op.drop_column('leads', 'deal_source')
