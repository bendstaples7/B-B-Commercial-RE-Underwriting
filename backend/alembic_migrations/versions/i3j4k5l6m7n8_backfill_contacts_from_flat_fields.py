"""Backfill relational contacts from legacy flat lead fields.

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-06-25

Attaches each lead's legacy flat ``phone_1..7`` / ``email_1..5`` values to its
primary owner ``Contact`` (creating that contact if missing), so the Log Call /
Log Email phone & email dropdowns -- which read the relational data via
``GET /api/properties/:id/contacts`` -- populate everywhere.

The original flat->relational migration (``k1l2m3n4o5p6``) skipped any lead that
already had a ``property_contacts`` row, leaving partially/wrongly migrated leads
broken. This data migration repairs them idempotently. All logic lives in the
canonical helper ``app.services.contact_backfill`` so it can also be exercised by
scripts and unit tests.
"""
import os
import sys

from alembic import op

revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from app.services.contact_backfill import backfill_contacts_from_flat_fields

    backfill_contacts_from_flat_fields(op.get_bind())


def downgrade():
    # Data backfill is additive and idempotent; there is no safe automatic
    # downgrade (we cannot tell backfilled rows from manually-entered ones).
    pass
