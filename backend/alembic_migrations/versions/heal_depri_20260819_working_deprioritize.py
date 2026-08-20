"""Unpark working leads silently copied to HubSpot Deprioritize.

Revision ID: heal_depri_20260819
Revises: mail_nudge_20260814
Create Date: 2026-08-19

Schema revision only. Nested app-factory / service heals are forbidden inside
Alembic (they can deadlock behind DDL locks and hang Deploy).

Data heal: backend/scripts/heal_working_deprioritize.py --apply
"""
from alembic import op  # noqa: F401 — revision module shape

revision = 'heal_depri_20260819'
down_revision = 'mail_nudge_20260814'
branch_labels = None
depends_on = None


def upgrade():
    # No-op: data heal must not run inside the Alembic transaction.
    pass


def downgrade():
    pass
