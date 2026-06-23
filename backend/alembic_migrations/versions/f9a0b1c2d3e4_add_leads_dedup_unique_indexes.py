"""Add unique dedup indexes on leads (owner+street, owner+PIN).

Revision ID: f9a0b1c2d3e4
Revises: f8a9b0c1d2e3
Create Date: 2026-06-22

Requires no remaining owner+normalized_street duplicates. Run merge first
(deploy.sh step 4a automates this on the VPS):

    python scripts/merge_duplicate_leads.py --mode dedup
    flask db upgrade
"""

from alembic import op
from sqlalchemy import text

revision = 'f9a0b1c2d3e4'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def _assert_no_owner_pin_duplicates(connection) -> None:
    rows = connection.execute(text(
        """
        SELECT owner_user_id, county_assessor_pin, count(*) AS cnt
        FROM leads
        WHERE owner_user_id IS NOT NULL
          AND county_assessor_pin IS NOT NULL AND county_assessor_pin != ''
        GROUP BY 1, 2
        HAVING count(*) > 1
        LIMIT 5
        """
    )).fetchall()
    if rows:
        sample = ', '.join(
            f"user={r.owner_user_id} pin={r.county_assessor_pin} ({r.cnt})"
            for r in rows
        )
        raise RuntimeError(
            "Cannot add unique dedup index — duplicate owner+PIN clusters remain. "
            f"Run: python scripts/merge_duplicate_leads.py --mode dedup. "
            f"Examples: {sample}"
        )


def _assert_no_owner_street_duplicates(connection) -> None:
    rows = connection.execute(text(
        """
        SELECT owner_user_id,
               lower(trim(owner_first_name)) AS fn,
               lower(trim(owner_last_name)) AS ln,
               normalized_street,
               count(*) AS cnt
        FROM leads
        WHERE normalized_street IS NOT NULL AND normalized_street != ''
          AND owner_first_name IS NOT NULL AND owner_first_name != ''
          AND owner_last_name IS NOT NULL AND owner_last_name != ''
          AND owner_user_id IS NOT NULL
        GROUP BY 1, 2, 3, 4
        HAVING count(*) > 1
        LIMIT 5
        """
    )).fetchall()
    if rows:
        sample = ', '.join(
            f"user={r.owner_user_id} {r.fn} {r.ln} @ {r.normalized_street} ({r.cnt})"
            for r in rows
        )
        raise RuntimeError(
            "Cannot add unique dedup index — duplicate owner+street clusters remain. "
            f"Run: python scripts/merge_duplicate_leads.py --mode dedup. "
            f"Examples: {sample}"
        )


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    _assert_no_owner_street_duplicates(bind)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_owner_normalized_street
        ON leads (
            owner_user_id,
            lower(trim(owner_first_name)),
            lower(trim(owner_last_name)),
            normalized_street
        )
        WHERE owner_user_id IS NOT NULL
          AND owner_first_name IS NOT NULL AND owner_first_name != ''
          AND owner_last_name IS NOT NULL AND owner_last_name != ''
          AND normalized_street IS NOT NULL AND normalized_street != ''
    """)
    _assert_no_owner_pin_duplicates(bind)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_owner_assessor_pin
        ON leads (owner_user_id, county_assessor_pin)
        WHERE owner_user_id IS NOT NULL
          AND county_assessor_pin IS NOT NULL AND county_assessor_pin != ''
    """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("DROP INDEX IF EXISTS uq_leads_owner_assessor_pin")
        op.execute("DROP INDEX IF EXISTS uq_leads_owner_normalized_street")
