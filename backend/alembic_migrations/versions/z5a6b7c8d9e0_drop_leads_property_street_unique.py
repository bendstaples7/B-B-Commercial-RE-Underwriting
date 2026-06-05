"""Drop unique constraint on leads.property_street.

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-06-05 00:00:00.000000

Background:
  leads.property_street had a UNIQUE constraint that made sense when the
  dataset was small (one record per property). With the DuPage County bulk
  import (~70K records), many parcels share the same street name (e.g.
  "MANOR DR", "NELTNOR BLVD") but have distinct county_assessor_pin values.
  The correct deduplication key is county_assessor_pin, not property_street.

  This migration drops the erroneous unique constraint so bulk imports no
  longer silently skip valid leads due to street-name collisions.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = 'z5a6b7c8d9e0'
down_revision = 'y4z5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE leads
        DROP CONSTRAINT IF EXISTS leads_property_street_key
    """)


def downgrade():
    # Re-creating this constraint on a table with duplicate street values
    # will fail unless duplicates are resolved first. The downgrade is
    # intentionally a no-op to avoid breaking a populated database.
    pass
