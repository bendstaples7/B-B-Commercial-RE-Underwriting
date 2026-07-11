"""HubSpotMatcherService — matches imported HubSpot records to internal Platform records.

Implements matching for deals (→ Lead/property), contacts (→ Lead/owner), and
companies (→ Organization) with confidence levels HIGH / MEDIUM / UNMATCHED.
"""
import re
import logging
from datetime import datetime

from app import db
from app.models.lead import Lead
from app.models.contact import Contact
from app.models.contact_email import ContactEmail
from app.models.contact_phone import ContactPhone
from app.models.property_contact import PropertyContact
from app.models.organization import Organization
from app.models.hubspot_match import HubSpotMatch
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_contact import HubSpotContact
from app.models.hubspot_company import HubSpotCompany

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Address abbreviation expansion map (whole-word replacements, longest first)
# ---------------------------------------------------------------------------
_ABBREV_MAP = [
    ("BLVD", "BOULEVARD"),
    ("PKWY", "PARKWAY"),
    ("HWY",  "HIGHWAY"),
    ("AVE",  "AVENUE"),
    ("CIR",  "CIRCLE"),
    ("STREET", "STREET"),   # already expanded — keep idempotent
    ("ST",   "STREET"),
    ("DR",   "DRIVE"),
    ("RD",   "ROAD"),
    ("CT",   "COURT"),
    ("LN",   "LANE"),
    ("PL",   "PLACE"),
]

# Pre-compile word-boundary patterns for each abbreviation
_ABBREV_PATTERNS = [
    (re.compile(r'\b' + abbr + r'\b'), expansion)
    for abbr, expansion in _ABBREV_MAP
]

# Punctuation characters to strip after abbreviation expansion
_PUNCT_RE = re.compile(r'[.,#\-/]')


class HubSpotMatcherService:
    """Matches HubSpot raw records to internal Platform records.

    Usage::

        svc = HubSpotMatcherService()
        match = svc.match_deal(hubspot_deal_record)
    """

    # ------------------------------------------------------------------
    # Static normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_address(address: str) -> str:
        """Normalise a street address for comparison.

        Steps:
        1. Strip whitespace and convert to uppercase.
        2. Expand common abbreviations as whole-word replacements.
        3. Strip unit/apartment suffixes (APT, UNIT, STE, #, FLOOR, FL, etc.)
           so that '4263 W Montrose Ave Apt 1' matches '4263 W Montrose'.
        4. Remove punctuation characters: . , # - /
        5. Collapse multiple spaces to a single space.

        Returns the normalised string, or an empty string if *address* is
        None / empty.
        """
        if not address:
            return ""
        result = address.strip().upper()
        for pattern, expansion in _ABBREV_PATTERNS:
            result = pattern.sub(expansion, result)

        # Strip unit/apt suffixes before punctuation removal so that
        # 'APT 1', 'UNIT 2B', 'STE 300', '# 4', 'FL 2', 'FLOOR 2' etc.
        # don't prevent an otherwise-correct address from matching.
        result = re.sub(
            r'\b(APT|APARTMENT|UNIT|STE|SUITE|FL|FLOOR|RM|ROOM|BLDG|BUILDING)\b[\s#]*[\w-]*',
            '',
            result,
        )
        # Also strip trailing bare number that follows the street name
        # (e.g. '4263 W MONTROSE AVENUE 1' → '4263 W MONTROSE AVENUE')
        result = re.sub(r'\s+\d+\s*$', '', result)

        result = _PUNCT_RE.sub("", result)
        result = re.sub(r'\s+', ' ', result).strip()
        return result

    @classmethod
    def _address_matches_for(cls, raw_address: str) -> list:
        """Return leads whose normalized street matches *raw_address*."""
        from app.services.lead_merge_utils import dedup_street_key

        norm_address = cls.normalize_address(raw_address)
        dedup_key = dedup_street_key(raw_address)
        if not norm_address and not dedup_key:
            return []

        candidates: list = []
        seen_ids: set[int] = set()
        if dedup_key:
            for lead in Lead.query.filter(Lead.normalized_street == dedup_key).all():
                if lead.id not in seen_ids:
                    candidates.append(lead)
                    seen_ids.add(lead.id)

        # Legacy rows before normalized_street backfill
        for lead in Lead.query.filter(
            Lead.property_street.isnot(None),
            Lead.normalized_street.is_(None),
        ).all():
            if lead.id not in seen_ids:
                candidates.append(lead)
                seen_ids.add(lead.id)

        matches = []
        for lead in candidates:
            if not lead.property_street:
                continue
            norm_lead = cls.normalize_address(lead.property_street)
            if norm_lead == norm_address or \
               norm_lead.startswith(norm_address + " ") or \
               norm_address.startswith(norm_lead + " "):
                matches.append(lead)
        return matches

    @staticmethod
    def _confirmed_hubspot_lead_ids() -> set[int]:
        """Lead ids with a confirmed HubSpot match row."""
        rows = HubSpotMatch.query.filter(
            HubSpotMatch.internal_record_type == 'lead',
            HubSpotMatch.status == 'confirmed',
            HubSpotMatch.internal_record_id.isnot(None),
        ).all()
        return {int(r.internal_record_id) for r in rows}

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Strip all non-digit characters from a phone number.

        Returns a string of digits only, or an empty string if *phone* is
        None / empty.
        """
        if not phone:
            return ""
        return re.sub(r'\D', '', phone)

    @staticmethod
    def normalize_company_name(name: str) -> str:
        """Normalise a company name for comparison.

        Steps:
        1. Convert to uppercase.
        2. Strip punctuation.
        3. Collapse whitespace.

        Returns the normalised string, or an empty string if *name* is
        None / empty.
        """
        if not name:
            return ""
        result = name.upper()
        result = re.sub(r'[^\w\s]', '', result)
        result = re.sub(r'\s+', ' ', result).strip()
        return result

    # ------------------------------------------------------------------
    # Lead enrichment from HubSpot data
    # ------------------------------------------------------------------

    def enrich_lead_from_deal(self, lead: Lead, deal: HubSpotDeal,
                              stage_label_map: dict = None,
                              *, sync_deal_context: bool = False) -> list[str]:
        """Enrich a Lead with data from a matched HubSpot deal.

        Copies fields that are currently null/empty on the Lead from the
        deal's raw_payload.  This is intentionally non-destructive: existing
        non-null values on the lead are never overwritten unless
        ``sync_deal_context=True`` (used during explicit HubSpot refresh).

        ``hubspot_deal_stage`` is always synced from the linked deal.
        """
        props = (deal.raw_payload or {}).get("properties", {})
        updated_fields = []

        # hubspot_deal_stage: always sync the live value — it is a CRM signal.
        # Translate internal stage ID to the portal's display label.
        stage_id = props.get("dealstage") or None
        if stage_id and not stage_label_map:
            try:
                from app.models.hubspot_config import HubSpotConfig
                from app.services.hubspot_client_service import HubSpotClientService
                _config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
                if _config:
                    stage_label_map = HubSpotClientService(_config).fetch_pipeline_stage_labels("deals")
            except Exception as _exc:
                logger.warning("enrich_lead_from_deal: could not fetch stage labels: %s", _exc)
        if stage_id:
            stage_label = (stage_label_map or {}).get(stage_id)
            if stage_label is None:
                # Unknown stage: neither the caller-supplied map nor the
                # on-demand fetch above could translate this stage ID. Do NOT
                # overwrite the stored label with the raw HubSpot stage ID
                # (Bug 1: 'closedlost' must never be persisted as the label).
                # Keep any existing human-readable label and leave it otherwise
                # unmapped — a later sync (once the pipeline labels are
                # available) will fill it in.
                logger.warning(
                    "enrich_lead_from_deal: stage_id=%r not in stage_label_map — "
                    "leaving hubspot_deal_stage unchanged (no raw-ID fallback). "
                    "Pipeline labels: %s",
                    stage_id, list((stage_label_map or {}).keys()),
                )
            else:
                if lead.hubspot_deal_stage != stage_label:
                    # Read-only mirror of HubSpot deal stage for audit/display.
                    # Canonical pipeline status is lead.lead_status (updated below).
                    lead.hubspot_deal_stage = stage_label
                    updated_fields.append("hubspot_deal_stage")

                # Sync lead_status to match the HubSpot pipeline stage label
                from app.services.hubspot_stage_mapping import (
                    lead_status_from_hubspot_stage,
                    manual_status_change_wins,
                )
                new_lead_status = lead_status_from_hubspot_stage(stage_label)
                if new_lead_status and lead.lead_status != new_lead_status:
                    # Don't override suppressed/do_not_contact with a pipeline stage
                    if lead.lead_status not in ('suppressed', 'do_not_contact'):
                        if not manual_status_change_wins(lead):
                            lead.lead_status = new_lead_status
                            updated_fields.append("lead_status")

        # Address fields — fill in nulls only
        field_map = {
            "address": "property_street",
        }
        for hs_key, lead_attr in field_map.items():
            val = (props.get(hs_key) or "").strip() or None
            if val and not getattr(lead, lead_attr):
                setattr(lead, lead_attr, val)
                updated_fields.append(lead_attr)

        # PIN
        pin = (
            props.get("county_assessor_pin")
            or props.get("pin")
            or ""
        ).strip() or None
        if pin and not lead.county_assessor_pin:
            lead.county_assessor_pin = pin
            updated_fields.append("county_assessor_pin")

        deal_source = (props.get("deal_source") or "").strip() or None
        if deal_source and (sync_deal_context or not (lead.deal_source or '').strip()):
            if lead.deal_source != deal_source:
                lead.deal_source = deal_source
                updated_fields.append("deal_source")

        deal_description = (props.get("description") or "").strip() or None
        if deal_description and (sync_deal_context or not (lead.deal_description or '').strip()):
            if lead.deal_description != deal_description:
                lead.deal_description = deal_description
                updated_fields.append("deal_description")

        lead.last_hubspot_sync_at = datetime.utcnow()
        if 'last_hubspot_sync_at' not in updated_fields:
            updated_fields.append('last_hubspot_sync_at')
        db.session.add(lead)

        return updated_fields

    def enrich_lead_from_contact(self, lead: Lead, contact: HubSpotContact) -> list[str]:
        """Enrich a Lead with contact data from a matched HubSpot contact.

        Fills in phone and email flat columns (phone_1–phone_7, email_1–email_5)
        from the HubSpot contact's properties, using the first empty slot.
        Also fills owner_first_name / owner_last_name when null.

        Additionally syncs data into the relational contact_phones /
        contact_emails tables if a PropertyContact link exists, so that
        the lead_crm_flags view also picks it up.

        Updates has_phone / has_email flags if new data was written.

        Returns a list of field names that were updated.
        """
        props = (contact.raw_payload or {}).get("properties", {})
        updated_fields: list[str] = []

        # --- Owner name -------------------------------------------------------
        first_name = (props.get("firstname") or "").strip() or None
        last_name = (props.get("lastname") or "").strip() or None
        if first_name and not lead.owner_first_name:
            lead.owner_first_name = first_name
            updated_fields.append("owner_first_name")
        if last_name and not lead.owner_last_name:
            lead.owner_last_name = last_name
            updated_fields.append("owner_last_name")

        # --- Phones -----------------------------------------------------------
        from app.services.phone_confidence_service import PhoneConfidenceService

        parsed_phones = PhoneConfidenceService.parse_phones_from_hubspot_props(props)
        hs_phones = [phone_val for phone_val, _, _ in parsed_phones]

        phone_slots = ["phone_1", "phone_2", "phone_3", "phone_4",
                       "phone_5", "phone_6", "phone_7"]
        # Collect already-stored flat phones to avoid duplicates
        existing_phones = {
            HubSpotMatcherService.normalize_phone(getattr(lead, slot))
            for slot in phone_slots
            if getattr(lead, slot)
        }
        for phone_val in hs_phones:
            digits = HubSpotMatcherService.normalize_phone(phone_val)
            if not digits or digits in existing_phones:
                continue
            # Write to first empty slot
            for slot in phone_slots:
                if not getattr(lead, slot):
                    setattr(lead, slot, phone_val)
                    updated_fields.append(slot)
                    existing_phones.add(digits)
                    break

        # --- Emails -----------------------------------------------------------
        hs_emails = []
        primary_email = (props.get("email") or "").strip().lower() or None
        if primary_email:
            hs_emails.append(primary_email)

        # Parse hs_additional_emails — comma or newline separated
        additional_emails_raw = (props.get("hs_additional_emails") or "").strip()
        if additional_emails_raw:
            for part in re.split(r'[\n,;]+', additional_emails_raw):
                part = part.strip().lower()
                if part and '@' in part and part not in hs_emails:
                    hs_emails.append(part)

        email_slots = ["email_1", "email_2", "email_3", "email_4", "email_5"]
        existing_emails = {
            (getattr(lead, slot) or "").strip().lower()
            for slot in email_slots
            if getattr(lead, slot)
        }
        for hs_email in hs_emails:
            if hs_email and hs_email not in existing_emails:
                for slot in email_slots:
                    if not getattr(lead, slot):
                        setattr(lead, slot, hs_email)
                        updated_fields.append(slot)
                        existing_emails.add(hs_email)
                        break

        # --- Mailing address from HubSpot contact ----------------------------
        hs_street = (props.get("address") or "").strip() or None
        hs_city   = (props.get("city") or "").strip() or None
        hs_state  = (props.get("state") or "").strip() or None
        hs_zip    = (props.get("zip") or "").strip() or None
        if hs_street and not lead.mailing_address:
            lead.mailing_address = hs_street
            updated_fields.append("mailing_address")
        if hs_city and not lead.mailing_city:
            lead.mailing_city = hs_city
            updated_fields.append("mailing_city")
        if hs_state and not lead.mailing_state:
            lead.mailing_state = hs_state
            updated_fields.append("mailing_state")
        if hs_zip and not lead.mailing_zip:
            lead.mailing_zip = hs_zip
            updated_fields.append("mailing_zip")

        # --- Update boolean flags --------------------------------------------
        if any(f.startswith("phone_") for f in updated_fields):
            lead.has_phone = True
            updated_fields.append("has_phone")
        if any(f.startswith("email_") for f in updated_fields):
            lead.has_email = True
            updated_fields.append("has_email")

        if updated_fields:
            db.session.add(lead)

        # --- Ensure a relational Contact + PropertyContact row exists ---------
        hs_first = (props.get("firstname") or "").strip() or None
        hs_last  = (props.get("lastname") or "").strip() or None
        if hs_first or hs_last:
            # Prefer ContactService upsert for name-deduped PropertyContact links.
            try:
                from app.services.contact_service import ContactService
                # Temporarily set flat owner if empty so upsert can create primary.
                if not lead.owner_first_name and not lead.owner_last_name:
                    if hs_first:
                        lead.owner_first_name = hs_first
                    if hs_last:
                        lead.owner_last_name = hs_last
                ContactService()._upsert_named_owner(
                    lead.id, hs_first, hs_last, is_primary=False,
                )
                updated_fields.append("property_contact_linked")
            except Exception as exc:
                logger.warning(
                    "enrich_lead_from_contact: ContactService upsert failed lead_id=%s: %s",
                    lead.id, exc,
                )
                already_linked = db.session.query(PropertyContact).join(Contact).filter(
                    PropertyContact.property_id == lead.id,
                    db.func.lower(Contact.first_name) == (hs_first or "").lower(),
                    db.func.lower(db.func.coalesce(Contact.last_name, "")) == (hs_last or "").lower(),
                ).first()

                if already_linked is None:
                    existing_contact = Contact(
                        first_name=hs_first,
                        last_name=hs_last,
                        role="owner",
                    )
                    db.session.add(existing_contact)
                    db.session.flush()
                    has_primary = PropertyContact.query.filter_by(
                        property_id=lead.id, is_primary=True
                    ).first() is not None
                    new_pc = PropertyContact(
                        property_id=lead.id,
                        contact_id=existing_contact.id,
                        role="owner",
                        is_primary=not has_primary,
                    )
                    db.session.add(new_pc)
                    db.session.flush()
                    updated_fields.append("property_contact_linked")

        contact_id = PhoneConfidenceService.get_primary_contact_id(lead.id)
        if contact_id is not None and parsed_phones:
            PhoneConfidenceService.sync_phones_from_hubspot_contact(lead.id, contact)
            if 'contact_phone_synced' not in updated_fields:
                updated_fields.append('contact_phone_synced')

        logger.debug(
            "enrich_lead_from_contact: lead_id=%s enriched fields=%s",
            lead.id, updated_fields,
        )
        return updated_fields

    # ------------------------------------------------------------------
    # Deal matching  (HubSpot Deal → internal Lead / property)
    # ------------------------------------------------------------------

    def match_deal(self, deal: HubSpotDeal, stage_label_map: dict = None) -> HubSpotMatch:
        """Match a HubSpot deal to an internal Lead record.

        Priority:
        1. PIN match against ``Lead.county_assessor_pin``  → HIGH confidence
        2. Normalised address match against ``Lead.property_street`` → MEDIUM
        3. No match → UNMATCHED; create a placeholder Lead with
           ``source='hubspot_import'`` and ``needs_review`` status.

        *stage_label_map* is an optional dict of HubSpot internal stage ID →
        display label used to translate ``dealstage`` IDs when enriching leads.
        If omitted, the method fetches it lazily from the HubSpot config.

        Returns the created/updated :class:`HubSpotMatch` record.
        """
        props = (deal.raw_payload or {}).get("properties", {})

        # Resolve stage label map lazily if not provided by the caller
        if stage_label_map is None:
            stage_label_map = {}
            try:
                from app.models.hubspot_config import HubSpotConfig as _HubSpotConfig
                from app.services.hubspot_client_service import HubSpotClientService as _HCS
                _config = _HubSpotConfig.query.order_by(_HubSpotConfig.id.desc()).first()
                if _config:
                    stage_label_map = _HCS(_config).fetch_pipeline_stage_labels("deals")
            except Exception as _exc:
                logger.debug("match_deal: could not fetch stage labels: %s", _exc)

        # --- 1. PIN match ---------------------------------------------------
        pin = (
            props.get("county_assessor_pin")
            or props.get("pin")
            or ""
        ).strip()

        if pin:
            lead = Lead.query.filter_by(county_assessor_pin=pin).first()
            if lead:
                logger.debug(
                    "Deal %s matched Lead %s via PIN '%s'",
                    deal.hubspot_id, lead.id, pin,
                )
                match = self._upsert_match(
                    hubspot_record_type="deal",
                    hubspot_id=deal.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=lead.id,
                    confidence="HIGH",
                    matching_criteria="pin_match",
                )
                enriched = self.enrich_lead_from_deal(lead, deal, stage_label_map)
                if enriched:
                    logger.debug("Deal %s enriched Lead %s fields: %s", deal.hubspot_id, lead.id, enriched)
                return match

        # --- 2. Normalised address match ------------------------------------
        raw_address = (
            props.get("dealname")
            or props.get("address")
            or ""
        ).strip()

        if raw_address:
            norm_address = HubSpotMatcherService.normalize_address(raw_address)
            address_matches = HubSpotMatcherService._address_matches_for(raw_address)

            if address_matches:
                from app.services.lead_merge_utils import pick_best_lead_for_deal

                confirmed_ids = HubSpotMatcherService._confirmed_hubspot_lead_ids()
                auto_confirm = len(address_matches) == 1
                if auto_confirm:
                    lead = address_matches[0]
                else:
                    lead = pick_best_lead_for_deal(
                        address_matches, confirmed_ids, props,
                    )
                    for candidate in address_matches:
                        if candidate.id != lead.id:
                            candidate.review_required = True
                    auto_confirm = True
                    logger.debug(
                        "Deal %s address '%s' matched %d leads — disambiguated to Lead %s",
                        deal.hubspot_id, norm_address, len(address_matches), lead.id,
                    )

                if auto_confirm:
                    logger.debug(
                        "Deal %s matched Lead %s via address '%s' (auto_confirm=True)",
                        deal.hubspot_id, lead.id, norm_address,
                    )
                    match = self._upsert_match(
                        hubspot_record_type="deal",
                        hubspot_id=deal.hubspot_id,
                        internal_record_type="lead",
                        internal_record_id=lead.id,
                        confidence="MEDIUM",
                        matching_criteria="address_match",
                        status="confirmed",
                    )
                    enriched = self.enrich_lead_from_deal(lead, deal, stage_label_map)
                    if enriched:
                        logger.debug(
                            "Deal %s enriched Lead %s fields: %s",
                            deal.hubspot_id, lead.id, enriched,
                        )
                else:
                    logger.debug(
                        "Deal %s address '%s' matched %d leads — ambiguous, requires manual review",
                        deal.hubspot_id, norm_address, len(address_matches),
                    )
                    match = self._upsert_match(
                        hubspot_record_type="deal",
                        hubspot_id=deal.hubspot_id,
                        internal_record_type="lead",
                        internal_record_id=None,
                        confidence="MEDIUM",
                        matching_criteria="address_match",
                        status="pending",
                    )
                return match

        # --- 3. No match — dedup identity or placeholder ---
        if raw_address:
            logger.debug(
                "Deal %s unmatched; creating placeholder Lead with address '%s'.",
                deal.hubspot_id, raw_address,
            )
            from app.services.lead_dedup_service import find_lead_by_identity
            from app.services.lead_merge_utils import owner_names_from_deal_props

            owner_first, owner_last = owner_names_from_deal_props(props)
            existing = find_lead_by_identity(
                owner_first_name=owner_first,
                owner_last_name=owner_last,
                property_street=raw_address,
            )
            if existing:
                logger.debug(
                    "Deal %s linked to existing Lead %s via dedup identity (no placeholder)",
                    deal.hubspot_id, existing.id,
                )
                match = self._upsert_match(
                    hubspot_record_type="deal",
                    hubspot_id=deal.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=existing.id,
                    confidence="MEDIUM",
                    matching_criteria="address_match",
                    status="confirmed",
                )
                enriched = self.enrich_lead_from_deal(existing, deal, stage_label_map)
                if enriched:
                    logger.debug(
                        "Deal %s enriched Lead %s fields: %s",
                        deal.hubspot_id, existing.id, enriched,
                    )
                return match

            placeholder = Lead(
                property_street=raw_address,
                source="hubspot_import",
            )
            db.session.add(placeholder)
            db.session.flush()
            return self._upsert_match(
                hubspot_record_type="deal",
                hubspot_id=deal.hubspot_id,
                internal_record_type="lead",
                internal_record_id=placeholder.id,
                confidence="UNMATCHED",
                matching_criteria=None,
            )
        else:
            logger.debug(
                "Deal %s unmatched and has no address; auto-confirming as new record.",
                deal.hubspot_id,
            )
            return self._upsert_match(
                hubspot_record_type="deal",
                hubspot_id=deal.hubspot_id,
                internal_record_type=None,
                internal_record_id=None,
                confidence="UNMATCHED",
                matching_criteria=None,
                status="confirmed",
            )

    # ------------------------------------------------------------------
    # Contact matching  (HubSpot Contact → internal Lead / owner)
    # ------------------------------------------------------------------

    def match_contact(self, contact: HubSpotContact) -> HubSpotMatch:
        """Match a HubSpot contact to an internal Contact record.

        Priority:
        1. Email match against ``ContactEmail.value`` (case-insensitive) → HIGH
        2. Phone match (digits only) against ``ContactPhone.value`` → HIGH
        3. Full name + associated deal's property match via ``PropertyContact`` → MEDIUM
        4. No match → create a new Contact + PropertyContact (role=owner).

        The HubSpotMatch record uses ``internal_record_type="lead"`` and
        ``internal_record_id=<property_id>`` for consistency with the existing
        match schema.

        Returns the created/updated :class:`HubSpotMatch` record.
        """
        props = (contact.raw_payload or {}).get("properties", {})

        email = (props.get("email") or "").strip().lower()
        phone_raw = (props.get("phone") or "").strip()
        phone_digits = HubSpotMatcherService.normalize_phone(phone_raw)
        first_name = (props.get("firstname") or "").strip()
        last_name = (props.get("lastname") or "").strip()

        # --- 1. Email match -------------------------------------------------
        if email:
            # First check ContactEmail table (normalized contacts)
            contact_email = ContactEmail.query.filter(
                db.func.lower(ContactEmail.value) == email
            ).first()
            if contact_email:
                matched_contact = contact_email.contact
                # Find the property linked to this contact via PropertyContact
                pc = PropertyContact.query.filter_by(
                    contact_id=matched_contact.id
                ).first()
                property_id = pc.property_id if pc else None
                logger.debug(
                    "Contact %s matched Contact %s via email '%s' (property_id=%s)",
                    contact.hubspot_id, matched_contact.id, email, property_id,
                )
                match = self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=property_id,
                    confidence="HIGH",
                    matching_criteria="email_match",
                )
                if property_id:
                    lead = Lead.query.get(property_id)
                    if lead:
                        self.enrich_lead_from_contact(lead, contact)
                return match

            # Also check Lead.email_1 directly (denormalized storage).
            # Tiebreaker: most recently updated lead wins; fall back to highest id.
            lead_by_email = Lead.query.filter(
                db.func.lower(Lead.email_1) == email
            ).order_by(Lead.updated_at.desc().nullslast(), Lead.id.desc()).first()
            if lead_by_email:
                logger.debug(
                    "Contact %s matched Lead %s via email_1 '%s'",
                    contact.hubspot_id, lead_by_email.id, email,
                )
                match = self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=lead_by_email.id,
                    confidence="HIGH",
                    matching_criteria="email_match",
                )
                self.enrich_lead_from_contact(lead_by_email, contact)
                return match

        # --- 2. Phone match (digits only) -----------------------------------
        if phone_digits:
            # Fetch all ContactPhone records and normalize digits in Python
            # (avoids DB-level regex; acceptable for typical dataset sizes)
            all_phones = ContactPhone.query.all()
            for cp in all_phones:
                if HubSpotMatcherService.normalize_phone(cp.value) == phone_digits:
                    matched_contact = cp.contact
                    pc = PropertyContact.query.filter_by(
                        contact_id=matched_contact.id
                    ).first()
                    property_id = pc.property_id if pc else None
                    logger.debug(
                        "Contact %s matched Contact %s via phone '%s' (property_id=%s)",
                        contact.hubspot_id, matched_contact.id, phone_digits, property_id,
                    )
                    match = self._upsert_match(
                        hubspot_record_type="contact",
                        hubspot_id=contact.hubspot_id,
                        internal_record_type="lead",
                        internal_record_id=property_id,
                        confidence="HIGH",
                        matching_criteria="phone_match",
                    )
                    if property_id:
                        lead = Lead.query.get(property_id)
                        if lead:
                            self.enrich_lead_from_contact(lead, contact)
                    return match

            # Also check Lead.phone_1 directly (denormalized storage).
            # Tiebreaker: most recently updated lead wins; fall back to highest id.
            all_leads_with_phone = Lead.query.filter(
                Lead.phone_1.isnot(None)
            ).order_by(Lead.updated_at.desc().nullslast(), Lead.id.desc()).all()
            for lead in all_leads_with_phone:
                if HubSpotMatcherService.normalize_phone(lead.phone_1) == phone_digits:
                    logger.debug(
                        "Contact %s matched Lead %s via phone_1 '%s'",
                        contact.hubspot_id, lead.id, phone_digits,
                    )
                    match = self._upsert_match(
                        hubspot_record_type="contact",
                        hubspot_id=contact.hubspot_id,
                        internal_record_type="lead",
                        internal_record_id=lead.id,
                        confidence="HIGH",
                        matching_criteria="phone_match",
                    )
                    self.enrich_lead_from_contact(lead, contact)
                    return match

        # --- 3. Name + property match ---------------------------------------
        if first_name and last_name:
            # Join Contact → PropertyContact, filter by first_name/last_name
            # (case-insensitive). Use the first match found.
            name_match = (
                Contact.query
                .join(PropertyContact, PropertyContact.contact_id == Contact.id)
                .filter(
                    db.func.lower(Contact.first_name) == first_name.lower(),
                    db.func.lower(Contact.last_name) == last_name.lower(),
                )
                .first()
            )
            if name_match:
                pc = PropertyContact.query.filter_by(
                    contact_id=name_match.id
                ).first()
                property_id = pc.property_id if pc else None
                logger.debug(
                    "Contact %s matched Contact %s via name '%s %s' (property_id=%s)",
                    contact.hubspot_id, name_match.id, first_name, last_name, property_id,
                )
                match = self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=property_id,
                    confidence="MEDIUM",
                    matching_criteria="name_property_match",
                )
                if property_id:
                    lead = Lead.query.get(property_id)
                    if lead:
                        self.enrich_lead_from_contact(lead, contact)
                return match

            # Also check Lead.owner_first_name / owner_last_name directly.
            # Tiebreaker: most recently updated lead wins; fall back to highest id.
            lead_by_name = (
                Lead.query
                .filter(
                    db.func.lower(Lead.owner_first_name) == first_name.lower(),
                    db.func.lower(Lead.owner_last_name) == last_name.lower(),
                )
                .order_by(Lead.updated_at.desc().nullslast(), Lead.id.desc())
                .first()
            )
            if lead_by_name:
                logger.debug(
                    "Contact %s matched Lead %s via owner name '%s %s'",
                    contact.hubspot_id, lead_by_name.id, first_name, last_name,
                )
                match = self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=lead_by_name.id,
                    confidence="MEDIUM",
                    matching_criteria="name_property_match",
                )
                self.enrich_lead_from_contact(lead_by_name, contact)
                return match

        # --- 4. No match — create a new Contact record and auto-confirm ----
        # Check if we already have a match for this contact (idempotency guard)
        existing_match = HubSpotMatch.query.filter_by(
            hubspot_record_type="contact",
            hubspot_id=contact.hubspot_id,
        ).first()
        if existing_match and existing_match.internal_record_id is not None:
            # Already processed — return the existing match without creating duplicates
            logger.debug(
                "Contact %s already has a match (id=%s); skipping new record creation.",
                contact.hubspot_id, existing_match.id,
            )
            return existing_match

        logger.debug(
            "Contact %s unmatched; creating new Contact record.",
            contact.hubspot_id,
        )
        new_contact = Contact(
            first_name=first_name or None,
            last_name=last_name or None,
            role="owner",
        )
        db.session.add(new_contact)
        db.session.flush()

        # Create a placeholder Lead so the contact has a property anchor,
        # then link them via PropertyContact (role=owner).
        placeholder_lead = Lead(source="hubspot_import")
        db.session.add(placeholder_lead)
        db.session.flush()

        pc = PropertyContact(
            property_id=placeholder_lead.id,
            contact_id=new_contact.id,
            role="owner",
            is_primary=True,
        )
        db.session.add(pc)
        db.session.flush()

        return self._upsert_match(
            hubspot_record_type="contact",
            hubspot_id=contact.hubspot_id,
            internal_record_type="contact",
            internal_record_id=new_contact.id,
            confidence="UNMATCHED",
            matching_criteria=None,
            status="confirmed",
        )

    # ------------------------------------------------------------------
    # Company matching  (HubSpot Company → internal Organization)
    # ------------------------------------------------------------------

    def match_company(self, company: HubSpotCompany) -> HubSpotMatch:
        """Match a HubSpot company to an internal Organization record.

        Priority:
        1. Exact normalised name match against ``Organization.name`` → MEDIUM
        2. Normalised name + associated deal's property match → MEDIUM
        3. No match → create a new Organization from the company data.

        Returns the created/updated :class:`HubSpotMatch` record.
        """
        props = (company.raw_payload or {}).get("properties", {})
        raw_name = (props.get("name") or "").strip()
        norm_name = HubSpotMatcherService.normalize_company_name(raw_name)

        if norm_name:
            # --- 1. Exact normalised name match -----------------------------
            orgs = Organization.query.filter(
                Organization.name.isnot(None)
            ).all()
            for org in orgs:
                if (
                    org.name
                    and HubSpotMatcherService.normalize_company_name(org.name)
                    == norm_name
                ):
                    logger.debug(
                        "Company %s matched Organization %s via name '%s'",
                        company.hubspot_id, org.id, norm_name,
                    )
                    return self._upsert_match(
                        hubspot_record_type="company",
                        hubspot_id=company.hubspot_id,
                        internal_record_type="organization",
                        internal_record_id=org.id,
                        confidence="MEDIUM",
                        matching_criteria="name_match",
                    )

            # --- 2. Name + deal property match ------------------------------
            # (Same confidence level; kept as a distinct criteria label for
            # Review_Queue display purposes.)
            # In the current implementation the name-only match above already
            # covers this case.  A future iteration can refine by also
            # checking deal associations.  For now we fall through to create.

        # --- 3. No match — create new Organization --------------------------
        # The new Organization is created directly from this HubSpot company,
        # so the match is self-referential and can be auto-confirmed.
        logger.debug(
            "Company %s unmatched; creating new Organization '%s'.",
            company.hubspot_id, raw_name,
        )
        new_org = Organization(
            name=raw_name or f"HubSpot Company {company.hubspot_id}",
            source="hubspot_import",
            hubspot_company_id=company.hubspot_id,
        )
        db.session.add(new_org)
        db.session.flush()

        return self._upsert_match(
            hubspot_record_type="company",
            hubspot_id=company.hubspot_id,
            internal_record_type="organization",
            internal_record_id=new_org.id,
            confidence="HIGH",
            matching_criteria="hubspot_import_new_record",
            status="confirmed",
        )

    # ------------------------------------------------------------------
    # Upsert helper
    # ------------------------------------------------------------------

    def _upsert_match(
        self,
        hubspot_record_type: str,
        hubspot_id: str,
        internal_record_type: str | None,
        internal_record_id: int | None,
        confidence: str,
        matching_criteria: str | None,
        status: str = "pending",
    ) -> HubSpotMatch:
        """Create or update a :class:`HubSpotMatch` record.

        Uses the unique constraint on ``(hubspot_record_type, hubspot_id)``
        to decide whether to insert or update.  The ``status`` field is set
        to the provided value on creation.  On update, status is only
        overwritten if the existing status is ``'pending'`` — confirmed/rejected
        matches are never downgraded.

        Returns the persisted :class:`HubSpotMatch` instance.
        """
        existing = HubSpotMatch.query.filter_by(
            hubspot_record_type=hubspot_record_type,
            hubspot_id=hubspot_id,
        ).first()

        if existing:
            existing.internal_record_type = internal_record_type
            existing.internal_record_id = internal_record_id
            existing.confidence = confidence
            existing.matching_criteria = matching_criteria
            # Only upgrade status — never downgrade a confirmed/rejected match
            if existing.status == "pending" and status != "pending":
                existing.status = status
            existing.updated_at = datetime.utcnow()
            db.session.flush()
            return existing

        match = HubSpotMatch(
            hubspot_record_type=hubspot_record_type,
            hubspot_id=hubspot_id,
            internal_record_type=internal_record_type,
            internal_record_id=internal_record_id,
            confidence=confidence,
            status=status,
            matching_criteria=matching_criteria,
        )
        db.session.add(match)
        db.session.flush()
        return match
