"""Squash/marker head revision — consolidation boundary.

This revision establishes the single unambiguous Migration_Head for the
clean-baseline (squash) strategy.  Its upgrade() and downgrade() are
intentional no-ops; all schema work was performed by prior revisions.

Baseline-Replacement Mapping
=============================
The consolidated baseline consists of the following revisions:

  * 000000000000  — initial_schema (single root; creates all pre-Alembic tables,
                    users table, indexes, and enum types using idempotent raw SQL)
  * 267725fe7017  — baseline_schema (neutralised for fresh-DB safety; idempotent
                    no-op when target types already match model-aligned form)
  * a2b3c4d5e6f7  — model_alignment (converts enum types and column types to the
                    model-aligned form using guarded, conditional raw SQL that is a
                    no-op when the target type already matches)

Prior revisions replaced/consolidated
--------------------------------------
The entire pre-consolidation chain up to and including
z5a6b7c8d9e0_drop_leads_property_street_unique is subsumed by the three
baseline revisions listed above.  Every revision from 000000000000 through
z5a6b7c8d9e0 appears in the chain and is applied in order on existing
databases; on a fresh database the baseline revisions produce the same final
schema directly.

Stamp path for existing production databases
---------------------------------------------
Production databases already at a revision in the pre-consolidation chain
(000000000000 … z5a6b7c8d9e0) should be advanced to the new head by running
the normal upgrade command:

    flask db upgrade

If the database was stamped to a baseline revision manually and you need to
advance the recorded revision without applying schema changes, use:

    flask db stamp b3c4d5e6f7a1

IMPORTANT: stamping only changes the recorded revision in the alembic_version
table.  It does NOT apply any schema changes.  Only use stamp when you are
certain the schema already matches the state produced by this revision.

Assumed starting revision for the stamp command: b3c4d5e6f7a1
(i.e. the database schema already reflects all migrations up to and including
this marker; use ``flask db upgrade`` instead if in doubt).

Unrecognised starting revision
-------------------------------
If the upgrade path is executed against a database whose recorded revision is
not present in the documented baseline-replacement mapping above, the upgrade
guard will halt before applying any schema change and will emit an error
identifying the unrecognised starting revision.  The database schema and
recorded revision will remain unchanged.

Requirements: 1.5, 7.1, 7.4, 7.5
"""

from alembic import op


# revision identifiers, used by Alembic
revision = 'b3c4d5e6f7a1'
down_revision = ('a2b3c4d5e6f7', 's0t1u2v3w4x5')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op — this is a squash/marker revision only.

    All schema work was performed by prior revisions in the chain.
    This revision exists solely to establish a single, unambiguous
    Migration_Head after the clean-baseline consolidation.
    """
    pass


def downgrade() -> None:
    """No-op — no schema objects were created by upgrade().

    Because upgrade() performs no schema changes, there is nothing
    to reverse.  Downgrading past this marker simply advances the
    recorded revision pointer back to the prior head (a2b3c4d5e6f7).
    """
    pass
