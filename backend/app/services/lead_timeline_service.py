"""LeadTimelineService — append-only activity log for leads."""
from datetime import datetime, timezone

from app import db
from app.models import LeadTimelineEntry
from app.exceptions import ResourceNotFoundError


class LeadTimelineService:
    """Manages the append-only timeline of activity for leads."""

    def append(
        self,
        lead_id: int,
        event_type: str,
        actor: str,
        summary: str,
        metadata: dict | None = None,
        occurred_at: datetime | None = None,
        source: str = 'manual',
        hubspot_activity_id: str | None = None,
    ) -> LeadTimelineEntry:
        """Append a new entry to the lead's timeline."""
        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type=event_type,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            source=source,
            actor=actor,
            summary=summary[:500],  # enforce 500-char limit
            event_metadata=metadata,
            hubspot_activity_id=hubspot_activity_id,
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    def get_page(
        self,
        lead_id: int,
        page: int = 1,
        per_page: int = 25,
    ) -> tuple[list, int]:
        """Return a paginated page of timeline entries in reverse-chronological order.

        Excludes soft-deleted entries from display but retains them in DB.
        Returns (entries, total_count).
        """
        query = (
            LeadTimelineEntry.query
            .filter_by(lead_id=lead_id, is_deleted=False)
            .order_by(LeadTimelineEntry.occurred_at.desc())
        )
        total = query.count()
        entries = query.offset((page - 1) * per_page).limit(per_page).all()
        return entries, total

    def soft_delete(self, entry_id: int, actor: str) -> LeadTimelineEntry:
        """Soft-delete a native timeline entry.

        Replaces summary with '[deleted]', preserves all other fields.
        Raises an error if the entry is HubSpot-sourced.
        """
        entry = LeadTimelineEntry.query.get(entry_id)
        if entry is None:
            raise ResourceNotFoundError(f"Timeline entry {entry_id} not found")

        if entry.source == 'hubspot':
            raise ValueError("HubSpot-sourced timeline entries cannot be deleted.")

        entry.summary = '[deleted]'
        entry.is_deleted = True
        db.session.add(entry)
        db.session.commit()
        return entry
