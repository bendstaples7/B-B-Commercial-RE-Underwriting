"""Attribute already-logged inbound calls to the mailer batch they followed.

Revision ID: mail_attr_20260919
Revises: cap_src_20260919
Create Date: 2026-09-19

Channel ROI reads ``mail_campaigns.response_count``. Inbound calls logged on
leads that were in a batch (including queue status ``submitted``) were not
counted unless the user picked a mailer, and the picker hid unconfirmed
sends. This ledger plus backfill makes those responses show up on deploy.

SQL mirrors ``backfill_inbound_mail_responses`` in mail_campaign_service.py.
Alembic revisions cannot import that module.
"""
from alembic import op

revision = 'mail_attr_20260919'
down_revision = 'cap_src_20260919'
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
    # Stamp inbound calls and inbound texts onto the latest attributable
    # batch in the prior 90 days. Already-attributed rows are left alone.
    op.execute("""
        WITH best AS (
            SELECT DISTINCT ON (e.id)
                e.id AS entry_id,
                c.id AS campaign_id
            FROM lead_timeline_entries e
            JOIN mail_queue_items qi
              ON qi.lead_id = e.lead_id
            JOIN mail_campaigns c
              ON c.id = qi.campaign_id
            WHERE e.is_deleted = false
              AND qi.status::text IN ('sent', 'submitted')
              AND c.status::text IN ('submitted', 'processing', 'mailed')
              AND COALESCE(c.submitted_at, c.created_at) <= e.occurred_at
              AND COALESCE(c.submitted_at, c.created_at)
                    >= e.occurred_at - INTERVAL '90 days'
              AND (
                    (
                        e.event_type = 'call_logged'
                        AND e.metadata->>'direction' = 'inbound'
                    )
                    OR (
                        e.event_type = 'note_added'
                        AND e.metadata->>'activity_kind' = 'text'
                    )
                  )
              AND LOWER(COALESCE(e.metadata->>'attributed_to_mail', ''))
                    NOT IN ('true', 't', '1')
            ORDER BY e.id,
                     COALESCE(c.submitted_at, c.created_at) DESC,
                     c.id DESC
        )
        UPDATE lead_timeline_entries e
        SET metadata = (
            CASE
                WHEN jsonb_typeof(COALESCE(e.metadata::jsonb, '{}'::jsonb)) = 'object'
                THEN COALESCE(e.metadata::jsonb, '{}'::jsonb)
                ELSE '{}'::jsonb
            END
            || jsonb_build_object(
                'mail_campaign_id', best.campaign_id,
                'attributed_to_mail', true,
                'mail_attribution_source', 'inbound_after_mailer'
            )
        )::json
        FROM best
        WHERE e.id = best.entry_id
    """)
    op.execute("""
        INSERT INTO mail_campaign_lead_attributions (
            lead_id, mail_campaign_id, created_at
        )
        SELECT DISTINCT
            e.lead_id,
            (e.metadata->>'mail_campaign_id')::integer,
            timezone('utc', now())
        FROM lead_timeline_entries e
        JOIN leads l ON l.id = e.lead_id
        JOIN mail_campaigns c
          ON c.id = (e.metadata->>'mail_campaign_id')::integer
        WHERE e.is_deleted = false
          AND LOWER(COALESCE(e.metadata->>'attributed_to_mail', ''))
                IN ('true', 't', '1')
          AND COALESCE(e.metadata->>'mail_campaign_id', '') ~ '^[0-9]+$'
        ON CONFLICT (lead_id, mail_campaign_id) DO NOTHING
    """)
    op.execute("""
        UPDATE mail_campaigns AS c
        SET response_count = counts.n,
            updated_at = timezone('utc', now())
        FROM (
            SELECT mail_campaign_id, COUNT(*)::integer AS n
            FROM mail_campaign_lead_attributions
            GROUP BY mail_campaign_id
        ) AS counts
        WHERE c.id = counts.mail_campaign_id
          AND counts.n > COALESCE(c.response_count, 0)
    """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute('DROP TABLE IF EXISTS mail_campaign_lead_attributions')
