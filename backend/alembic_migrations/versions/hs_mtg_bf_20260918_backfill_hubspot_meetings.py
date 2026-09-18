"""Mark HubSpot MEETING engagement backfill ownership.

Revision ID: hs_mtg_bf_20260918
Revises: hs_mtg_20260918
Create Date: 2026-09-18

Schema-only Alembic policy keeps service-layer data repairs out of migrations.
Run backend/scripts/backfill_hubspot_interactions_to_timeline.py --apply to
convert stored MEETING engagements and bridge them to the Command Center
timeline. The script is idempotent and uses mark_review=False so historical
meetings do not flood Needs Review.
"""
from __future__ import annotations

revision = 'hs_mtg_bf_20260918'
down_revision = 'hs_mtg_20260918'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
