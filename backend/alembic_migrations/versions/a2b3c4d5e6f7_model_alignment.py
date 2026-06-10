"""Model-alignment: converge enum and column types to model-aligned form.

Revision ID: a2b3c4d5e6f7
Revises: z5a6b7c8d9e0
Create Date: 2026-06-12 00:00:00.000000

History / Why this revision exists
------------------------------------
``000000000000_initial_schema`` creates enum types with lowercase names and
lowercase values (``property_type`` with values ``single_family``, etc.)
because those names matched the raw SQL files applied before Alembic.

``267725fe7017_baseline_schema`` was originally intended to rename those types
to PascalCase names with UPPERCASE values (``propertytype`` with values
``SINGLE_FAMILY``, etc.) to match an older version of the SQLAlchemy models.
However, the SQLAlchemy models were updated — they now use lowercase values via
``values_callable``, e.g.::

    class PropertyType(enum.Enum):
        SINGLE_FAMILY = 'single_family'   # .value is lowercase
    db.Column(db.Enum(PropertyType, values_callable=lambda x: [e.value for e in x]))

So the production database is **already correct**: the ``property_type`` enum
with lowercase values (``single_family``, ``multi_family``, ``commercial``)
matches what the models actually store and read.  The JSONB→JSON and ARRAY→JSON
conversions were already applied by ``267725fe7017`` on existing databases, and
the index renames (``idx_*`` → ``ix_*``) were also already applied.

This revision is therefore a **deliberate no-op** for all schema modifications.
The revision record (``a2b3c4d5e6f7``) is kept in the chain so the Alembic
version table advances correctly and production databases that have not yet
applied this revision can do so safely without any schema change.

Why not remove this revision?
     Removing it would break the chain for any database already stamped past
     it.  Keeping it as an explicit no-op is the safest path.

Why were the enum conversions removed?
     The original Step 1 created ``propertytype`` with UPPERCASE values and
     Step 2 tried to cast ``property_type`` columns using ``upper(...)::propertytype``.
     On production the ``propertytype`` enum already existed (created by
     ``267725fe7017``) with **lowercase** values, so ``EXCEPTION WHEN
     duplicate_object`` silently skipped re-creation, leaving it lowercase.
     The subsequent ``upper(...)::propertytype`` cast then failed with
     ``InvalidTextRepresentation: invalid input value for enum propertytype:
     "SINGLE_FAMILY"`` because the enum only accepted lowercase.  Since the
     models use lowercase values, the existing DB state is correct — no
     conversion is needed.

Revision ID: a2b3c4d5e6f7
"""
from alembic import op  # noqa: F401  (kept for convention; not used in body)


# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    # Intentional no-op.
    #
    # All schema changes originally planned for this revision were either:
    #   (a) already applied to production by earlier revisions, or
    #   (b) incorrect (wrong enum values — see module docstring).
    #
    # The revision record advances the Alembic version table so that
    # subsequent revisions (b3c4d5e6f7a1) can be applied without
    # requiring any schema mutation.
    pass


def downgrade():
    # Intentional no-op — nothing was applied by upgrade().
    pass
