"""Attribute already-logged inbound calls to the mailer batch they followed.

Revision ID: mail_attr_20260919
Revises: act_mtg_20260919
Create Date: 2026-09-19

Channel ROI reads ``mail_campaigns.response_count``. Inbound calls logged on
leads that were in a batch (including queue status ``submitted``) were not
counted unless the user picked a mailer, and the picker hid unconfirmed
sends. This ledger plus backfill makes those responses show up on deploy.
"""
from alembic import op
from sqlalchemy.orm import Session

revision = 'mail_attr_20260919'
down_revision = 'act_mtg_20260919'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute("""
        CREATE TABLE IF NOT EXISTS mail_campaign_lead_attributions (
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            mail_campaign_id INTEGER NOT NULL
                REFERENCES mail_campaigns(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (lead_id, mail_campaign_id)
        )
    """)
    session = Session(bind=bind, join_transaction_mode='create_savepoint')
    try:
        from app.services.mail_campaign_service import backfill_inbound_mail_responses
        backfill_inbound_mail_responses(session)
        # Release the savepoint so Alembic's outer transaction keeps the rows.
        session.commit()
    finally:
        session.close()


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute('DROP TABLE IF EXISTS mail_campaign_lead_attributions')
