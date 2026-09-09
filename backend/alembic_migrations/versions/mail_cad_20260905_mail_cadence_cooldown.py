"""Mark mail cadence revision; data heal runs post-deploy.

Revision ID: mail_cad_20260905
Revises: chan_roi_cascade_0831
Create Date: 2026-09-05

Originally this revision called ``heal_mail_cadence_cooldown`` inside the
Alembic transaction. On production that heal exceeded Deploy's 15-minute
migration timeout (exit 124) while scanning last-mailed for every
``mail_ready`` / rematch / queued lead.

The revision id stays in the chain so ``score_cal_20260907`` still follows.
Runtime Ready-to-Mail already enforces the 90-day gate; the idempotent heal
runs from ``scripts/heal_mail_cadence_cooldown.py`` after ``upgrade head``.
"""


revision = 'mail_cad_20260905'
down_revision = 'chan_roi_cascade_0831'
branch_labels = None
depends_on = None


def upgrade():
    # Intentionally empty: heavy data heal is post-deploy (see module docstring).
    print(
        'mail_cad_20260905: stamped — cadence data heal deferred to '
        'backend/scripts/heal_mail_cadence_cooldown.py',
        flush=True,
    )


def downgrade():
    # Cooldown is application logic; no schema to reverse.
    pass
