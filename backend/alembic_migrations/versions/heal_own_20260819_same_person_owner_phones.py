"""Heal same-person owner splits (dialed phone on former_owner).

Revision ID: heal_own_20260819
Revises: mail_nudge_20260814
Create Date: 2026-08-19

GIS listing-name refreshes archived the contacted person and left dump numbers
on a new owner contact. Idempotently reactivate the HubSpot-primary / dialed
contact and move extra numbers onto them.
"""
import os
import sys

import sqlalchemy as sa
from alembic import op

revision = 'heal_own_20260819'
down_revision = 'mail_nudge_20260814'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    clustered = bind.execute(sa.text("""
        SELECT COUNT(*) FROM (
            SELECT property_id
            FROM property_contacts
            WHERE role IN ('owner', 'former_owner')
            GROUP BY property_id
            HAVING COUNT(*) >= 2
        ) clustered
    """)).scalar()
    if not clustered:
        return

    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from flask import has_app_context

    from app.services.contact_service import ContactService

    def _run():
        ContactService().heal_same_person_owners_all_leads(
            commit=True,
            refresh_scoring=False,
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
