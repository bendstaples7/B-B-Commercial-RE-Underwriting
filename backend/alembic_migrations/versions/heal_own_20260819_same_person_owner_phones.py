"""Heal same-person owner splits (dialed phone on former_owner).

Revision ID: heal_own_20260819
Revises: keep_gis_20260819
Create Date: 2026-08-19

Schema revision only. Nested app-factory / service heals are forbidden inside
Alembic (they deadlock behind AccessExclusiveLock from prior DDL).

Data heal (already applied on production): run outside migrations via
backend/scripts/heal_same_person_owners.py (per-lead) or the bulk helper on
contact_service.heal_same_person_owners_all_leads from a one-shot shell —
never from this revision module.
"""
from alembic import op  # noqa: F401 — revision module shape

revision = 'heal_own_20260819'
down_revision = 'keep_gis_20260819'
branch_labels = None
depends_on = None


def upgrade():
    # No-op: data heal must not run inside the Alembic transaction.
    pass


def downgrade():
    pass
