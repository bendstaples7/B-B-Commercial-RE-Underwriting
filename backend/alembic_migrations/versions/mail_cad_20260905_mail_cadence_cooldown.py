"""Heal quarterly mail cadence: rematch dues + rescore stale mail_ready.

Revision ID: mail_cad_20260905
Revises: chan_roi_cascade_0831
Create Date: 2026-09-05

Idempotent data migration: open rematch tasks get due_date = last_mailed + 90,
and leads still ``mail_ready`` inside that window are rescored out of Ready to Mail.
"""


revision = 'mail_cad_20260905'
down_revision = 'chan_roi_cascade_0831'
branch_labels = None
depends_on = None


def upgrade():
    # Keep the idempotent data heal inside Alembic's transaction.
    from alembic import op
    from app import db
    from app.services.mail_task_lifecycle_service import heal_mail_cadence_cooldown

    bind = op.get_bind()
    session = db.session()
    previous_bind = session.bind
    session.bind = bind
    try:
        result = heal_mail_cadence_cooldown(commit=False)
        db.session.flush()
    finally:
        session.bind = previous_bind
    print(
        'mail_cad_20260905: '
        f"dues_fixed={result['rematch_dues_fixed']} "
        f"rescored={result['rescored']} "
        f"removed_queue={result.get('removed_queue_items', 0)}",
        flush=True,
    )


def downgrade():
    # Cooldown is application logic; no schema to reverse.
    pass
