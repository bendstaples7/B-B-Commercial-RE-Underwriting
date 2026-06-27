"""PhoneConfidenceService — per-phone confidence tracking and HubSpot annotation import."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text

from app import db
from app.models.contact_phone import ContactPhone
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.property_contact import PropertyContact

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE = 50
MIN_VIABLE_CONFIDENCE = 10


class PhoneConfidenceService:
    """Canonical service for phone confidence scores and HubSpot phone annotations."""

    @staticmethod
    def normalize_phone(value: str | None) -> str:
        return re.sub(r'\D', '', value or '')

    @staticmethod
    def parse_hubspot_phone_line(line: str) -> tuple[str | None, str | None]:
        """Extract phone value and trailing annotation from a HubSpot phone line."""
        line = (line or '').strip()
        if not line:
            return None, None
        line = re.sub(r'^\d+[).]\s*', '', line).strip()
        phone_match = re.match(r'^(\+?[\d\s\(\)\-\.]{7,20}?)(?:\s+[A-Za-z(]|$)', line)
        if not phone_match:
            phone_match = re.match(r'^(\+?[\d\(\)\-\.\s]+)', line)
        if not phone_match:
            return None, None
        phone_val = phone_match.group(1).strip()
        phone_start = line.find(phone_val)
        remainder = line[phone_start + len(phone_val):].strip().strip('()') if phone_start >= 0 else ''
        notes = remainder or None
        if len(PhoneConfidenceService.normalize_phone(phone_val)) < 7:
            return None, notes
        return phone_val, notes

    @staticmethod
    def confidence_from_annotation(note: str | None) -> int:
        if not note:
            return DEFAULT_CONFIDENCE
        lowered = note.lower()
        if 'confirmed' in lowered:
            return 90
        if 'disconnect' in lowered:
            return 5
        return DEFAULT_CONFIDENCE

    @staticmethod
    def confidence_from_outcome(outcome: str, prior: int) -> int:
        if outcome == 'answered':
            return max(prior, 85)
        if outcome == 'wrong_number':
            return 5
        if outcome in ('voicemail', 'no_answer', 'busy'):
            return max(MIN_VIABLE_CONFIDENCE, prior - 15)
        return prior

    @classmethod
    def merge_parsed_phones(
        cls,
        entries: list[tuple[str, str | None, str]],
    ) -> list[tuple[str, str | None, str]]:
        """Dedupe by normalized digits; prefer entries with richer HubSpot annotations."""
        by_digits: dict[str, tuple[str, str | None, str]] = {}
        for value, notes, label in entries:
            digits = cls.normalize_phone(value)
            if len(digits) < 7:
                continue
            existing = by_digits.get(digits)
            if existing is None:
                by_digits[digits] = (value, notes, label)
                continue
            ex_val, ex_notes, ex_label = existing
            if notes and not ex_notes:
                by_digits[digits] = (value, notes, label if label != 'other' else ex_label)
            elif notes and ex_notes:
                if cls.confidence_from_annotation(notes) > cls.confidence_from_annotation(ex_notes):
                    by_digits[digits] = (value, notes, label if label != 'other' else ex_label)
            elif label != 'other' and ex_label == 'other':
                by_digits[digits] = (ex_val, ex_notes, label)
        return list(by_digits.values())

    @classmethod
    def parse_phones_from_hubspot_props(cls, props: dict) -> list[tuple[str, str | None, str]]:
        """Parse and merge all phone fields from a HubSpot contact properties dict."""
        entries: list[tuple[str, str | None, str]] = []
        for key in ('phone', 'mobilephone', 'hs_phone_number'):
            val = (props.get(key) or '').strip()
            if not val:
                continue
            phone_val, notes = cls.parse_hubspot_phone_line(val)
            label = 'mobile' if key == 'mobilephone' else 'other'
            if phone_val:
                entries.append((phone_val, notes, label))
            else:
                entries.append((val, None, label))

        additional_raw = (props.get('additional_phone_numbers') or '').strip()
        if additional_raw:
            for line in additional_raw.splitlines():
                phone_val, notes = cls.parse_hubspot_phone_line(line)
                if phone_val:
                    entries.append((phone_val, notes, 'other'))

        return cls.merge_parsed_phones(entries)

    @classmethod
    def upsert_contact_phone(
        cls,
        contact_id: int,
        value: str,
        *,
        label: str = 'other',
        notes: str | None = None,
        source: str = 'hubspot_import',
    ) -> tuple[ContactPhone | None, bool]:
        """Upsert a contact phone. Returns (row, changed)."""
        digits = cls.normalize_phone(value)
        if len(digits) < 7:
            return None, False

        trimmed = value.strip()[:50]
        for cp in ContactPhone.query.filter_by(contact_id=contact_id).all():
            if cls.normalize_phone(cp.value) != digits:
                continue
            changed = False
            if notes:
                if cp.notes != notes:
                    cp.notes = notes
                    changed = True
                new_score = cls.confidence_from_annotation(notes)
                if cp.confidence_score != new_score:
                    cp.confidence_score = new_score
                    changed = True
            elif cp.confidence_score is None:
                cp.confidence_score = DEFAULT_CONFIDENCE
                changed = True
            if not cp.source:
                cp.source = source
                changed = True
            if label != 'other' and cp.label == 'other':
                cp.label = label
                changed = True
            db.session.add(cp)
            return cp, changed

        cp = ContactPhone(
            contact_id=contact_id,
            value=trimmed,
            label=label,
            notes=notes,
            confidence_score=cls.confidence_from_annotation(notes),
            source=source,
        )
        db.session.add(cp)
        db.session.flush()
        return cp, True

    @classmethod
    def sync_phones_from_hubspot_contact(cls, lead_id: int, contact) -> int:
        """Apply HubSpot phone annotations to relational contact_phones for a lead."""
        contact_id = cls.get_primary_contact_id(lead_id)
        if contact_id is None:
            return 0

        props = (contact.raw_payload or {}).get('properties', {})
        parsed = cls.parse_phones_from_hubspot_props(props)
        updated = 0
        for phone_val, notes, label in parsed:
            _, changed = cls.upsert_contact_phone(
                contact_id,
                phone_val,
                label=label,
                notes=notes,
                source='hubspot_import',
            )
            if changed:
                updated += 1
        return updated

    @classmethod
    def _find_phone_for_lead(cls, lead_id: int, phone_number: str) -> ContactPhone | None:
        digits = cls.normalize_phone(phone_number)
        if not digits:
            return None
        rows = db.session.execute(
            text("""
                SELECT cp.id FROM contact_phones cp
                JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                WHERE pc.property_id = :lead_id
            """),
            {'lead_id': lead_id},
        ).fetchall()
        for (phone_id,) in rows:
            cp = ContactPhone.query.get(phone_id)
            if cp and cls.normalize_phone(cp.value) == digits:
                return cp
        return None

    @classmethod
    def update_from_call(
        cls,
        lead_id: int,
        outcome: str,
        *,
        contact_phone_id: int | None = None,
        phone_number: str | None = None,
    ) -> None:
        cp = None
        if contact_phone_id is not None:
            cp = ContactPhone.query.get(contact_phone_id)
        elif phone_number:
            cp = cls._find_phone_for_lead(lead_id, phone_number)
        if cp is None:
            return
        prior = cp.confidence_score if cp.confidence_score is not None else DEFAULT_CONFIDENCE
        cp.confidence_score = cls.confidence_from_outcome(outcome, prior)
        cp.last_outcome = outcome
        cp.last_called_at = datetime.now(timezone.utc)
        db.session.add(cp)
        cls.refresh_lead_has_phone(lead_id)

    @classmethod
    def refresh_lead_has_phone(cls, lead_id: int) -> None:
        lead = Lead.query.get(lead_id)
        if lead is None:
            return
        scores = [
            row[0]
            for row in db.session.execute(
                text("""
                    SELECT cp.confidence_score FROM contact_phones cp
                    JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                    WHERE pc.property_id = :lead_id
                """),
                {'lead_id': lead_id},
            ).fetchall()
            if row[0] is not None
        ]
        flat_has = any(getattr(lead, f'phone_{i}') for i in range(1, 8))
        if scores:
            lead.has_phone = any(score >= MIN_VIABLE_CONFIDENCE for score in scores)
        else:
            lead.has_phone = flat_has
        db.session.add(lead)

    @classmethod
    def recompute_for_lead(cls, lead_id: int) -> None:
        """Replay call_logged timeline entries to refresh per-phone confidence."""
        entries = (
            LeadTimelineEntry.query
            .filter_by(lead_id=lead_id, event_type='call_logged', is_deleted=False)
            .order_by(LeadTimelineEntry.occurred_at.asc())
            .all()
        )
        for entry in entries:
            meta = entry.event_metadata or {}
            outcome = meta.get('outcome')
            if not outcome:
                continue
            cls.update_from_call(
                lead_id,
                outcome,
                contact_phone_id=meta.get('contact_phone_id'),
                phone_number=meta.get('phone_number'),
            )

    @staticmethod
    def sort_phones_for_display(phones: list[dict]) -> list[dict]:
        return sorted(
            phones,
            key=lambda p: (
                -(p.get('confidence_score') if p.get('confidence_score') is not None else DEFAULT_CONFIDENCE),
                p.get('value') or '',
            ),
        )

    @classmethod
    def build_phones_payload(cls, lead_id: int, lead: Lead) -> list[dict]:
        """Merge relational contact_phones and flat lead columns into structured phones."""
        relational_rows = db.session.execute(
            text("""
                SELECT cp.id, cp.value, cp.label, cp.notes, cp.confidence_score,
                       cp.last_outcome, cp.last_called_at, cp.source
                FROM contact_phones cp
                JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                WHERE pc.property_id = :lead_id
                ORDER BY cp.id
            """),
            {'lead_id': lead_id},
        ).fetchall()

        phones: list[dict] = []
        seen_digits: set[str] = set()

        for row in relational_rows:
            digits = cls.normalize_phone(row[1])
            if not digits or digits in seen_digits:
                continue
            seen_digits.add(digits)
            phones.append({
                'id': row[0],
                'value': row[1],
                'label': row[2],
                'notes': row[3],
                'confidence_score': row[4] if row[4] is not None else DEFAULT_CONFIDENCE,
                'last_outcome': row[5],
                'last_called_at': row[6].isoformat() if row[6] else None,
                'source': row[7],
            })

        for slot in range(1, 8):
            raw = getattr(lead, f'phone_{slot}')
            if not raw or not str(raw).strip():
                continue
            digits = cls.normalize_phone(str(raw))
            if not digits or digits in seen_digits:
                continue
            seen_digits.add(digits)
            phones.append({
                'value': str(raw).strip(),
                'confidence_score': DEFAULT_CONFIDENCE,
            })

        return cls.sort_phones_for_display(phones)

    @classmethod
    def get_primary_contact_id(cls, lead_id: int) -> int | None:
        primary = PropertyContact.query.filter_by(
            property_id=lead_id,
            is_primary=True,
        ).first()
        if primary:
            return primary.contact_id
        any_link = PropertyContact.query.filter_by(property_id=lead_id).first()
        return any_link.contact_id if any_link else None
