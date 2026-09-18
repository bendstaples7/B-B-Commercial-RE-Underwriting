"""Convert stored HubSpot MEETING engagements onto the Command Center timeline.

Revision ID: hs_mtg_bf_20260918
Revises: hs_mtg_20260918
Create Date: 2026-09-18

Idempotent: convert_engagement skips meetings that already have an Interaction,
and HubSpotTimelineImportService dedupes by hubspot_activity_id. mark_review is
False so historical meetings do not flood Needs Review.
"""
from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import func

logger = logging.getLogger('alembic.runtime.migration')

revision = 'hs_mtg_bf_20260918'
down_revision = 'hs_mtg_20260918'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    from app.models.hubspot_engagement import HubSpotEngagement
    from app.models.interaction import Interaction
    from app.models.interaction_association import InteractionAssociation
    from app.services.hubspot_activity_converter_service import (
        HubSpotActivityConverterService,
    )
    from app.services.hubspot_timeline_import_service import (
        HubSpotTimelineImportService,
    )

    converter = HubSpotActivityConverterService()
    timeline = HubSpotTimelineImportService()

    meetings = (
        HubSpotEngagement.query
        .filter(func.upper(HubSpotEngagement.engagement_type) == 'MEETING')
        .all()
    )
    lead_ids: set[int] = set()
    converted = 0
    for engagement in meetings:
        result = converter.convert_engagement(engagement)
        interaction = result
        if interaction is None:
            interaction = Interaction.query.filter_by(
                hubspot_engagement_id=str(engagement.hubspot_id),
            ).first()
        else:
            converted += 1
        if interaction is None:
            continue
        for assoc in InteractionAssociation.query.filter_by(
            interaction_id=interaction.id,
            target_type='lead',
        ).all():
            if assoc.target_id is not None:
                lead_ids.add(int(assoc.target_id))

    bridged = 0
    for lead_id in sorted(lead_ids):
        bridged += timeline.sync_lead_from_interactions(
            lead_id,
            mark_review=False,
        )

    logger.info(
        "HubSpot meeting backfill: engagements=%d converted=%d leads=%d new_timeline=%d",
        len(meetings),
        converted,
        len(lead_ids),
        bridged,
    )


def downgrade():
    # Do not delete imported activity; meetings are source-of-truth CRM history.
    pass
