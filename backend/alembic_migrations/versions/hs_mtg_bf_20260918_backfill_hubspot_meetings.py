"""Convert stored HubSpot MEETING engagements onto the Command Center timeline.

Revision ID: hs_mtg_bf_20260918
Revises: hs_mtg_20260918
Create Date: 2026-09-18

Pure SQL (Alembic purity): no app factory / ContactService. Deploy applies
this so historical meetings appear without a manual script.

Idempotent: skips meetings that already have an Interaction (unique
hubspot_engagement_id) and timeline rows that already have hubspot_activity_id.
Shared meetings attach to every confirmed match, then the globally unique
timeline id keeps the lowest lead_id (same as import_activities_for_lead).
mark_review is not applied — historical meetings must not flood Needs Review.
"""
from __future__ import annotations

from alembic import op

revision = 'hs_mtg_bf_20260918'
down_revision = 'hs_mtg_20260918'
branch_labels = None
depends_on = None


_MEETING_ENGAGEMENTS = """
    SELECT
        he.hubspot_id,
        he.raw_payload,
        LEFT(
            BTRIM(
                regexp_replace(
                    regexp_replace(
                        COALESCE(
                            NULLIF(BTRIM(he.raw_payload #>> '{metadata,body}'), ''),
                            NULLIF(BTRIM(he.raw_payload #>> '{engagement,bodyPreview}'), ''),
                            NULLIF(BTRIM(he.raw_payload #>> '{metadata,title}'), ''),
                            NULLIF(BTRIM(he.raw_payload #>> '{metadata,subject}'), ''),
                            ''
                        ),
                        '<[^>]+>',
                        '',
                        'g'
                    ),
                    '&nbsp;',
                    ' ',
                    'g'
                )
            ),
            10000
        ) AS body,
        COALESCE(
            CASE
                WHEN COALESCE(
                    he.raw_payload #>> '{metadata,startTime}',
                    he.raw_payload #>> '{engagement,timestamp}',
                    he.raw_payload #>> '{engagement,createdAt}'
                ) ~ '^[0-9]+(\\.[0-9]+)?$'
                THEN (
                    to_timestamp(
                        (
                            COALESCE(
                                he.raw_payload #>> '{metadata,startTime}',
                                he.raw_payload #>> '{engagement,timestamp}',
                                he.raw_payload #>> '{engagement,createdAt}'
                            )
                        )::numeric / 1000.0
                    ) AT TIME ZONE 'UTC'
                )
                ELSE NULL
            END,
            timezone('utc', now())
        ) AS occurred_at
    FROM hubspot_engagements he
    WHERE upper(he.engagement_type) = 'MEETING'
"""

_ASSOC_IDS = """
    SELECT
        he.hubspot_id,
        rec.record_type,
        rec.hs_id
    FROM hubspot_engagements he
    CROSS JOIN LATERAL (
        SELECT 'deal'::text AS record_type, elem #>> '{}' AS hs_id
        FROM json_array_elements(
            CASE
                WHEN json_typeof(he.raw_payload #> '{associations,dealIds}') = 'array'
                THEN he.raw_payload #> '{associations,dealIds}'
                ELSE '[]'::json
            END
        ) AS elem
        UNION ALL
        SELECT 'contact'::text, elem #>> '{}'
        FROM json_array_elements(
            CASE
                WHEN json_typeof(he.raw_payload #> '{associations,contactIds}') = 'array'
                THEN he.raw_payload #> '{associations,contactIds}'
                ELSE '[]'::json
            END
        ) AS elem
        UNION ALL
        SELECT 'company'::text, elem #>> '{}'
        FROM json_array_elements(
            CASE
                WHEN json_typeof(he.raw_payload #> '{associations,companyIds}') = 'array'
                THEN he.raw_payload #> '{associations,companyIds}'
                ELSE '[]'::json
            END
        ) AS elem
    ) rec
    WHERE upper(he.engagement_type) = 'MEETING'
      AND rec.hs_id IS NOT NULL AND rec.hs_id <> ''
"""


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    op.execute(
        f"""
        INSERT INTO interactions (
            interaction_type,
            body,
            occurred_at,
            source,
            hubspot_engagement_id,
            raw_payload,
            is_orphaned,
            created_at,
            updated_at
        )
        SELECT
            'meeting',
            COALESCE(me.body, ''),
            me.occurred_at,
            'hubspot_import',
            me.hubspot_id,
            me.raw_payload,
            true,
            timezone('utc', now()),
            timezone('utc', now())
        FROM ({_MEETING_ENGAGEMENTS}) me
        WHERE NOT EXISTS (
            SELECT 1
            FROM interactions i
            WHERE i.hubspot_engagement_id = me.hubspot_id
        )
        """
    )

    op.execute(
        f"""
        INSERT INTO interaction_associations (interaction_id, target_type, target_id)
        SELECT DISTINCT
            i.id,
            hm.internal_record_type,
            hm.internal_record_id
        FROM interactions i
        JOIN hubspot_engagements he ON he.hubspot_id = i.hubspot_engagement_id
        JOIN ({_ASSOC_IDS}) a ON a.hubspot_id = i.hubspot_engagement_id
        JOIN hubspot_matches hm
          ON hm.hubspot_record_type = a.record_type
         AND hm.hubspot_id = a.hs_id
         AND hm.status = 'confirmed'
         AND hm.internal_record_id IS NOT NULL
         AND hm.internal_record_type IN ('lead', 'organization', 'contact')
        WHERE upper(he.engagement_type) = 'MEETING'
          AND NOT EXISTS (
              SELECT 1
              FROM interaction_associations ia
              WHERE ia.interaction_id = i.id
                AND ia.target_type = hm.internal_record_type
                AND ia.target_id = hm.internal_record_id
          )
        """
    )

    op.execute(
        """
        UPDATE interactions i
        SET is_orphaned = NOT EXISTS (
            SELECT 1
            FROM interaction_associations ia
            WHERE ia.interaction_id = i.id
        )
        FROM hubspot_engagements he
        WHERE i.hubspot_engagement_id = he.hubspot_id
          AND upper(he.engagement_type) = 'MEETING'
        """
    )

    # Globally unique hubspot_activity_id: lowest lead_id wins, matching
    # sync_lead_from_interactions over sorted(lead_ids).
    op.execute(
        """
        INSERT INTO lead_timeline_entries (
            lead_id,
            event_type,
            occurred_at,
            source,
            actor,
            summary,
            metadata,
            hubspot_activity_id,
            is_deleted,
            created_at
        )
        SELECT DISTINCT ON (i.hubspot_engagement_id)
            ia.target_id,
            'hubspot_meeting',
            i.occurred_at,
            'hubspot',
            'HubSpot',
            LEFT(
                COALESCE(NULLIF(BTRIM(i.body), ''), 'HubSpot meeting activity'),
                500
            ),
            json_build_object(
                'id', i.hubspot_engagement_id,
                'type', 'MEETING',
                'body', i.body,
                'meeting_status', COALESCE(
                    he.raw_payload #>> '{metadata,status}',
                    he.raw_payload #>> '{metadata,meetingOutcome}'
                ),
                'occurred_at', to_char(
                    i.occurred_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'
                )
            ),
            i.hubspot_engagement_id,
            false,
            timezone('utc', now())
        FROM interactions i
        JOIN interaction_associations ia
          ON ia.interaction_id = i.id
         AND ia.target_type = 'lead'
        JOIN hubspot_engagements he
          ON he.hubspot_id = i.hubspot_engagement_id
        WHERE upper(he.engagement_type) = 'MEETING'
          AND i.source = 'hubspot_import'
          AND i.hubspot_engagement_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM lead_timeline_entries e
              WHERE e.hubspot_activity_id = i.hubspot_engagement_id
          )
        ORDER BY i.hubspot_engagement_id, ia.target_id
        """
    )


def downgrade():
    pass
