"""HubSpotTimelineImportService — imports HubSpot activities as LeadTimelineEntry rows."""
from datetime import datetime, timedelta, timezone

from app import db
from app.models import Lead, LeadTimelineEntry


# Mapping from HubSpot activity type to timeline event_type
_HUBSPOT_TYPE_TO_EVENT_TYPE = {
    'NOTE': 'hubspot_note',
    'CALL': 'hubspot_call',
    'TASK': 'hubspot_task',
    'DEAL_STAGE_CHANGE': 'hubspot_deal_stage',
    # Fallback for unknown types
    'EMAIL': 'hubspot_note',
    'MEETING': 'hubspot_note',
}


class HubSpotTimelineImportService:
    """Imports HubSpot activity records as LeadTimelineEntry rows."""

    def import_activities_for_lead(
        self,
        lead_id: int,
        hubspot_activities: list[dict],
    ) -> int:
        """Import HubSpot activities for a lead.

        Maps HubSpot record types to LeadTimelineEntry rows with source='hubspot'.
        Deduplicates by hubspot_activity_id.
        Returns count of new entries written.
        Updates last_hubspot_sync_at and hubspot_deal_stage on the lead.
        Sets review_required=True if new entries were written.
        """
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        # Get existing hubspot_activity_ids for this lead to deduplicate
        existing_ids = set(
            row[0]
            for row in db.session.query(LeadTimelineEntry.hubspot_activity_id)
            .filter(
                LeadTimelineEntry.lead_id == lead_id,
                LeadTimelineEntry.source == 'hubspot',
                LeadTimelineEntry.hubspot_activity_id.isnot(None),
            )
            .all()
        )

        new_entries_count = 0
        latest_deal_stage = None

        for activity in hubspot_activities:
            activity_id = str(activity.get('id', ''))
            if not activity_id or activity_id in existing_ids:
                continue

            activity_type = activity.get('type', 'NOTE').upper()
            event_type = _HUBSPOT_TYPE_TO_EVENT_TYPE.get(activity_type, 'hubspot_note')

            # Parse occurred_at from HubSpot timestamp (milliseconds epoch or ISO string)
            occurred_at_raw = activity.get('occurred_at') or activity.get('timestamp')
            if isinstance(occurred_at_raw, (int, float)):
                occurred_at = datetime.fromtimestamp(occurred_at_raw / 1000, tz=timezone.utc)
            elif isinstance(occurred_at_raw, str):
                try:
                    occurred_at = datetime.fromisoformat(occurred_at_raw.replace('Z', '+00:00'))
                except ValueError:
                    occurred_at = datetime.now(timezone.utc)
            else:
                occurred_at = datetime.now(timezone.utc)

            # Build summary from activity body/title
            body = activity.get('body') or activity.get('title') or activity.get('subject') or ''
            summary = body[:500] if body else f"HubSpot {activity_type.lower()} activity"

            # Track deal stage changes
            if activity_type == 'DEAL_STAGE_CHANGE':
                latest_deal_stage = activity.get('deal_stage') or activity.get('to_stage')

            entry = LeadTimelineEntry(
                lead_id=lead_id,
                event_type=event_type,
                occurred_at=occurred_at,
                source='hubspot',
                actor='HubSpot',
                summary=summary,
                event_metadata=activity,
                hubspot_activity_id=activity_id,
            )
            db.session.add(entry)
            existing_ids.add(activity_id)
            new_entries_count += 1

        # Update lead signals
        lead.last_hubspot_sync_at = datetime.now(timezone.utc)
        if latest_deal_stage:
            lead.hubspot_deal_stage = latest_deal_stage
        if new_entries_count > 0:
            lead.review_required = True
            lead.review_reason = 'New HubSpot activity'
            lead.review_triggered_at = datetime.now(timezone.utc)

        db.session.add(lead)
        db.session.commit()

        return new_entries_count

    def derive_is_warm(self, lead_id: int) -> bool:
        """Evaluate is_warm signal from imported HubSpot call records.

        Returns True iff at least one call with outcome='connected' and
        occurred_at within the past 180 days exists.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)

        # Look for hubspot_call entries with 'connected' in their metadata
        entries = (
            LeadTimelineEntry.query
            .filter(
                LeadTimelineEntry.lead_id == lead_id,
                LeadTimelineEntry.event_type == 'hubspot_call',
                LeadTimelineEntry.source == 'hubspot',
                LeadTimelineEntry.occurred_at >= cutoff,
            )
            .all()
        )

        for entry in entries:
            metadata = entry.event_metadata or {}
            outcome = (
                metadata.get('outcome') or
                metadata.get('disposition') or
                metadata.get('call_outcome') or
                ''
            ).lower()
            if 'connected' in outcome or outcome == 'answered':
                return True

        return False
