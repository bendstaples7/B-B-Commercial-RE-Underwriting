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
    #
    # Flask-SQLAlchemy 3.1 Session.get_bind() always prefers db.engines[None]
    # and ignores session.bind. Install a plain SQLAlchemy Session bound to
    # op.get_bind() into the scoped registry so ORM writes join Alembic's txn.
    from alembic import op
    from sqlalchemy.orm import Session

    from app import db
    from app.services.mail_task_lifecycle_service import heal_mail_cadence_cooldown

    bind = op.get_bind()
    db.session.remove()
    migration_session = Session(bind=bind)
    db.session.registry.set(migration_session)
    try:
        result = heal_mail_cadence_cooldown(commit=False)
        migration_session.flush()
    except Exception:
        migration_session.rollback()
        raise
    finally:
        db.session.remove()

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
