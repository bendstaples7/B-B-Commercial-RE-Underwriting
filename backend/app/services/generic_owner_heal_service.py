"""Clear assessor/listing placeholder owner names and unstage cold mail.

Canonical heal for stubs such as ``Taxpayer of`` / ``TAXPAYER OF 123 MAIN``:

1. Null flat ``owner_*`` when the display is placeholder-only
2. Unlink primary (and other) owner contacts whose display is placeholder-only
3. Remove staged ``MailQueueItem`` rows (status ``removed``)
4. Timeline + optional rescore so ``mail_ready`` becomes ``enrich_data``

Used by Alembic ``gen_own_20260910`` and
``scripts/heal_generic_owner_names.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.mail_queue_item import MailQueueItem
from app.models.property_contact import PropertyContact
from app.services.plugins.owner_name_utils import (
    contact_display_name,
    is_placeholder_owner_name,
)

logger = logging.getLogger(__name__)

HEAL_ACTOR = 'heal_generic_owner_names'
HEAL_REASON = 'generic_owner_placeholder'


def _flat_display(lead: Lead) -> str:
    return contact_display_name(
        getattr(lead, 'owner_first_name', None),
        getattr(lead, 'owner_last_name', None),
    )


def _owner2_display(lead: Lead) -> str:
    return contact_display_name(
        getattr(lead, 'owner_2_first_name', None),
        getattr(lead, 'owner_2_last_name', None),
    )


class GenericOwnerHealService:
    """Remove placeholder owner identities and pull leads out of mail staging."""

    def candidate_query(self):
        """SQL prefilter: names that often contain assessor/listing stubs."""
        return (
            Lead.query.filter(
                or_(
                    Lead.owner_first_name.ilike('%taxpayer%'),
                    Lead.owner_last_name.ilike('%taxpayer%'),
                    Lead.owner_first_name.ilike('%owner of record%'),
                    Lead.owner_last_name.ilike('%owner of record%'),
                    Lead.owner_first_name.ilike('%unknown owner%'),
                    Lead.owner_last_name.ilike('%unknown owner%'),
                    Lead.owner_first_name.ilike('%current resident%'),
                    Lead.owner_last_name.ilike('%current resident%'),
                    Lead.owner_first_name.ilike('%for sale by owner%'),
                    Lead.owner_last_name.ilike('%for sale by owner%'),
                    Lead.owner_first_name.ilike('n/a'),
                    Lead.owner_last_name.ilike('n/a'),
                    Lead.owner_first_name.ilike('na'),
                    Lead.owner_last_name.ilike('na'),
                    Lead.owner_first_name.ilike('fsbo'),
                    Lead.owner_last_name.ilike('fsbo'),
                ),
            )
            .order_by(Lead.id)
        )

    def is_heal_candidate(self, lead: Lead) -> bool:
        if is_placeholder_owner_name(_flat_display(lead)):
            return True
        if is_placeholder_owner_name(_owner2_display(lead)):
            return True
        for link in PropertyContact.query.filter_by(
            property_id=lead.id, role='owner',
        ).all():
            contact = db.session.get(Contact, link.contact_id)
            if contact is None:
                continue
            display = contact_display_name(contact.first_name, contact.last_name)
            if display and is_placeholder_owner_name(display):
                return True
        return False

    def list_candidates(
        self,
        *,
        limit: int | None = None,
        lead_id: int | None = None,
    ) -> list[Lead]:
        if lead_id is not None:
            lead = db.session.get(Lead, lead_id)
            if lead is None or not self.is_heal_candidate(lead):
                return []
            return [lead]

        q = self.candidate_query()
        if limit is not None:
            q = q.limit(max(limit * 5, limit))
        leads = q.all()
        out = [lead for lead in leads if self.is_heal_candidate(lead)]
        if limit is not None:
            return out[:limit]
        return out

    def _clear_flat_placeholder(self, lead: Lead) -> list[str]:
        cleared: list[str] = []
        if is_placeholder_owner_name(_flat_display(lead)):
            if (lead.owner_first_name or '').strip() or (lead.owner_last_name or '').strip():
                cleared.append(
                    contact_display_name(lead.owner_first_name, lead.owner_last_name),
                )
            lead.owner_first_name = None
            lead.owner_last_name = None
        if is_placeholder_owner_name(_owner2_display(lead)):
            if (
                (getattr(lead, 'owner_2_first_name', None) or '').strip()
                or (getattr(lead, 'owner_2_last_name', None) or '').strip()
            ):
                cleared.append(_owner2_display(lead))
            lead.owner_2_first_name = None
            lead.owner_2_last_name = None
        return cleared

    def _unlink_placeholder_owner_contacts(self, lead_id: int) -> list[dict[str, Any]]:
        removed: list[dict[str, Any]] = []
        links = PropertyContact.query.filter_by(
            property_id=lead_id, role='owner',
        ).all()
        for link in links:
            contact = db.session.get(Contact, link.contact_id)
            if contact is None:
                continue
            display = contact_display_name(contact.first_name, contact.last_name)
            if not display or not is_placeholder_owner_name(display):
                continue
            removed.append({
                'contact_id': contact.id,
                'name': display,
                'was_primary': bool(link.is_primary),
            })
            db.session.delete(link)
        return removed

    def _remove_queued_mail(self, lead: Lead) -> int:
        queued = MailQueueItem.query.filter_by(
            lead_id=lead.id,
            status='queued',
        ).all()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for item in queued:
            item.status = 'removed'
            item.updated_at = now
            suffix = 'generic_owner_placeholder'
            item.validation_error = (
                f'{item.validation_error}; {suffix}'
                if item.validation_error
                else suffix
            )
            db.session.add(item)
        if queued:
            lead.up_next_to_mail = False
            try:
                from app.services.mail_task_lifecycle_service import (
                    cancel_pending_mail_follow_up_tasks,
                )
                cancel_pending_mail_follow_up_tasks(
                    lead.id,
                    actor=HEAL_ACTOR,
                    reason=HEAL_REASON,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    'Failed cancelling mail follow-ups for lead %s', lead.id,
                )
        return len(queued)

    def heal_lead(
        self,
        lead: Lead,
        *,
        rescore: bool = True,
        commit: bool = False,
    ) -> dict[str, Any]:
        """Heal one lead. Returns a summary dict (idempotent when already clean)."""
        if not self.is_heal_candidate(lead):
            return {
                'lead_id': lead.id,
                'healed': False,
                'cleared_names': [],
                'unlinked_contacts': [],
                'removed_queue_items': 0,
            }

        before = _flat_display(lead) or _owner2_display(lead) or 'placeholder'
        cleared = self._clear_flat_placeholder(lead)
        unlinked = self._unlink_placeholder_owner_contacts(lead.id)
        removed_queue = self._remove_queued_mail(lead)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.add(
            LeadTimelineEntry(
                lead_id=lead.id,
                event_type='owner_name_changed',
                occurred_at=now,
                source='system',
                actor=HEAL_ACTOR,
                summary=(
                    f'Cleared placeholder owner name ({before!r}) — '
                    'research a real owner before cold mail'
                ),
                event_metadata={
                    'reason': HEAL_REASON,
                    'cleared_names': cleared,
                    'unlinked_contacts': unlinked,
                    'removed_queue_items': removed_queue,
                },
            )
        )
        db.session.add(lead)

        if commit:
            db.session.commit()

        if rescore:
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(lead.id)

        return {
            'lead_id': lead.id,
            'healed': True,
            'cleared_names': cleared,
            'unlinked_contacts': unlinked,
            'removed_queue_items': removed_queue,
        }

    def heal_all(
        self,
        *,
        limit: int | None = None,
        lead_id: int | None = None,
        dry_run: bool = False,
        rescore: bool = True,
    ) -> dict[str, Any]:
        candidates = self.list_candidates(limit=limit, lead_id=lead_id)
        rows: list[dict[str, Any]] = []
        if dry_run:
            for lead in candidates:
                rows.append({
                    'lead_id': lead.id,
                    'flat_name': _flat_display(lead) or None,
                    'owner_2_name': _owner2_display(lead) or None,
                    'recommended_action': lead.recommended_action,
                })
            return {
                'scanned': len(candidates),
                'healed': 0,
                'dry_run': True,
                'rows': rows,
            }

        healed = 0
        for lead in candidates:
            summary = self.heal_lead(lead, rescore=rescore, commit=False)
            if summary['healed']:
                healed += 1
                rows.append(summary)
        db.session.commit()
        return {
            'scanned': len(candidates),
            'healed': healed,
            'dry_run': False,
            'rows': rows[:100],
        }
