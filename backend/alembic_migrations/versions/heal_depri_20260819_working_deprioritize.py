"""Unpark working leads silently copied to HubSpot Deprioritize.

Revision ID: heal_depri_20260819
Revises: heal_own_20260819
Create Date: 2026-08-19
"""
import os
import sys

from alembic import op  # noqa: F401 — Alembic revision module contract

revision = 'heal_depri_20260819'
down_revision = 'heal_own_20260819'
branch_labels = None
depends_on = None


def upgrade():
    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from flask import has_app_context

    from app.services.lead_status_service import heal_working_deprioritize_leads

    def _run():
        heal_working_deprioritize_leads(commit=True)

    if has_app_context():
        _run()
        return

    from app import create_app

    app = create_app()
    with app.app_context():
        _run()


def downgrade():
    pass
