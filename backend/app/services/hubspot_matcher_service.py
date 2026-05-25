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
        3. Remove punctuation characters: . , # - /
        4. Collapse multiple spaces to a single space.

        Returns the normalised string, or an empty string if *address* is
        None / empty.
        """
        if not address:
            return ""
        result = address.strip().upper()
        for pattern, expansion in _ABBREV_PATTERNS:
            result = pattern.sub(expansion, result)
        result = _PUNCT_RE.sub("", result)
        result = re.sub(r'\s+', ' ', result).strip()
        return result

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
    # Deal matching  (HubSpot Deal → internal Lead / property)
    # ------------------------------------------------------------------

    def match_deal(self, deal: HubSpotDeal) -> HubSpotMatch:
        """Match a HubSpot deal to an internal Lead record.

        Priority:
        1. PIN match against ``Lead.county_assessor_pin``  → HIGH confidence
        2. Normalised address match against ``Lead.property_street`` → MEDIUM
        3. No match → UNMATCHED; create a placeholder Lead with
           ``source='hubspot_import'`` and ``needs_review`` status.

        Returns the created/updated :class:`HubSpotMatch` record.
        """
        props = (deal.raw_payload or {}).get("properties", {})

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
                return self._upsert_match(
                    hubspot_record_type="deal",
                    hubspot_id=deal.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=lead.id,
                    confidence="HIGH",
                    matching_criteria="pin_match",
                )

        # --- 2. Normalised address match ------------------------------------
        raw_address = (
            props.get("dealname")
            or props.get("address")
            or ""
        ).strip()

        if raw_address:
            norm_address = HubSpotMatcherService.normalize_address(raw_address)
            # Query all leads that have a property_street set and compare
            # normalised values in Python (avoids DB-level normalisation).
            leads_with_address = Lead.query.filter(
                Lead.property_street.isnot(None)
            ).all()
            for lead in leads_with_address:
                if (
                    lead.property_street
                    and HubSpotMatcherService.normalize_address(lead.property_street)
                    == norm_address
                ):
                    logger.debug(
                        "Deal %s matched Lead %s via address '%s'",
                        deal.hubspot_id, lead.id, norm_address,
                    )
                    return self._upsert_match(
                        hubspot_record_type="deal",
                        hubspot_id=deal.hubspot_id,
                        internal_record_type="lead",
                        internal_record_id=lead.id,
                        confidence="MEDIUM",
                        matching_criteria="address_match",
                        status="pending",
                    )

        # --- 3. No match — record as UNMATCHED with no internal record ----------
        # If the deal has an address, create a placeholder Lead so the address
        # is preserved for manual review. If there's no address at all, just
        # record UNMATCHED with no internal record to avoid blank placeholder leads.
        if raw_address:
            logger.debug(
                "Deal %s unmatched; creating placeholder Lead with address '%s'.",
                deal.hubspot_id, raw_address,
            )
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
                return self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=property_id,
                    confidence="HIGH",
                    matching_criteria="email_match",
                )

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
                return self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=lead_by_email.id,
                    confidence="HIGH",
                    matching_criteria="email_match",
                )

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
                    return self._upsert_match(
                        hubspot_record_type="contact",
                        hubspot_id=contact.hubspot_id,
                        internal_record_type="lead",
                        internal_record_id=property_id,
                        confidence="HIGH",
                        matching_criteria="phone_match",
                    )

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
                    return self._upsert_match(
                        hubspot_record_type="contact",
                        hubspot_id=contact.hubspot_id,
                        internal_record_type="lead",
                        internal_record_id=lead.id,
                        confidence="HIGH",
                        matching_criteria="phone_match",
                    )

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
                return self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=property_id,
                    confidence="MEDIUM",
                    matching_criteria="name_property_match",
                )

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
                return self._upsert_match(
                    hubspot_record_type="contact",
                    hubspot_id=contact.hubspot_id,
                    internal_record_type="lead",
                    internal_record_id=lead_by_name.id,
                    confidence="MEDIUM",
                    matching_criteria="name_property_match",
                )

        # --- 4. No match — create a new Contact record and auto-confirm ----
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
