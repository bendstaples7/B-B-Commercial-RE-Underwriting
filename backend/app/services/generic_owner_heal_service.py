"""Clear assessor/listing placeholder owner names and unstage cold mail.

Canonical heal for stubs such as ``Taxpayer of`` / ``TAXPAYER OF 123 MAIN``:

1. Null flat ``owner_*`` when the display is placeholder-only
2. Unlink owner contacts whose display is placeholder-only
3. Remove staged ``MailQueueItem`` rows when cold mail is blocked for the lead
4. Timeline + optional rescore so ``mail_ready`` becomes ``enrich_data``

Used by ``scripts/heal_generic_owner_names.py``. Deploy applies the same class
of fix via Alembic ``gen_own_20260910`` (Core SQL).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, func

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.mail_queue_item import MailQueueItem
from app.models.property_contact import PropertyContact
from app.services.entity_owner_policy import cold_mail_block_reason
from app.services.plugins.owner_name_utils import (
    contact_display_name,
    is_placeholder_owner_name,
)

logger = logging.getLogger(__name__)

HEAL_ACTOR = 'heal_generic_owner_names'
HEAL_REASON = 'generic_owner_placeholder'
_VALIDATION_ERROR_MAX = 500
_MARKER = 'generic_owner_placeholder'


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


def _name_column_prefilter(*columns):
    """SQL OR clauses matching common placeholder substrings on name columns."""
    clauses = []
    for col in columns:
        clauses.extend([
            col.ilike('%taxpayer%'),
            col.ilike('%owner of record%'),
            col.ilike('%unknown owner%'),
            col.ilike('%current resident%'),
            col.ilike('%for sale by owner%'),
            col.ilike('%the taxpayer%'),
            col.ilike('%owner unknown%'),
            col.ilike('%name unknown%'),
            func.lower(func.trim(func.coalesce(col, ''))).in_(
                ('n/a', 'na', 'fsbo', 'taxpayer'),
            ),
        ])
    return clauses


def _concat_prefilter(first_col, last_col):
    """Match phrases that may split across first/last (e.g. Taxpayer / of)."""
    joined = func.concat_ws(
        ' ',
        func.nullif(func.trim(func.coalesce(first_col, '')), ''),
        func.nullif(func.trim(func.coalesce(last_col, '')), ''),
    )
    return [
        joined.ilike('%taxpayer of%'),
        joined.ilike('%owner of record%'),
        joined.ilike('%unknown owner%'),
        joined.ilike('%current resident%'),
        joined.ilike('%for sale by owner%'),
        joined.ilike('%the taxpayer%'),
        joined.ilike('%owner unknown%'),
        joined.ilike('%name unknown%'),
    ]


class GenericOwnerHealService:
    """Remove placeholder owner identities and pull leads out of mail staging."""

    def candidate_query(self):
        """SQL prefilter: flats, owner_2, and linked owner Contacts."""
        contact_exists = (
            db.session.query(PropertyContact.id)
            .join(Contact, Contact.id == PropertyContact.contact_id)
            .filter(
                PropertyContact.property_id == Lead.id,
                PropertyContact.role == 'owner',
                or_(
                    *_name_column_prefilter(Contact.first_name, Contact.last_name),
                    *_concat_prefilter(Contact.first_name, Contact.last_name),
                ),
            )
            .exists()
        )
        return (
            Lead.query.filter(
                or_(
                    *_name_column_prefilter(
                        Lead.owner_first_name,
                        Lead.owner_last_name,
                        Lead.owner_2_first_name,
                        Lead.owner_2_last_name,
                    ),
                    *_concat_prefilter(Lead.owner_first_name, Lead.owner_last_name),
                    *_concat_prefilter(
                        Lead.owner_2_first_name, Lead.owner_2_last_name,
                    ),
                    contact_exists,
                ),
            )
            .order_by(Lead.id)
        )

    def is_heal_candidate(self, lead: Lead) -> bool:
        flat = _flat_display(lead)
        if flat and is_placeholder_owner_name(flat):
            return True
        owner2 = _owner2_display(lead)
        if owner2 and is_placeholder_owner_name(owner2):
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

        # SQL prefilter is intentionally broad (hybrids like "Sam For Sale By
        # Owner" match). Page until we collect ``limit`` post-filtered rows.
        if limit is None:
            return [
                lead for lead in self.candidate_query().all()
                if self.is_heal_candidate(lead)
            ]

        out: list[Lead] = []
        offset = 0
        batch_size = max(limit * 5, 50)
        while len(out) < limit:
            batch = (
                self.candidate_query()
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            for lead in batch:
                if self.is_heal_candidate(lead):
                    out.append(lead)
                    if len(out) >= limit:
                        break
            offset += len(batch)
            if len(batch) < batch_size:
                break
        return out[:limit]

    def _clear_flat_placeholder(self, lead: Lead) -> list[str]:
        cleared: list[str] = []
        flat = _flat_display(lead)
        if flat and is_placeholder_owner_name(flat):
            cleared.append(flat)
            # owner_first_name is NOT NULL in the initial schema — keep ''.
            lead.owner_first_name = ''
            lead.owner_last_name = None
        owner2 = _owner2_display(lead)
        if owner2 and is_placeholder_owner_name(owner2):
            cleared.append(owner2)
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

    def _should_unstage_mail(self, lead: Lead) -> bool:
        """Unstage when cold-mail policy still blocks the lead for any reason.

        Placeholder heals often sit behind a higher-priority blocker (tax
        exempt, nonprofit). Still unstage those. Commercial entity orgs return
        ``None`` and may cold-mail the LLC address — keep their queue items.
        """
        return cold_mail_block_reason(lead) is not None

    def _append_validation_marker(self, existing: str | None) -> str:
        if not (existing or '').strip():
            return _MARKER
        combined = f'{existing}; {_MARKER}'
        if len(combined) <= _VALIDATION_ERROR_MAX:
            return combined
        keep = _VALIDATION_ERROR_MAX - len(f'; {_MARKER}')
        return f'{(existing or "")[:max(keep, 0)]}; {_MARKER}'

    def _remove_queued_mail(self, lead: Lead) -> int:
        if not self._should_unstage_mail(lead):
            return 0
        queued = MailQueueItem.query.filter_by(
            lead_id=lead.id,
            status='queued',
        ).all()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for item in queued:
            item.status = 'removed'
            item.updated_at = now
            item.validation_error = self._append_validation_marker(
                item.validation_error,
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

        before = (
            (_flat_display(lead) if _flat_display(lead) else '')
            or (_owner2_display(lead) if _owner2_display(lead) else '')
            or 'placeholder'
        )
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

        # Commit heal before best-effort rescoring so a scoring failure cannot
        # roll back the cleared names / unstaged queue rows.
        if commit or rescore:
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
            # Commit each heal before optional rescore (see heal_lead).
            summary = self.heal_lead(lead, rescore=rescore, commit=True)
            if summary['healed']:
                healed += 1
                rows.append(summary)
        return {
            'scanned': len(candidates),
            'healed': healed,
            'dry_run': False,
            'rows': rows[:100],
        }
