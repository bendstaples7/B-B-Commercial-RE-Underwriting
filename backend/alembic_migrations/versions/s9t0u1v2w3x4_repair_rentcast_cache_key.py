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
    columns = {
        column["name"]: column
        for column in inspector.get_columns("rentcast_cache")
    }

    constraints = {
        constraint["name"]: constraint
        for constraint in inspector.get_unique_constraints("rentcast_cache")
    }
    cache_constraint = constraints.get("uq_rentcast_cache_key")
    has_cache_key_constraint = (
        cache_constraint is not None
        and cache_constraint.get("column_names") == ["cache_key"]
    )
    if cache_constraint is not None and not has_cache_key_constraint:
        op.drop_constraint(
            "uq_rentcast_cache_key",
            "rentcast_cache",
            type_="unique",
        )

    op.execute(
        "ALTER TABLE rentcast_cache "
        "ADD COLUMN IF NOT EXISTS cache_key VARCHAR(700)"
    )

    # Legacy rows predate property_type-aware keys. Multi-Family is the
    # application's default and preserves cache hits for the common path.
    rows = bind.execute(
        sa.text(
            "SELECT id, address_key, unit_type_label, bedrooms, bathrooms, "
            "square_footage FROM rentcast_cache WHERE cache_key IS NULL"
        )
    )
    for row in rows.mappings():
        cache_key = json.dumps(
            [
                row["address_key"],
                row["unit_type_label"],
                "Multi-Family",
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

    # Nullable key fields allowed duplicate legacy rows. Keep the newest cache
    # entry for each generated key before enforcing uniqueness.
    bind.execute(
        sa.text(
            """
            DELETE FROM rentcast_cache AS older
            USING rentcast_cache AS newer
            WHERE older.cache_key = newer.cache_key
              AND (
                    older.fetched_at < newer.fetched_at
                    OR (
                        older.fetched_at = newer.fetched_at
                        AND older.id < newer.id
                    )
              )
            """
        )
    )

    if "cache_key" not in columns or columns["cache_key"].get("nullable", True):
        op.alter_column("rentcast_cache", "cache_key", nullable=False)
    if not has_cache_key_constraint:
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
