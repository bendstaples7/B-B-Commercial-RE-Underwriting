"""HubSpotTimelineImportService — imports HubSpot activities as LeadTimelineEntry rows."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import text as _text

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.helpers.html_text import strip_html_tags
from app.services.helpers.hubspot_call_disposition import (
    format_hubspot_call_summary,
    is_connected_disposition,
    looks_like_uuid,
    resolve_call_disposition_label,
)

logger = logging.getLogger(__name__)


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

# Interaction.interaction_type → HubSpot-style activity type for import_activities_for_lead
_INTERACTION_TYPE_TO_HUBSPOT = {
    'note': 'NOTE',
    'call': 'CALL',
    'email': 'EMAIL',
    'meeting': 'MEETING',
}

# User-visible history bridged to Command Center (tasks use LeadTask instead)
BRIDGE_INTERACTION_TYPES = frozenset(_INTERACTION_TYPE_TO_HUBSPOT.keys())
_BRIDGE_INTERACTION_TYPES = BRIDGE_INTERACTION_TYPES  # alias for internal use

# Activity types that indicate actual contact was made with the owner
_CONTACT_ACTIVITY_TYPES = {'CALL', 'NOTE', 'EMAIL', 'MEETING'}

# Lead statuses that imply no contact has been made yet
_NO_CONTACT_STATUSES = {'mailing_no_contact_made'}

# Only flag Needs Review when a newly imported HubSpot entry is this recent.
# Prevents live convert/webhook from flooding review when years of history bridge in.
_REVIEW_RECENCY_DAYS = 14


class HubSpotTimelineImportService:
    """Imports HubSpot activity records as LeadTimelineEntry rows."""

    @staticmethod
    def interaction_to_activity(interaction) -> Optional[dict]:
        """Map a HubSpot-imported Interaction to an activity dict for import.

        Returns None when the interaction cannot be bridged (missing engagement
        id, unsupported type, or non-hubspot source).
        """
        if interaction is None:
            return None
        if getattr(interaction, 'source', None) != 'hubspot_import':
            return None
        engagement_id = interaction.hubspot_engagement_id
        if not engagement_id:
            return None
        itype = (interaction.interaction_type or '').lower()
        activity_type = _INTERACTION_TYPE_TO_HUBSPOT.get(itype)
        if activity_type is None:
            return None

        occurred_at = interaction.occurred_at
        if isinstance(occurred_at, datetime):
            if occurred_at.tzinfo is None:
                occurred_at_value = occurred_at.replace(tzinfo=timezone.utc).isoformat()
            else:
                occurred_at_value = occurred_at.isoformat()
        else:
            occurred_at_value = occurred_at

        activity = {
            'id': str(engagement_id),
            'type': activity_type,
            'body': strip_html_tags(interaction.body or ''),
            'occurred_at': occurred_at_value,
        }

        # Surface call disposition for derive_is_warm / UI metadata
        raw = interaction.raw_payload or {}
        metadata = raw.get('metadata') if isinstance(raw, dict) else None
        if not isinstance(metadata, dict):
            metadata = {}
        engagement_obj = raw.get('engagement') if isinstance(raw, dict) else None
        if not isinstance(engagement_obj, dict):
            engagement_obj = {}

        if activity_type == 'CALL':
            disposition = metadata.get('disposition') or metadata.get('callOutcome')
            activity['body'] = format_hubspot_call_summary(
                body=strip_html_tags(interaction.body or '') or None,
                title=metadata.get('title'),
                disposition=disposition,
                direction=metadata.get('direction'),
                body_preview=strip_html_tags(engagement_obj.get('bodyPreview') or '') or None,
            )
            label = resolve_call_disposition_label(disposition)
            if label:
                activity['disposition'] = label
                activity['outcome'] = label
            elif disposition is not None and not looks_like_uuid(disposition):
                activity['disposition'] = str(disposition)
                activity['outcome'] = str(disposition)
            for dial_key in (
                'toNumber',
                'fromNumber',
                'phoneNumber',
                'hs_call_to_number',
                'hs_call_from_number',
            ):
                dialed = metadata.get(dial_key)
                if dialed and not isinstance(dialed, (dict, list)):
                    activity['phone_number'] = str(dialed).strip()
                    break
        elif isinstance(metadata, dict) and metadata:
            disposition = (
                metadata.get('disposition')
                or metadata.get('status')
                or metadata.get('callOutcome')
            )
            if disposition is not None and not isinstance(disposition, (dict, list)):
                label = resolve_call_disposition_label(disposition) or (
                    None if looks_like_uuid(disposition) else str(disposition)
                )
                if label:
                    activity['disposition'] = label
                    activity['outcome'] = label

        return activity

    @staticmethod
    def _json_safe_metadata(activity: dict) -> dict:
        """Copy activity dict with only JSON-serializable values for event_metadata."""
        safe = {}
        for key, value in activity.items():
            if isinstance(value, datetime):
                safe[key] = value.isoformat()
            elif isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = value
            else:
                safe[key] = str(value)
        return safe

    def import_activities_for_lead(
        self,
        lead_id: int,
        hubspot_activities: list[dict],
        *,
        mark_review: bool = True,
    ) -> int:
        """Import HubSpot activities for a lead.

        Maps HubSpot record types to LeadTimelineEntry rows with source='hubspot'.
        Deduplicates by hubspot_activity_id.
        Returns count of new entries written.
        Updates last_hubspot_sync_at and hubspot_deal_stage on the lead.
        Sets review_required=True if new entries were written and mark_review=True.
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

        # hubspot_activity_id is globally unique — also skip ids already on other leads
        candidate_ids = [
            str(a.get('id', ''))
            for a in hubspot_activities
            if a.get('id') and str(a.get('id')) not in existing_ids
        ]
        if candidate_ids:
            existing_ids.update(
                row[0]
                for row in db.session.query(LeadTimelineEntry.hubspot_activity_id)
                .filter(LeadTimelineEntry.hubspot_activity_id.in_(candidate_ids))
                .all()
            )

        new_entries_count = 0
        recent_new_entries = 0
        latest_deal_stage = None
        contact_activity_imported = False  # tracks whether any contact-type activity was new
        now = datetime.now(timezone.utc)
        review_cutoff = now - timedelta(days=_REVIEW_RECENCY_DAYS)
        # Apply call confidence after the loop, sorted by occurred_at (list order
        # from HubSpot is not guaranteed chronological).
        pending_call_confidence: list[tuple[datetime, object, object | None, str]] = []

        for activity in hubspot_activities:
            activity_id = str(activity.get('id', ''))
            if not activity_id or activity_id in existing_ids:
                continue

            activity_type = activity.get('type', 'NOTE').upper()
            event_type = _HUBSPOT_TYPE_TO_EVENT_TYPE.get(activity_type, 'hubspot_note')

            # Parse occurred_at from HubSpot timestamp (ms epoch, ISO string, or datetime)
            occurred_at_raw = activity.get('occurred_at') or activity.get('timestamp')
            occurred_at = None
            if isinstance(occurred_at_raw, datetime):
                occurred_at = occurred_at_raw
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            elif isinstance(occurred_at_raw, (int, float)):
                occurred_at = datetime.fromtimestamp(occurred_at_raw / 1000, tz=timezone.utc)
            elif isinstance(occurred_at_raw, str) and occurred_at_raw.strip():
                try:
                    occurred_at = datetime.fromisoformat(occurred_at_raw.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(
                        "HubSpot activity %s has unparseable occurred_at=%r — skipping",
                        activity_id,
                        occurred_at_raw,
                    )
                    continue
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            else:
                logger.warning(
                    "HubSpot activity %s missing occurred_at — skipping",
                    activity_id,
                )
                continue

            # Build summary from activity body/title (always plain text)
            raw_body = activity.get('body') or activity.get('title') or activity.get('subject') or ''
            plain_body = strip_html_tags(raw_body) if raw_body else ''
            summary = plain_body[:500] if plain_body else f"HubSpot {activity_type.lower()} activity"

            # Track deal stage changes
            if activity_type == 'DEAL_STAGE_CHANGE':
                latest_deal_stage = activity.get('deal_stage') or activity.get('to_stage')

            # Track whether a contact-type activity (call, note, email, meeting) was imported
            if activity_type in _CONTACT_ACTIVITY_TYPES:
                contact_activity_imported = True

            meta_activity = dict(activity)
            if plain_body or 'body' in meta_activity:
                meta_activity['body'] = plain_body

            entry = LeadTimelineEntry(
                lead_id=lead_id,
                event_type=event_type,
                occurred_at=occurred_at,
                source='hubspot',
                actor='HubSpot',
                summary=summary,
                event_metadata=self._json_safe_metadata(meta_activity),
                hubspot_activity_id=activity_id,
            )
            db.session.add(entry)
            existing_ids.add(activity_id)
            new_entries_count += 1
            if occurred_at >= review_cutoff:
                recent_new_entries += 1

            # HubSpot CRM_UI calls often omit toNumber — still update confidence
            # on the lead's HubSpot-primary phone from disposition (deferred).
            if event_type == 'hubspot_call':
                pending_call_confidence.append((
                    occurred_at,
                    meta_activity.get('disposition') or meta_activity.get('outcome'),
                    meta_activity.get('phone_number'),
                    activity_id,
                ))

        if pending_call_confidence:
            from app.services.phone_confidence_service import PhoneConfidenceService
            pending_call_confidence.sort(key=lambda row: row[0])
            for _occurred_at, disposition, phone_number, activity_id in pending_call_confidence:
                try:
                    PhoneConfidenceService.apply_hubspot_call_outcome(
                        lead_id,
                        disposition,
                        phone_number=phone_number,
                    )
                except Exception as exc:
                    logger.warning(
                        'HubSpot call confidence update failed for lead %s activity %s: %s',
                        lead_id,
                        activity_id,
                        exc,
                    )

        # Update lead signals — only touch sync timestamp when we actually wrote rows
        # so idempotent re-runs do not mark every lead as freshly HubSpot-synced.
        if new_entries_count > 0:
            lead.last_hubspot_sync_at = now
        if latest_deal_stage:
            # Read-only HubSpot stage mirror; primary pipeline status is lead_status.
            lead.hubspot_deal_stage = latest_deal_stage
        if new_entries_count > 0 and mark_review and recent_new_entries > 0:
            lead.review_required = True
            lead.review_triggered_at = now
            # If HubSpot shows contact activity but status still says no contact made,
            # use a specific review reason so the Needs Review queue surfaces it clearly.
            # Check the interactions table — that's where HubSpot call/note/email data lives.
            if lead.lead_status in _NO_CONTACT_STATUSES:
                has_contact_interaction = db.session.execute(_text("""
                    SELECT 1
                    FROM interactions i
                    JOIN interaction_associations ia ON ia.interaction_id = i.id
                    WHERE ia.target_type = 'lead'
                      AND ia.target_id = :lead_id
                      AND i.interaction_type IN ('call', 'note', 'email', 'meeting')
                    LIMIT 1
                """), {'lead_id': lead_id}).fetchone() is not None
                if has_contact_interaction or contact_activity_imported:
                    lead.review_reason = (
                        'HubSpot shows contact activity but status is still '
                        '"Mailing, No Contact Made" - please update status'
                    )
                else:
                    lead.review_reason = 'New HubSpot activity'
            else:
                lead.review_reason = 'New HubSpot activity'

        db.session.add(lead)
        db.session.commit()

        return new_entries_count

    def sync_lead_from_interactions(
        self,
        lead_id: int,
        *,
        mark_review: bool = True,
        hubspot_engagement_ids: Optional[Iterable[str]] = None,
    ) -> int:
        """Bridge HubSpot Interactions for a lead into LeadTimelineEntry rows.

        Loads lead-associated Interactions with source='hubspot_import' and type
        in note/call/email/meeting, maps them to activity dicts, and imports.
        Idempotent via hubspot_activity_id dedupe.

        When hubspot_engagement_ids is set, only those engagements are considered
        (live/webhook paths). mark_review only flags Needs Review for newly
        imported entries with occurred_at within the last 14 days.

        Returns count of new timeline entries written.
        """
        from app.models import Interaction, InteractionAssociation

        query = (
            db.session.query(Interaction)
            .join(
                InteractionAssociation,
                InteractionAssociation.interaction_id == Interaction.id,
            )
            .filter(
                InteractionAssociation.target_type == 'lead',
                InteractionAssociation.target_id == lead_id,
                Interaction.source == 'hubspot_import',
                Interaction.hubspot_engagement_id.isnot(None),
                Interaction.interaction_type.in_(tuple(_BRIDGE_INTERACTION_TYPES)),
            )
        )
        if hubspot_engagement_ids is not None:
            id_list = [str(i) for i in hubspot_engagement_ids if i]
            if not id_list:
                return 0
            query = query.filter(Interaction.hubspot_engagement_id.in_(id_list))

        interactions = query.order_by(Interaction.occurred_at.asc()).all()

        activities = []
        for interaction in interactions:
            activity = self.interaction_to_activity(interaction)
            if activity is not None:
                activities.append(activity)

        if not activities:
            return 0

        return self.import_activities_for_lead(
            lead_id, activities, mark_review=mark_review
        )

    def sync_leads_from_interactions(
        self,
        lead_ids: Optional[Iterable[int]] = None,
        *,
        mark_review: bool = True,
    ) -> dict:
        """Sync timeline entries for many leads.

        When lead_ids is None, syncs every lead that has a bridgeable HubSpot
        Interaction association.
        Returns ``{lead_id: new_count, ...}`` for leads that were attempted.
        """
        from app.models import Interaction, InteractionAssociation

        if lead_ids is None:
            lead_ids = [
                row[0]
                for row in (
                    db.session.query(InteractionAssociation.target_id)
                    .join(
                        Interaction,
                        Interaction.id == InteractionAssociation.interaction_id,
                    )
                    .filter(
                        InteractionAssociation.target_type == 'lead',
                        Interaction.source == 'hubspot_import',
                        Interaction.hubspot_engagement_id.isnot(None),
                        Interaction.interaction_type.in_(tuple(_BRIDGE_INTERACTION_TYPES)),
                    )
                    .distinct()
                    .all()
                )
            ]

        results: dict[int, int] = {}
        for lid in sorted({int(x) for x in lead_ids if x is not None}):
            try:
                results[lid] = self.sync_lead_from_interactions(
                    lid, mark_review=mark_review
                )
            except Exception as exc:
                db.session.rollback()
                logger.warning(
                    "sync_leads_from_interactions: lead_id=%s failed: %s",
                    lid, exc,
                )
                results[lid] = -1  # sentinel: failed (distinct from 0 = already current)
        return results

    def scrub_html_from_hubspot_entries(self, lead_id: Optional[int] = None) -> int:
        """Rewrite HubSpot timeline summaries/metadata body to plain text.

        Also replaces bare HubSpot disposition UUIDs with readable call summaries
        using engagement metadata when available.
        Idempotent. Returns count of entries updated.
        """
        from app.models import Interaction

        q = LeadTimelineEntry.query.filter(
            LeadTimelineEntry.source == 'hubspot',
            LeadTimelineEntry.is_deleted.is_(False),
        )
        if lead_id is not None:
            q = q.filter(LeadTimelineEntry.lead_id == lead_id)

        updated = 0
        BATCH_SIZE = 200

        def _flush_batch(entries: list) -> int:
            if not entries:
                return 0
            # Prefetch all HubSpot call engagements in the batch so cleanup +
            # disposition rewrite share one query (and UUID detection runs after
            # HTML cleanup below).
            call_ids = [
                str(e.hubspot_activity_id)
                for e in entries
                if e.event_type == 'hubspot_call' and e.hubspot_activity_id
            ]
            by_engagement: dict[str, object] = {}
            if call_ids:
                for interaction in (
                    Interaction.query
                    .filter(Interaction.hubspot_engagement_id.in_(call_ids))
                    .all()
                ):
                    by_engagement[str(interaction.hubspot_engagement_id)] = interaction

            batch_updated = 0
            for entry in entries:
                changed = False
                summary = entry.summary or ''
                meta = dict(entry.event_metadata) if isinstance(entry.event_metadata, dict) else {}

                if '<' in summary:
                    cleaned = strip_html_tags(summary)
                    if cleaned != summary:
                        entry.summary = cleaned[:500] if cleaned else entry.summary
                        summary = entry.summary or ''
                        changed = True

                body = meta.get('body')
                if isinstance(body, str) and '<' in body:
                    cleaned_body = strip_html_tags(body)
                    if cleaned_body != body:
                        meta['body'] = cleaned_body
                        changed = True

                needs_call_rewrite = (
                    entry.event_type == 'hubspot_call'
                    and entry.hubspot_activity_id
                    and (
                        looks_like_uuid(summary)
                        or looks_like_uuid(meta.get('body'))
                        or looks_like_uuid(meta.get('disposition'))
                        or looks_like_uuid(meta.get('outcome'))
                    )
                )
                if needs_call_rewrite:
                    interaction = by_engagement.get(str(entry.hubspot_activity_id))
                    raw = (getattr(interaction, 'raw_payload', None) if interaction else None) or {}
                    metadata = raw.get('metadata') if isinstance(raw, dict) else {}
                    if not isinstance(metadata, dict):
                        metadata = {}
                    engagement_obj = raw.get('engagement') if isinstance(raw, dict) else {}
                    if not isinstance(engagement_obj, dict):
                        engagement_obj = {}
                    disposition = metadata.get('disposition') or meta.get('disposition')
                    new_summary = format_hubspot_call_summary(
                        body=strip_html_tags(metadata.get('body') or '') or None,
                        title=metadata.get('title'),
                        disposition=disposition,
                        direction=metadata.get('direction'),
                        body_preview=strip_html_tags(engagement_obj.get('bodyPreview') or '') or None,
                    )
                    if new_summary and new_summary != entry.summary:
                        entry.summary = new_summary[:500]
                        changed = True
                    label = resolve_call_disposition_label(disposition)
                    if label and (
                        meta.get('disposition') != label or meta.get('outcome') != label
                    ):
                        meta['disposition'] = label
                        meta['outcome'] = label
                        changed = True
                    if entry.summary and meta.get('body') != entry.summary:
                        meta['body'] = entry.summary
                        changed = True

                if changed:
                    entry.event_metadata = meta or entry.event_metadata
                    db.session.add(entry)
                    batch_updated += 1
            if batch_updated:
                db.session.commit()
            return batch_updated

        # Keyset pagination — never commit while a yield_per stream cursor is open
        last_id = 0
        while True:
            page = (
                q.filter(LeadTimelineEntry.id > last_id)
                .order_by(LeadTimelineEntry.id.asc())
                .limit(BATCH_SIZE)
                .all()
            )
            if not page:
                break
            updated += _flush_batch(page)
            last_id = page[-1].id
        return updated

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
            )
            if is_connected_disposition(outcome):
                return True

        return False
