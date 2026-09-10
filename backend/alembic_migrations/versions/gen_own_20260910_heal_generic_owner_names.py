"""Clear placeholder owner names and unstage mail candidates.

Revision ID: gen_own_20260910
Revises: score_cal_20260907
Create Date: 2026-09-10

Assessor stubs such as ``Taxpayer of`` / ``TAXPAYER OF <address>`` were treated
as real people and could reach Ready to Mail. Deploy runs the same heal as
``GenericOwnerHealService`` so existing rows leave mail staging automatically.
"""
from __future__ import annotations

revision = 'gen_own_20260910'
down_revision = 'score_cal_20260907'
branch_labels = None
depends_on = None


def upgrade():
    from app.services.generic_owner_heal_service import GenericOwnerHealService

    # Nested create_app is unnecessary — Alembic env already has the Flask app.
    summary = GenericOwnerHealService().heal_all(dry_run=False, rescore=True)
    print(
        'generic_owner_heal scanned=%s healed=%s'
        % (summary['scanned'], summary['healed'])
    )


def downgrade():
    # Data heal is not reversible (placeholder names were not real identities).
    pass
