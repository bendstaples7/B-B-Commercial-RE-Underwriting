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

# Safe integer parse for legacy JSON mail_campaign_id values. Rejects empty,
# non-digits, and values outside a signed 32-bit int before casting.
_SAFE_CAMPAIGN_ID = """
CASE
    WHEN COALESCE(e.metadata->>'mail_campaign_id', '') ~ '^[0-9]{1,9}$'
         AND (e.metadata->>'mail_campaign_id')::bigint
               BETWEEN 1 AND 2147483647
    THEN (e.metadata->>'mail_campaign_id')::integer
    ELSE NULL
END
"""


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
    op.execute(f"""
        INSERT INTO mail_campaign_lead_attributions (
            lead_id, mail_campaign_id, created_at
        )
        SELECT DISTINCT
            e.lead_id,
            campaign_id,
            timezone('utc', now())
        FROM (
            SELECT
                e.lead_id,
                {_SAFE_CAMPAIGN_ID} AS campaign_id
            FROM lead_timeline_entries e
            WHERE e.is_deleted = false
              AND LOWER(COALESCE(e.metadata->>'attributed_to_mail', ''))
                    IN ('true', 't', '1')
        ) AS e
        JOIN mail_campaigns c ON c.id = e.campaign_id
        WHERE e.campaign_id IS NOT NULL
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
    # Reverse only rows this migration stamped. Live attributions stay.
    op.execute(f"""
        WITH stamped AS (
            SELECT DISTINCT
                e.lead_id,
                {_SAFE_CAMPAIGN_ID} AS campaign_id
            FROM lead_timeline_entries e
            WHERE e.metadata->>'mail_attribution_source' = 'inbound_after_mailer'
        ),
        per_campaign AS (
            SELECT campaign_id, COUNT(*)::integer AS n
            FROM stamped
            WHERE campaign_id IS NOT NULL
            GROUP BY campaign_id
        )
        UPDATE mail_campaigns AS c
        SET response_count = GREATEST(0, COALESCE(c.response_count, 0) - p.n),
            updated_at = timezone('utc', now())
        FROM per_campaign p
        WHERE c.id = p.campaign_id
    """)
    op.execute("""
        UPDATE lead_timeline_entries e
        SET metadata = (
            CASE
                WHEN jsonb_typeof(COALESCE(e.metadata::jsonb, '{}'::jsonb)) = 'object'
                THEN COALESCE(e.metadata::jsonb, '{}'::jsonb)
                ELSE '{}'::jsonb
            END
            - 'mail_campaign_id'
            - 'attributed_to_mail'
            - 'mail_attribution_source'
        )::json
        WHERE e.metadata->>'mail_attribution_source' = 'inbound_after_mailer'
    """)
    op.execute('DROP TABLE IF EXISTS mail_campaign_lead_attributions')
