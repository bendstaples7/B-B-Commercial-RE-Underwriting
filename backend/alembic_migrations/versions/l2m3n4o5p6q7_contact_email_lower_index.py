"""Replace case-sensitive contact_emails.value index with functional lower(value) index.

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-05-18 00:00:00.000000

Changes:
  - Drop the case-sensitive ix_contact_emails_value index created in k1l2m3n4o5p6.
  - Create a functional index ix_contact_emails_value_lower on lower(value) so that
    the HubSpot matcher's case-insensitive email lookup
    (filter(lower(ContactEmail.value) == email)) can use an index scan instead of
    a full table scan.

Requirements: 11.1 (HubSpot contact matching)
"""
from alembic import op

revision = 'l2m3n4o5p6q7'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old case-sensitive index
    op.drop_index('ix_contact_emails_value', table_name='contact_emails')

    # Create functional index on lower(value) for case-insensitive lookups
    op.execute(
        "CREATE INDEX ix_contact_emails_value_lower "
        "ON contact_emails (lower(value))"
    )


def downgrade():
    # Drop the functional index
    op.execute("DROP INDEX IF EXISTS ix_contact_emails_value_lower")

    # Restore the original case-sensitive index
    op.create_index(
        'ix_contact_emails_value',
        'contact_emails',
        ['value'],
        unique=False
    )
