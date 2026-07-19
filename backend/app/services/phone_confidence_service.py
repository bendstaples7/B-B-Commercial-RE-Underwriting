"""PhoneConfidenceService — per-phone confidence tracking and HubSpot annotation import."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import or_, text

from app import db
from app.models.contact_phone import ContactPhone
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.property_contact import PropertyContact

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE = 50
MIN_VIABLE_CONFIDENCE = 10
HUBSPOT_PRIMARY_NOTE = 'HubSpot primary'


class PhoneConfidenceService:
    """Canonical service for phone confidence scores and HubSpot phone annotations."""

    @staticmethod
    def normalize_phone(value: str | None) -> str:
        return re.sub(r'\D', '', value or '')

    @staticmethod
    def _is_synthetic_hubspot_primary_notes(notes: str | None) -> bool:
        return (notes or '').strip().lower() == HUBSPOT_PRIMARY_NOTE.lower()

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
    def _note_has_word(lowered: str, word: str) -> bool:
        return re.search(rf'(?<![a-z]){re.escape(word)}(?![a-z])', lowered) is not None

    @classmethod
    def _explicit_annotation_score(cls, notes: str | None) -> int | None:
        """Non-default annotation score, excluding synthetic HubSpot-primary marker."""
        if not notes or notes.lower().strip() == 'hubspot primary':
            return None
        score = cls.confidence_from_annotation(notes)
        return score if score != DEFAULT_CONFIDENCE else None

    @classmethod
    def confidence_from_annotation(cls, note: str | None) -> int:
        if not note:
            return DEFAULT_CONFIDENCE
        lowered = note.lower().strip()
        if any(
            phrase in lowered
            for phrase in (
                'wrong number',
                'wrong #',
                'not in service',
                'not good',
            )
        ):
            return 5
        if any(
            cls._note_has_word(lowered, token)
            for token in ('disconnect', 'disconnected', 'dead', 'incorrect', 'wrong')
        ) or re.search(r'(^|[\s(/])(wn|nis)([\s)/]|$)', lowered):
            return 5
        if any(
            cls._note_has_word(lowered, token)
            for token in ('confirmed', 'good', 'verified', 'correct', 'works')
        ):
            return 90
        if any(
            token in lowered
            for token in (
                'son of',
                'daughter',
                'wife',
                'husband',
                'relative',
                'brother',
                'sister',
                'mother',
                'father',
                'family',
            )
        ):
            return 25
        if lowered in ('na', 'n/a') or re.search(r'(^|[\s(])n/?a([\s)]|$)', lowered):
            return 35
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
    def outcome_from_hubspot_disposition(cls, disposition_or_label: object | None) -> str | None:
        """Map HubSpot disposition GUID/label to ``confidence_from_outcome`` keys."""
        from app.services.helpers.hubspot_call_disposition import (
            resolve_call_disposition_label,
        )

        label = (resolve_call_disposition_label(disposition_or_label) or '').lower().strip()
        if not label:
            raw = str(disposition_or_label or '').strip().lower()
            label = raw.replace('_', ' ')
        if label in {'connected', 'answered'}:
            return 'answered'
        if label in {'left voicemail', 'voicemail'}:
            return 'voicemail'
        if label in {'left live message'}:
            return 'voicemail'
        if label in {'no answer', 'no_answer'}:
            return 'no_answer'
        if label == 'busy':
            return 'busy'
        if label in {'wrong number', 'wrong_number'}:
            return 'wrong_number'
        return None

    @classmethod
    def find_hubspot_primary_phone_for_lead(cls, lead_id: int) -> ContactPhone | None:
        """Best HubSpot-primary (or sole hubspot_import) phone on the lead."""
        rows = (
            ContactPhone.query
            .join(PropertyContact, PropertyContact.contact_id == ContactPhone.contact_id)
            .filter(
                PropertyContact.property_id == lead_id,
                or_(
                    PropertyContact.role.is_(None),
                    PropertyContact.role != 'former_owner',
                ),
            )
            .all()
        )
        primary: list[ContactPhone] = []
        hubspot_rows: list[ContactPhone] = []
        for cp in rows:
            notes_l = (cp.notes or '').lower()
            source_l = (str(cp.source) if cp.source is not None else '').lower()
            if 'hubspot primary' in notes_l:
                primary.append(cp)
            if source_l.startswith('hubspot'):
                hubspot_rows.append(cp)
        # Prefer explicit HubSpot-primary notes; otherwise only a sole HubSpot phone.
        if primary:
            pool = primary
        elif len(hubspot_rows) == 1:
            pool = hubspot_rows
        else:
            return None

        def _rank(cp: ContactPhone) -> tuple[int, int]:
            score = cp.confidence_score if cp.confidence_score is not None else DEFAULT_CONFIDENCE
            notes_l = (cp.notes or '').lower()
            preferred = 0 if 'hubspot primary' in notes_l else 1
            return (-score, preferred)

        pool.sort(key=_rank)
        return pool[0]

    @classmethod
    def apply_hubspot_call_outcome(
        cls,
        lead_id: int,
        disposition_or_label: object | None,
        *,
        phone_number: str | None = None,
    ) -> bool:
        """Update confidence from a HubSpot call; fall back to HubSpot-primary phone."""
        outcome = cls.outcome_from_hubspot_disposition(disposition_or_label)
        if not outcome:
            return False
        dialed = (str(phone_number).strip() if phone_number is not None else '') or None
        cp = None
        if dialed:
            cp = cls._find_phone_for_lead(lead_id, dialed)
            if cp is None:
                # Dialed number present but not on the lead — do not mis-attribute.
                logger.info(
                    'HubSpot call outcome skipped for lead %s: unmatched phone %r',
                    lead_id,
                    dialed,
                )
                return False
        else:
            cp = cls.find_hubspot_primary_phone_for_lead(lead_id)
        if cp is None:
            return False
        cls.update_from_call(
            lead_id,
            outcome,
            contact_phone_id=cp.id,
            phone_number=cp.value,
        )
        return True

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

            def _merge_rank(n: str | None) -> tuple[int, int]:
                """Higher tuple wins. Explicit negatives outrank positives."""
                if not n:
                    return (0, 0)
                if n.lower().strip() == HUBSPOT_PRIMARY_NOTE.lower():
                    return (1, 0)
                score = cls.confidence_from_annotation(n)
                if score != DEFAULT_CONFIDENCE:
                    # Prefer lower scores so "disconnected"/WN beat "confirmed".
                    return (3, -score)
                return (2, score)

            if notes and not ex_notes:
                by_digits[digits] = (value, notes, label if label != 'other' else ex_label)
            elif notes and ex_notes:
                if _merge_rank(notes) > _merge_rank(ex_notes):
                    by_digits[digits] = (value, notes, label if label != 'other' else ex_label)
            elif label != 'other' and ex_label == 'other':
                by_digits[digits] = (ex_val, ex_notes, label)
        return list(by_digits.values())

    @classmethod
    def parse_phones_from_hubspot_props(cls, props: dict) -> list[tuple[str, str | None, str]]:
        """Parse and merge all phone fields from a HubSpot contact properties dict."""
        entries: list[tuple[str, str | None, str]] = []
        primary_field_digits: set[str] = set()
        for key in ('phone', 'mobilephone', 'hs_phone_number'):
            val = (props.get(key) or '').strip()
            if not val:
                continue
            phone_val, notes = cls.parse_hubspot_phone_line(val)
            label = 'mobile' if key == 'mobilephone' else 'other'
            if key in ('phone', 'mobilephone'):
                primary_field_digits.add(cls.normalize_phone(phone_val or val))
            if phone_val:
                entries.append((phone_val, notes, label))
            else:
                entries.append((val, notes, label))

        additional_raw = (props.get('additional_phone_numbers') or '').strip()
        if additional_raw:
            for line in additional_raw.splitlines():
                phone_val, notes = cls.parse_hubspot_phone_line(line)
                if phone_val:
                    entries.append((phone_val, notes, 'other'))

        merged = cls.merge_parsed_phones(entries)
        stamped: list[tuple[str, str | None, str]] = []
        for value, notes, label in merged:
            if (
                not notes
                and cls.normalize_phone(value) in primary_field_digits
            ):
                notes = HUBSPOT_PRIMARY_NOTE
            stamped.append((value, notes, label))
        return stamped

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
        notes_l = (notes or '').lower()
        is_hubspot_primary = (
            label in ('mobile',)
            or 'hubspot primary' in notes_l
            or (source == 'hubspot_import' and notes_l.startswith('hubspot primary'))
        )
        # Primary HubSpot phone/mobile fields get a floor of 85 unless annotated lower
        # (WN/NIS stay at annotation score) or unless only the synthetic marker applies.
        annotation_score = cls.confidence_from_annotation(notes)
        explicit_score = cls._explicit_annotation_score(notes)
        synthetic_primary_notes = cls._is_synthetic_hubspot_primary_notes(notes)
        if (
            is_hubspot_primary
            and explicit_score is None
            and annotation_score >= DEFAULT_CONFIDENCE
        ):
            annotation_score = max(annotation_score, 85)
            if not notes or synthetic_primary_notes:
                notes = HUBSPOT_PRIMARY_NOTE
        elif explicit_score is not None:
            annotation_score = explicit_score

        for cp in ContactPhone.query.filter_by(contact_id=contact_id).all():
            if cls.normalize_phone(cp.value) != digits:
                continue
            changed = False
            # Synthetic "HubSpot primary" is a marker, not an annotation — treat like
            # empty notes so outcome-derived low confidence (wrong_number) is kept.
            if notes and not synthetic_primary_notes:
                if cp.notes != notes:
                    cp.notes = notes
                    changed = True
                if cp.confidence_score != annotation_score:
                    cp.confidence_score = annotation_score
                    changed = True
            elif is_hubspot_primary or synthetic_primary_notes:
                preserve_low = (
                    cp.last_outcome == 'wrong_number'
                    or (
                        cp.confidence_score is not None
                        and cp.confidence_score < MIN_VIABLE_CONFIDENCE
                        and cls._explicit_annotation_score(cp.notes) is None
                    )
                )
                if cp.notes != HUBSPOT_PRIMARY_NOTE:
                    cp.notes = HUBSPOT_PRIMARY_NOTE
                    changed = True
                if not preserve_low:
                    boosted = max(
                        cp.confidence_score if cp.confidence_score is not None else DEFAULT_CONFIDENCE,
                        85,
                    )
                    if cp.confidence_score != boosted:
                        cp.confidence_score = boosted
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
            confidence_score=annotation_score,
            source=source,
        )
        db.session.add(cp)
        db.session.flush()
        return cp, True

    @classmethod
    def _ensure_active_owner_contact_id(cls, lead_id: int) -> int | None:
        """Create an owner from lead name fields when no active owner exists.

        Never reactivates a former_owner solely because HubSpot phones arrived —
        that would put prior-owner numbers back on outreach paths.
        """
        from app.services.contact_service import ContactService

        lead = Lead.query.get(lead_id)
        if lead is None:
            return None
        first = (getattr(lead, 'owner_first_name', None) or '').strip() or None
        last = (getattr(lead, 'owner_last_name', None) or '').strip() or None
        if not first and not last:
            return None
        contact, _link = ContactService()._upsert_named_owner(
            lead_id, first, last, is_primary=True,
        )
        return contact.id

    @classmethod
    def sync_phones_from_hubspot_contact(cls, lead_id: int, contact) -> int:
        """Apply HubSpot phone annotations to relational contact_phones for a lead."""
        contact_id = cls.get_primary_contact_id(lead_id)
        if contact_id is None:
            contact_id = cls._ensure_active_owner_contact_id(lead_id)
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
                  AND (pc.role IS NULL OR pc.role <> 'former_owner')
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
            candidate = ContactPhone.query.get(contact_phone_id)
            if candidate is not None:
                link = PropertyContact.query.filter_by(
                    property_id=lead_id,
                    contact_id=candidate.contact_id,
                ).first()
                if link is not None and link.role != 'former_owner':
                    cp = candidate
        elif phone_number:
            cp = cls._find_phone_for_lead(lead_id, phone_number)
        if cp is None:
            return
        prior = cp.confidence_score if cp.confidence_score is not None else DEFAULT_CONFIDENCE
        prior_outcome = cp.last_outcome
        cp.last_called_at = datetime.now(timezone.utc)
        # Wrong-number demotion sticks until a connected/answered call.
        if prior_outcome == 'wrong_number' and outcome not in ('answered', 'wrong_number'):
            cp.last_outcome = outcome
            if prior < MIN_VIABLE_CONFIDENCE:
                cp.confidence_score = prior
            db.session.add(cp)
            cls.refresh_lead_has_phone(lead_id)
            return
        cp.confidence_score = cls.confidence_from_outcome(outcome, prior)
        cp.last_outcome = outcome
        preserve_low = (
            prior < MIN_VIABLE_CONFIDENCE
            or outcome == 'wrong_number'
        )
        # Match upsert_phone: synthetic HubSpot-primary marker floors at 85
        # unless the number was/is marked wrong (or similarly non-viable).
        if (
            cls._is_synthetic_hubspot_primary_notes(cp.notes)
            and not preserve_low
            and (cp.confidence_score is None or cp.confidence_score >= MIN_VIABLE_CONFIDENCE)
        ):
            cp.confidence_score = max(
                cp.confidence_score if cp.confidence_score is not None else DEFAULT_CONFIDENCE,
                85,
            )
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
                      AND (pc.role IS NULL OR pc.role <> 'former_owner')
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
    def _reset_phone_confidence_baseline(cls, lead_id: int) -> None:
        """Reset lead phones to annotation/default scores before timeline replay."""
        rows = (
            ContactPhone.query
            .join(PropertyContact, PropertyContact.contact_id == ContactPhone.contact_id)
            .filter(
                PropertyContact.property_id == lead_id,
                or_(
                    PropertyContact.role.is_(None),
                    PropertyContact.role != 'former_owner',
                ),
            )
            .all()
        )
        for cp in rows:
            notes = cp.notes
            explicit = cls._explicit_annotation_score(notes)
            if explicit is not None:
                cp.confidence_score = explicit
            elif cls._is_synthetic_hubspot_primary_notes(notes):
                cp.confidence_score = 85
            else:
                annotation = cls.confidence_from_annotation(notes)
                cp.confidence_score = (
                    annotation if annotation != DEFAULT_CONFIDENCE else DEFAULT_CONFIDENCE
                )
            cp.last_outcome = None
            cp.last_called_at = None
            db.session.add(cp)

    @classmethod
    def recompute_for_lead(cls, lead_id: int) -> None:
        """Replay call_logged + hubspot_call timeline entries for confidence.

        Resets to annotation/default baselines first so recompute is idempotent
        even when import already applied the same HubSpot call outcomes.
        """
        cls._reset_phone_confidence_baseline(lead_id)
        entries = (
            LeadTimelineEntry.query
            .filter(
                LeadTimelineEntry.lead_id == lead_id,
                LeadTimelineEntry.event_type.in_(('call_logged', 'hubspot_call')),
                LeadTimelineEntry.is_deleted.is_(False),
            )
            .order_by(LeadTimelineEntry.occurred_at.asc())
            .all()
        )
        for entry in entries:
            meta = entry.event_metadata or {}
            if entry.event_type == 'hubspot_call':
                cls.apply_hubspot_call_outcome(
                    lead_id,
                    meta.get('disposition') or meta.get('outcome'),
                    phone_number=meta.get('phone_number'),
                )
                continue
            outcome = meta.get('outcome')
            if not outcome:
                continue
            mapped = cls.outcome_from_hubspot_disposition(outcome) or outcome
            if mapped not in (
                'answered', 'wrong_number', 'voicemail', 'no_answer', 'busy',
            ):
                # Native call_logged already uses those keys.
                mapped = outcome
            cls.update_from_call(
                lead_id,
                mapped,
                contact_phone_id=meta.get('contact_phone_id'),
                phone_number=meta.get('phone_number'),
            )

    @staticmethod
    def sort_phones_for_display(phones: list[dict]) -> list[dict]:
        def _sort_key(p: dict):
            score = (
                p.get('confidence_score')
                if p.get('confidence_score') is not None
                else DEFAULT_CONFIDENCE
            )
            notes = (p.get('notes') or '').lower()
            source = (p.get('source') or '').lower()
            is_primary = (
                'hubspot primary' in notes
                or (source.startswith('hubspot') and 'hubspot primary' in notes)
            )
            # Confidence DESC, then HubSpot-primary preference — never alphabetical.
            return (-score, 0 if is_primary else 1)

        return sorted(phones, key=_sort_key)

    @classmethod
    def serialize_contact_phone(
        cls,
        phone: ContactPhone | None = None,
        *,
        include_contact_id: bool = False,
        phone_id: int | None = None,
        contact_id: int | None = None,
        value: str | None = None,
        label: str | None = None,
        notes: str | None = None,
        confidence_score: int | None = None,
        last_outcome: str | None = None,
        last_called_at: datetime | None = None,
        source: str | None = None,
    ) -> dict | None:
        """Canonical phone DTO for API dumps (contacts nested phones + CC phones[]).

        Prefer passing a ``ContactPhone`` model; keyword overrides support merged
        flat-column rows that have no relational id.

        Returns ``None`` when value is missing/blank so list serializers can skip
        bad rows without failing the whole contact payload.
        """
        if phone is not None:
            phone_id = phone.id if phone_id is None else phone_id
            contact_id = phone.contact_id if contact_id is None else contact_id
            value = phone.value if value is None else value
            label = phone.label if label is None else label
            notes = phone.notes if notes is None else notes
            confidence_score = (
                phone.confidence_score if confidence_score is None else confidence_score
            )
            last_outcome = phone.last_outcome if last_outcome is None else last_outcome
            last_called_at = phone.last_called_at if last_called_at is None else last_called_at
            source = phone.source if source is None else source

        if value is None or not str(value).strip():
            return None

        def _enum_or_str(raw):
            if raw is None:
                return None
            return raw.value if hasattr(raw, 'value') else raw

        called_at = last_called_at
        if called_at is not None and hasattr(called_at, 'isoformat'):
            called_at = called_at.isoformat()

        payload: dict = {
            'value': str(value).strip(),
            'label': _enum_or_str(label),
            'notes': notes,
            'confidence_score': (
                confidence_score if confidence_score is not None else DEFAULT_CONFIDENCE
            ),
            'last_outcome': last_outcome,
            'last_called_at': called_at,
            'source': _enum_or_str(source),
        }
        if phone_id is not None:
            payload['id'] = phone_id
        if include_contact_id and contact_id is not None:
            payload['contact_id'] = contact_id
        return payload

    @classmethod
    def serialize_contact_phones(
        cls,
        phones,
        *,
        include_contact_id: bool = False,
    ) -> list[dict]:
        """Serialize a sequence of ContactPhone models, skipping blank values."""
        out: list[dict] = []
        for phone in phones or []:
            payload = cls.serialize_contact_phone(
                phone, include_contact_id=include_contact_id,
            )
            if payload is not None:
                out.append(payload)
        return cls.sort_phones_for_display(out)

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
                  AND (pc.role IS NULL OR pc.role <> 'former_owner')
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
            payload = cls.serialize_contact_phone(
                phone_id=row[0],
                value=row[1],
                label=row[2],
                notes=row[3],
                confidence_score=row[4],
                last_outcome=row[5],
                last_called_at=row[6],
                source=row[7],
            )
            if payload is not None:
                phones.append(payload)

        for slot in range(1, 8):
            raw = getattr(lead, f'phone_{slot}')
            if not raw or not str(raw).strip():
                continue
            digits = cls.normalize_phone(str(raw))
            if not digits or digits in seen_digits:
                continue
            seen_digits.add(digits)
            payload = cls.serialize_contact_phone(
                value=str(raw).strip(),
                confidence_score=DEFAULT_CONFIDENCE,
            )
            if payload is not None:
                phones.append(payload)

        return cls.sort_phones_for_display(phones)

    @classmethod
    def get_primary_contact_id(cls, lead_id: int) -> int | None:
        active_links = PropertyContact.query.filter(
            PropertyContact.property_id == lead_id,
            or_(
                PropertyContact.role.is_(None),
                PropertyContact.role != 'former_owner',
            ),
        )
        primary = active_links.filter_by(is_primary=True).first()
        if primary:
            return primary.contact_id
        any_link = active_links.first()
        return any_link.contact_id if any_link else None
