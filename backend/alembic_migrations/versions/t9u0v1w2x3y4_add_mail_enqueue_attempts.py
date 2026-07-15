"""Add durable direct-mail enqueue attempt audit.

Revision ID: t9u0v1w2x3y4
Revises: s9t0u1v2w3x4
"""

from alembic import op
import sqlalchemy as sa

from app.services.address_parse_service import parse_embedded_us_address


revision = 't9u0v1w2x3y4'
down_revision = 's9t0u1v2w3x4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mail_enqueue_attempts (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(100) NOT NULL,
            source_queue VARCHAR(100),
            requested_count INTEGER NOT NULL,
            added_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            invalid_count INTEGER NOT NULL DEFAULT 0,
            results JSON NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_mail_enqueue_attempts_user_created
        ON mail_enqueue_attempts (user_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_mail_enqueue_attempts_created_at
        ON mail_enqueue_attempts (created_at)
        """
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        """
        SELECT id, mailing_address, mailing_city, mailing_state, mailing_zip
        FROM leads
        WHERE NULLIF(BTRIM(mailing_address), '') IS NOT NULL
          AND (
            NULLIF(BTRIM(mailing_city), '') IS NULL
            OR NULLIF(BTRIM(mailing_state), '') IS NULL
            OR NULLIF(BTRIM(mailing_zip), '') IS NULL
          )
        """
    )).mappings()
    updates = []
    for row in rows:
        parsed = parse_embedded_us_address(row['mailing_address'])
        if parsed is None:
            continue
        _street, city, state, zip_code = parsed
        updates.append({
            'lead_id': row['id'],
            'city': row['mailing_city'] or city,
            'state': row['mailing_state'] or state,
            'zip_code': row['mailing_zip'] or zip_code,
        })
    if updates:
        bind.execute(
            sa.text(
                """
                UPDATE leads
                SET mailing_city = :city,
                    mailing_state = :state,
                    mailing_zip = :zip_code
                WHERE id = :lead_id
                """
            ),
            updates,
        )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_mail_enqueue_attempts_created_at")
    op.execute("DROP INDEX IF EXISTS ix_mail_enqueue_attempts_user_created")
    op.execute("DROP TABLE IF EXISTS mail_enqueue_attempts")
