"""Repair legacy rentcast_cache tables missing cache_key.

Revision ID: s9t0u1v2w3x4
Revises: q8r9s0t1u2v3
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "s9t0u1v2w3x4"
down_revision = "q8r9s0t1u2v3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("rentcast_cache")}

    # Fresh databases already have cache_key because the original create-table
    # migration was corrected. Older databases recorded that revision before
    # the correction and need this repair.
    if "cache_key" in columns:
        return

    constraints = {
        constraint["name"]: constraint
        for constraint in inspector.get_unique_constraints("rentcast_cache")
    }
    if "uq_rentcast_cache_key" in constraints:
        op.drop_constraint(
            "uq_rentcast_cache_key",
            "rentcast_cache",
            type_="unique",
        )

    op.execute(
        "ALTER TABLE rentcast_cache "
        "ADD COLUMN IF NOT EXISTS cache_key VARCHAR(700)"
    )

    rows = bind.execute(
        sa.text(
            "SELECT id, address_key, unit_type_label, bedrooms, bathrooms, "
            "square_footage FROM rentcast_cache"
        )
    )
    for row in rows.mappings():
        cache_key = json.dumps(
            [
                row["address_key"],
                row["unit_type_label"],
                "",
                row["bedrooms"],
                float(row["bathrooms"]) if row["bathrooms"] is not None else None,
                row["square_footage"],
            ],
            separators=(",", ":"),
        )
        bind.execute(
            sa.text(
                "UPDATE rentcast_cache SET cache_key = :cache_key WHERE id = :id"
            ),
            {"cache_key": cache_key, "id": row["id"]},
        )

    op.alter_column("rentcast_cache", "cache_key", nullable=False)
    op.create_unique_constraint(
        "uq_rentcast_cache_key",
        "rentcast_cache",
        ["cache_key"],
    )


def downgrade():
    op.execute(
        "ALTER TABLE rentcast_cache "
        "DROP CONSTRAINT IF EXISTS uq_rentcast_cache_key"
    )
    op.execute("ALTER TABLE rentcast_cache DROP COLUMN IF EXISTS cache_key")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_rentcast_cache_key'
                  AND conrelid = 'rentcast_cache'::regclass
            ) THEN
                ALTER TABLE rentcast_cache
                ADD CONSTRAINT uq_rentcast_cache_key UNIQUE
                    (address_key, unit_type_label, bedrooms, bathrooms, square_footage);
            END IF;
        END
        $$;
        """
    )
