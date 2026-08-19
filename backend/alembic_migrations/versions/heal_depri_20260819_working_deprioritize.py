"""Unpark working leads silently copied to HubSpot Deprioritize.

Revision ID: heal_depri_20260819
Revises: mail_nudge_20260814
Create Date: 2026-08-19
"""
import os
import sys

import sqlalchemy as sa
from alembic import op

revision = 'heal_depri_20260819'
down_revision = 'mail_nudge_20260814'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    parked = bind.execute(sa.text(
        "SELECT COUNT(*) FROM leads WHERE lead_status = 'deprioritize'"
    )).scalar()
    if not parked:
        return

    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from flask import has_app_context

    from app.services.lead_status_service import heal_working_deprioritize_leads

    def _run():
        heal_working_deprioritize_leads(
            commit=True,
            push_hubspot=False,
            recompute_action=False,
        )

    if has_app_context():
        _run()
        return

    from app import create_app

    app = create_app()
    with app.app_context():
        _run()


def downgrade():
    pass
