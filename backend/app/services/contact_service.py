"""ContactService — business logic for Contact CRUD and Property-Contact linking.

Implements all operations required by the property-contact-model spec:
  - create_contact / update_contact / delete_contact
  - link_contact_to_property / unlink_contact_from_property
  - get_contacts_for_property / get_ordered_contacts_payload
  - batch_owner_display_for_leads (queue / list display)
"""
import logging
import unicodedata

import sqlalchemy.exc

from app import db
from app.models.contact import Contact
from app.models.contact_phone import ContactPhone
from app.models.contact_email import ContactEmail
from app.models.property_contact import PropertyContact
from app.models.lead import Property
from app.exceptions import ResourceNotFoundError, ConflictError, ValidationException
from app.services.contact_backfill import phone_digits, split_phone_field, split_email_field

from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


def _strip_invisible(value: str) -> str:
    """Strip all Unicode whitespace and control characters from *value*.

    Mirrors the helper used in OrganizationService so that validation is
    consistent across the codebase.
    """
    cleaned = ''.join(
        ch for ch in value
        if not (unicodedata.category(ch).startswith('C') or unicodedata.category(ch) == 'Zs')
    )
    return cleaned.strip()


class ContactService:
    """Service class for all Contact-related operations.

    All database writes use ``db.session`` and commit at the end of each
    operation.  Callers are responsible for providing a valid Flask
    application context.
    """

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_contact(self, data: dict) -> Contact:
        """Create a new Contact with optional phones and emails.

        Parameters
        ----------
        data : dict
            Must contain at least one non-empty/non-whitespace value for
            ``first_name`` or ``last_name``.  Optional keys: ``role``,
            ``role_description``, ``notes``, ``phones`` (list of dicts),
            ``emails`` (list of dicts).

        Returns
        -------
        Contact
            The newly created and persisted Contact.

        Raises
        ------
        ValidationException
            If both ``first_name`` and ``last_name`` are absent, null, or
            composed entirely of whitespace.
        """
        self._validate_name(data)

        contact = Contact(
            first_name=data.get('first_name'),
            last_name=data.get('last_name'),
            role=data.get('role', 'owner'),
            role_description=data.get('role_description'),
            notes=data.get('notes'),
        )
        db.session.add(contact)
        db.session.flush()  # populate contact.id before inserting children

        for phone_data in data.get('phones', []):
            phone = ContactPhone(
                contact_id=contact.id,
                value=phone_data['value'],
                label=phone_data.get('label', 'other'),
            )
            db.session.add(phone)

        for email_data in data.get('emails', []):
            email = ContactEmail(
                contact_id=contact.id,
                value=email_data['value'],
                label=email_data.get('label', 'other'),
            )
            db.session.add(email)

        db.session.commit()
        logger.info("Created Contact id=%d", contact.id)
        return contact

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_contact(self, contact_id: int, data: dict) -> Contact:
        """Update an existing Contact, replacing phones and emails atomically.

        Phones and emails are replaced using a delete-then-insert strategy so
        that the caller always supplies the full desired set.

        Parameters
        ----------
        contact_id : int
        data : dict
            Partial or full set of updatable fields.  If ``phones`` is
            present, all existing ContactPhone records are deleted and
            replaced.  Same for ``emails``.

        Returns
        -------
        Contact
            The updated Contact.

        Raises
        ------
        ResourceNotFoundError
            If no Contact with *contact_id* exists.
        ValidationException
            If both name fields are explicitly set to empty/whitespace.
        """
        contact = self._get_contact_or_raise(contact_id)

        # Only validate names if at least one name key is being updated
        if 'first_name' in data or 'last_name' in data:
            merged = {
                'first_name': data.get('first_name', contact.first_name),
                'last_name': data.get('last_name', contact.last_name),
            }
            self._validate_name(merged)

        # Update scalar fields
        for field in ('first_name', 'last_name', 'role', 'role_description', 'notes'):
            if field in data:
                setattr(contact, field, data[field])

        # Replace phones atomically
        if 'phones' in data:
            ContactPhone.query.filter_by(contact_id=contact.id).delete()
            for phone_data in data['phones']:
                phone = ContactPhone(
                    contact_id=contact.id,
                    value=phone_data['value'],
                    label=phone_data.get('label', 'other'),
                )
                db.session.add(phone)

        # Replace emails atomically
        if 'emails' in data:
            ContactEmail.query.filter_by(contact_id=contact.id).delete()
            for email_data in data['emails']:
                email = ContactEmail(
                    contact_id=contact.id,
                    value=email_data['value'],
                    label=email_data.get('label', 'other'),
                )
                db.session.add(email)

        db.session.commit()
        logger.info("Updated Contact id=%d", contact.id)
        return contact

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_contact(self, contact_id: int) -> None:
        """Delete a Contact and cascade to phones, emails, and property_contacts.

        Parameters
        ----------
        contact_id : int

        Raises
        ------
        ResourceNotFoundError
            If no Contact with *contact_id* exists.
        """
        contact = self._get_contact_or_raise(contact_id)
        db.session.delete(contact)
        db.session.commit()
        logger.info("Deleted Contact id=%d", contact_id)

    # ------------------------------------------------------------------
    # Link / Unlink
    # ------------------------------------------------------------------

    def link_contact_to_property(
        self,
        property_id: int,
        contact_id: int,
        role: str,
        is_primary: bool,
    ) -> PropertyContact:
        """Create a PropertyContact association.

        If *is_primary* is ``True``, all existing PropertyContact records for
        *property_id* are first set to ``is_primary=False`` before the new
        record is inserted.

        Parameters
        ----------
        property_id : int
        contact_id : int
        role : str
        is_primary : bool

        Returns
        -------
        PropertyContact

        Raises
        ------
        ResourceNotFoundError
            If the Property or Contact does not exist.
        ConflictError
            If a PropertyContact for (property_id, contact_id) already exists.
        """
        # Verify both entities exist
        if Property.query.get(property_id) is None:
            raise ResourceNotFoundError(
                f"Property id={property_id} not found.",
                payload={'property_id': property_id},
            )
        if Contact.query.get(contact_id) is None:
            raise ResourceNotFoundError(
                f"Contact id={contact_id} not found.",
                payload={'contact_id': contact_id},
            )

        # Promote an existing former_owner link instead of conflicting.
        # Duplicate active links still raise ConflictError (API contract).
        existing_link = (
            PropertyContact.query
            .filter_by(property_id=property_id, contact_id=contact_id)
            .first()
        )
        if existing_link is not None:
            if existing_link.role == 'former_owner' and role == 'owner':
                if is_primary:
                    other_owners = (
                        PropertyContact.query
                        .filter(
                            PropertyContact.property_id == property_id,
                            PropertyContact.role == 'owner',
                            PropertyContact.contact_id != contact_id,
                        )
                        .all()
                    )
                    if other_owners:
                        from datetime import datetime, timezone
                        from app.services.owner_snapshot_service import (
                            REASON_CONTACT_REPLACED,
                            capture_owner_snapshot,
                        )
                        lead = Property.query.get(property_id)
                        if lead is not None:
                            capture_owner_snapshot(
                                lead, reason=REASON_CONTACT_REPLACED, commit=False,
                            )
                        now = datetime.now(timezone.utc)
                        for old in other_owners:
                            old.role = 'former_owner'
                            old.is_primary = False
                            old.superseded_at = now
                    (
                        PropertyContact.query
                        .filter_by(property_id=property_id, is_primary=True)
                        .update({'is_primary': False})
                    )
                existing_link.role = 'owner'
                existing_link.is_primary = is_primary
                existing_link.superseded_at = None
                db.session.add(existing_link)
                db.session.commit()
                from app.services.lead_refresh import refresh_lead_scoring
                refresh_lead_scoring(property_id)
                return existing_link

            raise ConflictError(
                f"Contact id={contact_id} is already linked to Property id={property_id}.",
                payload={'property_id': property_id, 'contact_id': contact_id},
            )

        # Demote existing primary contacts if the new one is primary
        # (co-owners stay active owners — only primary flag changes).
        if is_primary:
            (
                PropertyContact.query
                .filter_by(property_id=property_id, is_primary=True)
                .update({'is_primary': False})
            )

        link = PropertyContact(
            property_id=property_id,
            contact_id=contact_id,
            role=role,
            is_primary=is_primary,
        )
        db.session.add(link)

        try:
            db.session.commit()
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
            raise ConflictError(
                f"Contact id={contact_id} is already linked to Property id={property_id}.",
                payload={'property_id': property_id, 'contact_id': contact_id},
            )

        logger.info(
            "Linked Contact id=%d to Property id=%d role=%r is_primary=%s",
            contact_id, property_id, role, is_primary,
        )

        # Linking an owner contact changes the property's data-completeness and
        # owner-situation sub-scores (a linked Contact plus its phones/emails),
        # so refresh lead_score + recommended_action (error-isolated).
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(property_id)

        return link

    def unlink_contact_from_property(self, property_id: int, contact_id: int) -> None:
        """Remove a PropertyContact association without deleting the Contact.

        Parameters
        ----------
        property_id : int
        contact_id : int

        Raises
        ------
        ResourceNotFoundError
            If no PropertyContact for (property_id, contact_id) exists.
        """
        link = (
            PropertyContact.query
            .filter_by(property_id=property_id, contact_id=contact_id)
            .first()
        )
        if link is None:
            raise ResourceNotFoundError(
                f"No link found between Property id={property_id} and Contact id={contact_id}.",
                payload={'property_id': property_id, 'contact_id': contact_id},
            )
        db.session.delete(link)
        db.session.commit()
        logger.info(
            "Unlinked Contact id=%d from Property id=%d",
            contact_id, property_id,
        )

        # Removing an owner contact lowers data-completeness / owner-situation
        # inputs — refresh lead_score + recommended_action (error-isolated).
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(property_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_contacts_for_property(
        self,
        property_id: int,
        *,
        include_former_owners: bool = False,
    ) -> list:
        """Return Contacts linked to a Property, with join record metadata.

        Each element of the returned list is a tuple ``(Contact, PropertyContact)``
        so that callers have access to both the contact fields and the join
        record's ``role`` and ``is_primary`` values.

        Former owners are excluded by default (see Past owners / snapshots).
        """
        if Property.query.get(property_id) is None:
            raise ResourceNotFoundError(
                f"Property id={property_id} not found.",
                payload={'property_id': property_id},
            )

        query = (
            db.session.query(Contact, PropertyContact)
            .options(
                selectinload(Contact.phones),
                selectinload(Contact.emails),
            )
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == property_id)
        )
        if not include_former_owners:
            query = query.filter(PropertyContact.role != 'former_owner')
        return query.all()

    @staticmethod
    def serialize_contact_summary(contact: Contact, pc: PropertyContact) -> dict:
        """Serialize a property-linked contact for command-center / detail payloads."""
        from app.services.phone_confidence_service import PhoneConfidenceService

        return {
            'id': contact.id,
            'first_name': contact.first_name,
            'last_name': contact.last_name,
            'role': pc.role,
            'is_primary': bool(pc.is_primary),
            'phones': PhoneConfidenceService.serialize_contact_phones(
                contact.phones or [],
            ),
            'emails': [
                {'id': e.id, 'value': e.value, 'label': e.label}
                for e in (contact.emails or [])
            ],
        }

    def get_ordered_contacts_payload(
        self,
        property_id: int,
        *,
        include_former_owners: bool = False,
    ) -> list[dict]:
        """Contacts for a property, primary first then by PropertyContact id.

        Shape matches PropertyDetail / CommandCenter ``contacts[]``:
        id, first_name, last_name, role, is_primary, phones[], emails[].

        Former owners are excluded by default (see Past owners / snapshots).
        """
        rows = self.get_contacts_for_property(
            property_id,
            include_former_owners=include_former_owners,
        )
        rows = sorted(rows, key=lambda pair: (not pair[1].is_primary, pair[1].id))
        return [self.serialize_contact_summary(contact, pc) for contact, pc in rows]

    # ------------------------------------------------------------------
    # Upsert from flat lead owners (Sheets / GIS / backfill)
    # ------------------------------------------------------------------

    def upsert_owners_from_lead(
        self,
        lead: Property,
        *,
        phone_source: str | None = 'flat_backfill',
        commit: bool = True,
        refresh_scoring: bool = False,
    ) -> list[tuple[Contact, PropertyContact]]:
        """Upsert Owner 1 / Owner 2 from flat lead fields into PropertyContacts.

        Name-dedupes against existing links on the property. Attaches flat
        ``phone_1..7`` / ``email_1..5`` to the primary owner contact.
        """
        if lead is None or getattr(lead, 'id', None) is None:
            raise ValidationException('Lead with id is required.', field='lead_id')

        property_id = lead.id
        outgoing_owner_ids = {
            pc.contact_id
            for pc in PropertyContact.query.filter_by(
                property_id=property_id,
                role='owner',
            ).all()
        }
        owners: list[tuple[str | None, str | None]] = []
        o1_first = (lead.owner_first_name or '').strip() or None
        o1_last = (lead.owner_last_name or '').strip() or None
        if o1_first or o1_last:
            owners.append((o1_first, o1_last))
        o2_first = (getattr(lead, 'owner_2_first_name', None) or '').strip() or None
        o2_last = (getattr(lead, 'owner_2_last_name', None) or '').strip() or None
        if o2_first or o2_last:
            owners.append((o2_first, o2_last))

        from app.services.helpers.owner_organization import promote_named_owner_to_organization

        results: list[tuple[Contact, PropertyContact]] = []
        primary_contact: Contact | None = None
        person_owners: list[tuple[str | None, str | None]] = []
        promoted_any_org = False

        for first_name, last_name in owners:
            org = promote_named_owner_to_organization(
                property_id,
                first_name,
                last_name,
                source='owner_import',
                unlink_contact=False,
            )
            if org is not None:
                promoted_any_org = True
                continue
            person_owners.append((first_name, last_name))

        phone_digit_list = self._flat_phone_digits_from_lead(lead)
        email_list = self._flat_emails_from_lead(lead)
        owner_user_id = getattr(lead, 'owner_user_id', None)

        for index, (first_name, last_name) in enumerate(person_owners):
            want_primary = index == 0
            contact, link = self._upsert_named_owner(
                property_id,
                first_name,
                last_name,
                is_primary=want_primary,
                owner_user_id=owner_user_id,
                phone_digit_list=phone_digit_list if want_primary else None,
                emails=email_list if want_primary else None,
            )
            results.append((contact, link))
            if want_primary or primary_contact is None:
                primary_contact = contact

        if primary_contact is None and (
            any(getattr(lead, f'phone_{i}', None) for i in range(1, 8))
            or any(getattr(lead, f'email_{i}', None) for i in range(1, 6))
        ):
            # Phones/emails without person names — ensure a primary owner shell exists.
            contact, link = self._upsert_named_owner(
                property_id,
                None,
                'Owner',
                is_primary=True,
                owner_user_id=owner_user_id,
                phone_digit_list=phone_digit_list,
                emails=email_list,
            )
            primary_contact = contact
            results.append((contact, link))

        if primary_contact is not None:
            self._attach_flat_phones_emails(
                primary_contact,
                lead,
                phone_source=phone_source,
            )

        # When incoming person owners differ from existing owner-role links,
        # archive the unmatched ones so Past owners history is preserved.
        if results or promoted_any_org:
            kept_ids = {contact.id for contact, _link in results}
            archive_ids = outgoing_owner_ids - kept_ids
            if archive_ids:
                self._archive_unmatched_owners(
                    property_id,
                    kept_ids,
                    only_contact_ids=archive_ids,
                )

        if commit:
            db.session.commit()
        else:
            db.session.flush()

        if refresh_scoring:
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(property_id)

        if promoted_any_org and commit:
            try:
                from app.services.entity_resolution_service import EntityResolutionService
                EntityResolutionService().ensure_researched(
                    property_id, actor='owner_import',
                )
            except Exception:  # noqa: BLE001 — never block owner upsert
                logger.exception(
                    'ensure_researched failed after owner upsert for lead %s',
                    property_id,
                )

        return results

    def _reactivate_owner_link(
        self,
        link: PropertyContact,
        property_id: int,
        *,
        is_primary: bool,
    ) -> None:
        """Restore an archived/former owner link to active owner for upserts."""
        if is_primary:
            PropertyContact.query.filter_by(
                property_id=property_id, is_primary=True,
            ).update({'is_primary': False})
            link.is_primary = True
        link.role = 'owner'
        link.superseded_at = None

    def _archive_unmatched_owners(
        self,
        property_id: int,
        kept_contact_ids: set[int],
        *,
        only_contact_ids: set[int] | None = None,
    ) -> int:
        """Re-role owner links not in *kept_contact_ids* to former_owner.

        Snapshots once when any owners will be archived. No-op when nothing
        unmatched exists (avoids snapshot spam on idempotent upserts).
        """
        from datetime import datetime, timezone

        from app.services.owner_snapshot_service import (
            REASON_CONTACT_REPLACED,
            capture_owner_snapshot,
        )

        query = PropertyContact.query.filter(
            PropertyContact.property_id == property_id,
            PropertyContact.role == 'owner',
        )
        if kept_contact_ids:
            query = query.filter(~PropertyContact.contact_id.in_(kept_contact_ids))
        if only_contact_ids is not None:
            query = query.filter(PropertyContact.contact_id.in_(only_contact_ids))
        unmatched = query.all()
        if not unmatched:
            return 0

        lead = Property.query.get(property_id)
        if lead is not None:
            capture_owner_snapshot(lead, reason=REASON_CONTACT_REPLACED, commit=False)

        now = datetime.now(timezone.utc)
        for link in unmatched:
            link.role = 'former_owner'
            link.is_primary = False
            link.superseded_at = now
        return len(unmatched)

    @staticmethod
    def _flat_phone_digits_from_lead(lead: Property) -> list[str]:
        digits: list[str] = []
        seen: set[str] = set()
        for i in range(1, 8):
            raw = getattr(lead, f'phone_{i}', None)
            for value in split_phone_field(raw):
                d = phone_digits(value)
                if d and d not in seen:
                    seen.add(d)
                    digits.append(d)
        return digits

    @staticmethod
    def _flat_emails_from_lead(lead: Property) -> list[str]:
        emails: list[str] = []
        seen: set[str] = set()
        for i in range(1, 6):
            raw = getattr(lead, f'email_{i}', None)
            for value in split_email_field(raw or ''):
                e = (value or '').strip().lower()
                if e and e not in seen:
                    seen.add(e)
                    emails.append(e)
        return emails

    def _user_property_scope_filter(self, owner_user_id: str | None):
        """Scope Property queries to the same CRM user (including both-null)."""
        if owner_user_id is None:
            return Property.owner_user_id.is_(None)
        return Property.owner_user_id == owner_user_id

    def find_reusable_contact_for_user(
        self,
        owner_user_id: str | None,
        *,
        phone_digit_list: list[str] | None = None,
        emails: list[str] | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> Contact | None:
        """Find an existing Contact already linked to this user's properties.

        Match by lowercased email or normalized phone digits. When a person name
        is supplied, require ``owner_names_equivalent`` so shared office numbers
        do not attach the wrong person.
        """
        from app.services.plugins.owner_name_utils import owner_names_equivalent

        emails_lower = [
            (e or '').strip().lower() for e in (emails or []) if (e or '').strip()
        ]
        phones = [d for d in (phone_digit_list or []) if d]
        if not emails_lower and not phones:
            return None

        require_name = bool((first_name or '').strip() or (last_name or '').strip())
        scope = self._user_property_scope_filter(owner_user_id)
        contact_ids_q = (
            db.session.query(PropertyContact.contact_id)
            .join(Property, Property.id == PropertyContact.property_id)
            .filter(scope)
        )

        def _name_ok(contact: Contact) -> bool:
            if not require_name:
                return True
            return owner_names_equivalent(
                contact.first_name, contact.last_name, first_name, last_name,
            )

        if emails_lower:
            hits = (
                db.session.query(Contact)
                .join(ContactEmail, ContactEmail.contact_id == Contact.id)
                .filter(Contact.id.in_(contact_ids_q))
                .filter(db.func.lower(ContactEmail.value).in_(emails_lower))
                .order_by(Contact.id.asc())
                .all()
            )
            for hit in hits:
                if _name_ok(hit):
                    return hit

        if phones:
            wanted = set(phones)
            phone_rows = (
                db.session.query(Contact, ContactPhone)
                .join(ContactPhone, ContactPhone.contact_id == Contact.id)
                .filter(Contact.id.in_(contact_ids_q))
                .order_by(Contact.id.asc())
                .all()
            )
            for contact, phone in phone_rows:
                if phone_digits(phone.value) not in wanted:
                    continue
                if _name_ok(contact):
                    return contact
        return None

    def _upsert_named_owner(
        self,
        property_id: int,
        first_name: str | None,
        last_name: str | None,
        *,
        is_primary: bool,
        owner_user_id: str | None = None,
        phone_digit_list: list[str] | None = None,
        emails: list[str] | None = None,
    ) -> tuple[Contact, PropertyContact]:
        from app.services.plugins.owner_name_utils import owner_names_equivalent

        first_norm = (first_name or '').strip().lower()
        last_norm = (last_name or '').strip().lower()

        existing_rows = (
            db.session.query(Contact, PropertyContact)
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == property_id)
            .all()
        )
        for contact, link in existing_rows:
            c_first = (contact.first_name or '').strip().lower()
            c_last = (contact.last_name or '').strip().lower()
            exact = c_first == first_norm and c_last == last_norm
            fuzzy = (not exact) and owner_names_equivalent(
                contact.first_name, contact.last_name, first_name, last_name,
            )
            if not exact and not fuzzy:
                continue
            if link.role not in ('owner', 'former_owner'):
                continue
            # Prefer the more complete first name (e.g. JOSEPH A over Joseph)
            if (first_name or '').strip() and len((first_name or '').strip()) > len(
                (contact.first_name or '').strip()
            ):
                contact.first_name = first_name
            if (last_name or '').strip() and not (contact.last_name or '').strip():
                contact.last_name = last_name
            if link.role == 'former_owner':
                self._reactivate_owner_link(link, property_id, is_primary=is_primary)
            elif is_primary:
                PropertyContact.query.filter_by(
                    property_id=property_id, is_primary=True,
                ).update({'is_primary': False})
                link.is_primary = True
            return contact, link

        # Cross-property reuse: same user + phone/email (+ name gate) on another building.
        reused = self.find_reusable_contact_for_user(
            owner_user_id,
            phone_digit_list=phone_digit_list,
            emails=emails,
            first_name=first_name,
            last_name=last_name,
        )
        if reused is not None:
            for contact, link in existing_rows:
                if contact.id == reused.id:
                    if link.role not in ('owner', 'former_owner'):
                        # Keep attorney/manager/etc. intact — do not convert to owner.
                        reused = None
                        break
                    if link.role == 'former_owner':
                        self._reactivate_owner_link(link, property_id, is_primary=is_primary)
                    elif is_primary:
                        PropertyContact.query.filter_by(
                            property_id=property_id, is_primary=True,
                        ).update({'is_primary': False})
                        link.is_primary = True
                    return reused, link
            if reused is not None:
                if is_primary:
                    PropertyContact.query.filter_by(
                        property_id=property_id, is_primary=True,
                    ).update({'is_primary': False})
                if (first_name or '').strip() and len((first_name or '').strip()) > len(
                    (reused.first_name or '').strip()
                ):
                    reused.first_name = first_name
                if (last_name or '').strip() and not (reused.last_name or '').strip():
                    reused.last_name = last_name
                link = PropertyContact(
                    property_id=property_id,
                    contact_id=reused.id,
                    role='owner',
                    is_primary=is_primary or not existing_rows,
                )
                try:
                    with db.session.begin_nested():
                        db.session.add(link)
                        db.session.flush()
                except sqlalchemy.exc.IntegrityError:
                    existing = (
                        PropertyContact.query
                        .filter_by(property_id=property_id, contact_id=reused.id)
                        .first()
                    )
                    if existing is None:
                        raise
                    if existing.role not in ('owner', 'former_owner'):
                        # Race: non-owner link appeared — create a distinct owner contact.
                        reused = None
                    else:
                        self._reactivate_owner_link(
                            existing, property_id, is_primary=is_primary,
                        )
                        return reused, existing
                else:
                    return reused, link

        if is_primary:
            PropertyContact.query.filter_by(
                property_id=property_id, is_primary=True,
            ).update({'is_primary': False})

        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            role='owner',
        )
        db.session.add(contact)
        db.session.flush()
        link = PropertyContact(
            property_id=property_id,
            contact_id=contact.id,
            role='owner',
            is_primary=is_primary or not existing_rows,
        )
        db.session.add(link)
        db.session.flush()
        return contact, link

    RELATED_PROPERTIES_CAP = 15

    @staticmethod
    def _escape_like(value: str) -> str:
        return (
            (value or '')
            .replace('\\', '\\\\')
            .replace('%', '\\%')
            .replace('_', '\\_')
        )

    def _serialize_related_property(self, p: Property) -> dict:
        return {
            'id': p.id,
            'property_street': p.property_street,
            'property_city': p.property_city,
            'lead_status': p.lead_status,
            'lead_score': float(p.lead_score) if p.lead_score is not None else None,
        }

    def _is_same_building(self, a: Property, b: Property) -> bool:
        from app.services.lead_merge_utils import streets_match_normalized
        from app.services.plugins.pin_utils import normalize_pin_for_socrata

        if streets_match_normalized(a.property_street, b.property_street):
            return True
        pin_a = normalize_pin_for_socrata(a.county_assessor_pin or '') or ''
        pin_b = normalize_pin_for_socrata(b.county_assessor_pin or '') or ''
        return bool(pin_a and pin_b and pin_a == pin_b)

    def _owner_names_for_related(self, lead: Property) -> tuple[str | None, str | None]:
        from app.services.plugins.owner_name_utils import expand_owner_name_parts

        first = (lead.owner_first_name or '').strip() or None
        last = (lead.owner_last_name or '').strip() or None
        if not first and not last:
            primary_row = (
                db.session.query(Contact)
                .join(PropertyContact, PropertyContact.contact_id == Contact.id)
                .filter(
                    PropertyContact.property_id == lead.id,
                    PropertyContact.is_primary.is_(True),
                )
                .first()
            )
            if primary_row is None:
                primary_row = (
                    db.session.query(Contact)
                    .join(PropertyContact, PropertyContact.contact_id == Contact.id)
                    .filter(PropertyContact.property_id == lead.id)
                    .order_by(Contact.id.asc())
                    .first()
                )
            if primary_row is not None:
                first = (primary_row.first_name or '').strip() or None
                last = (primary_row.last_name or '').strip() or None
        first, last = expand_owner_name_parts(first, last)
        return (first or None), (last or None)

    def get_related_properties(
        self,
        lead_id: int,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        """Other buildings for the same person (shared Contact and/or owner name).

        Never merges leads — returns skinny dicts for CC / search badges.
        Excludes same-building address/PIN variants.
        Only traverses **owner** role links within the lead's ``owner_user_id`` scope.
        """
        from app.services.plugins.owner_name_utils import (
            is_matchable_person_name,
            owner_names_equivalent,
        )
        from sqlalchemy import case, or_

        cap = self.RELATED_PROPERTIES_CAP if limit is None else limit
        lead = db.session.get(Property, lead_id)
        if lead is None:
            return []

        related_ids: set[int] = set()
        scope = self._user_property_scope_filter(lead.owner_user_id)

        contact_ids = [
            row.contact_id
            for row in (
                PropertyContact.query
                .join(Property, Property.id == PropertyContact.property_id)
                .filter(
                    PropertyContact.property_id == lead_id,
                    PropertyContact.role == 'owner',
                    scope,
                )
                .all()
            )
        ]
        if contact_ids:
            for (pid,) in (
                db.session.query(PropertyContact.property_id)
                .join(Property, Property.id == PropertyContact.property_id)
                .filter(
                    PropertyContact.contact_id.in_(contact_ids),
                    PropertyContact.property_id != lead_id,
                    PropertyContact.role == 'owner',
                    scope,
                )
                .all()
            ):
                related_ids.add(pid)

        first, last = self._owner_names_for_related(lead)
        if is_matchable_person_name(first, last):
            q = Property.query.filter(
                Property.id != lead_id,
                scope,
            )
            if last:
                last_l = last.lower()
                escaped = self._escape_like(last_l)
                q = q.filter(
                    or_(
                        db.func.lower(db.func.trim(Property.owner_last_name)) == last_l,
                        db.func.lower(Property.owner_first_name).like(
                            f'% {escaped}', escape='\\',
                        ),
                    )
                )
            for other in q.limit(250).all():
                if not owner_names_equivalent(
                    first, last, other.owner_first_name, other.owner_last_name,
                ):
                    continue
                related_ids.add(other.id)

        if not related_ids:
            return []

        props = (
            Property.query
            .filter(Property.id.in_(related_ids), scope)
            .order_by(
                case((Property.lead_score.is_(None), 1), else_=0),
                Property.lead_score.desc(),
                Property.id.asc(),
            )
            .all()
        )
        out: list[dict] = []
        for p in props:
            if self._is_same_building(lead, p):
                continue
            out.append(self._serialize_related_property(p))
            if len(out) >= cap:
                break
        return out

    def property_count_for_lead(self, lead_id: int) -> int:
        """Number of buildings in this person's portfolio including *lead_id*."""
        return 1 + len(self.get_related_properties(lead_id))

    def person_identity_for_lead(self, lead: Property) -> dict[str, str | None]:
        """Stable person key + display name for search portfolio grouping.

        Keys on ``owner_user_id`` + expanded last name + first given-name token so
        ``GILBERT JANSON`` and ``GILBERT E JANSON`` share one key. When an owner
        Contact is linked to multiple properties in this user scope, prefer
        ``contact:<id>``.
        """
        import re
        from app.services.plugins.owner_name_utils import (
            expand_owner_name_parts,
            is_generic_owner_name,
        )

        raw_owner_name = ' '.join(
            part for part in (
                (lead.owner_first_name or '').strip(),
                (lead.owner_last_name or '').strip(),
            ) if part
        )
        if is_generic_owner_name(raw_owner_name):
            return {
                'person_key': f'lead:{lead.id}',
                'owner_display_name': raw_owner_name or None,
            }

        scope = self._user_property_scope_filter(lead.owner_user_id)
        for (cid,) in (
            db.session.query(PropertyContact.contact_id)
            .join(Property, Property.id == PropertyContact.property_id)
            .filter(
                PropertyContact.property_id == lead.id,
                PropertyContact.role == 'owner',
                scope,
            )
            .all()
        ):
            prop_count = (
                PropertyContact.query
                .join(Property, Property.id == PropertyContact.property_id)
                .filter(
                    PropertyContact.contact_id == cid,
                    PropertyContact.role == 'owner',
                    scope,
                )
                .count()
            )
            if prop_count < 2:
                continue
            contact = db.session.get(Contact, cid)
            display = None
            if contact is not None:
                display = ' '.join(
                    p for p in (
                        (contact.first_name or '').strip(),
                        (contact.last_name or '').strip(),
                    ) if p
                ) or None
            user = lead.owner_user_id or ''
            return {
                'person_key': f'{user}|contact:{cid}',
                'owner_display_name': display,
            }

        first = (lead.owner_first_name or '').strip() or None
        last = (lead.owner_last_name or '').strip() or None
        first, last = expand_owner_name_parts(first, last)
        last_norm = re.sub(r'[^a-z]', '', (last or '').lower())
        tokens = [re.sub(r'[^a-z]', '', t) for t in (first or '').lower().split() if t]
        tokens = [t for t in tokens if t]
        first_token = tokens[0] if tokens else ''
        user = lead.owner_user_id or ''
        if last_norm and first_token:
            person_key = f'{user}|{last_norm}|{first_token}'
        else:
            person_key = f'lead:{lead.id}'

        if first and last:
            display = f'{first} {last}'.strip()
        else:
            display = (first or last or '').strip() or None
        return {
            'person_key': person_key,
            'owner_display_name': display,
        }

    def _person_identity_from_maps(
        self,
        lead: Property,
        lead_contacts: dict[int, set[int]],
        contact_scoped_props: dict[int, set[int]],
        contacts_by_id: dict[int, Contact],
    ) -> dict[str, str | None]:
        """Build person identity using preloaded contact / property maps (no queries)."""
        import re
        from app.services.plugins.owner_name_utils import (
            expand_owner_name_parts,
            is_generic_owner_name,
        )

        raw_owner_name = ' '.join(
            part for part in (
                (lead.owner_first_name or '').strip(),
                (lead.owner_last_name or '').strip(),
            ) if part
        )
        if is_generic_owner_name(raw_owner_name):
            return {
                'person_key': f'lead:{lead.id}',
                'owner_display_name': raw_owner_name or None,
            }

        for cid in sorted(lead_contacts.get(lead.id, set())):
            if len(contact_scoped_props.get(cid, set())) < 2:
                continue
            contact = contacts_by_id.get(cid)
            display = None
            if contact is not None:
                display = ' '.join(
                    p for p in (
                        (contact.first_name or '').strip(),
                        (contact.last_name or '').strip(),
                    ) if p
                ) or None
            user = lead.owner_user_id or ''
            return {
                'person_key': f'{user}|contact:{cid}',
                'owner_display_name': display,
            }

        first = (lead.owner_first_name or '').strip() or None
        last = (lead.owner_last_name or '').strip() or None
        first, last = expand_owner_name_parts(first, last)
        last_norm = re.sub(r'[^a-z]', '', (last or '').lower())
        tokens = [re.sub(r'[^a-z]', '', t) for t in (first or '').lower().split() if t]
        tokens = [t for t in tokens if t]
        first_token = tokens[0] if tokens else ''
        user = lead.owner_user_id or ''
        if last_norm and first_token:
            person_key = f'{user}|{last_norm}|{first_token}'
        else:
            person_key = f'lead:{lead.id}'

        if first and last:
            display = f'{first} {last}'.strip()
        else:
            display = (first or last or '').strip() or None
        return {
            'person_key': person_key,
            'owner_display_name': display,
        }

    def portfolio_enrichment_for_leads(self, lead_ids: list[int]) -> dict[int, dict]:
        """Batched person_key / property_count / portfolio rows for search.

        Avoids per-lead ``person_identity_for_lead`` / ``get_related_properties``
        calls. Shared-contact traversal is owner-role + user-scoped only.
        """
        from collections import defaultdict
        from app.services.plugins.owner_name_utils import (
            expand_owner_name_parts,
            is_matchable_person_name,
            owner_names_equivalent,
        )
        from sqlalchemy import or_

        if not lead_ids:
            return {}

        leads = Property.query.filter(Property.id.in_(lead_ids)).all()
        by_id = {lead.id: lead for lead in leads}
        out: dict[int, dict] = {}

        page_links = (
            PropertyContact.query
            .join(Property, Property.id == PropertyContact.property_id)
            .filter(
                PropertyContact.property_id.in_(lead_ids),
                PropertyContact.role == 'owner',
            )
            .all()
        )
        contact_ids = {link.contact_id for link in page_links}
        lead_contacts: dict[int, set[int]] = defaultdict(set)
        lead_primary_contact: dict[int, int] = {}
        for link in page_links:
            lead_contacts[link.property_id].add(link.contact_id)
            if link.is_primary:
                lead_primary_contact[link.property_id] = link.contact_id

        # contact_id -> (property_id, owner_user_id) for owner links only
        contact_prop_users: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
        if contact_ids:
            for cid, pid, uid in (
                db.session.query(
                    PropertyContact.contact_id,
                    PropertyContact.property_id,
                    Property.owner_user_id,
                )
                .join(Property, Property.id == PropertyContact.property_id)
                .filter(
                    PropertyContact.contact_id.in_(contact_ids),
                    PropertyContact.role == 'owner',
                )
                .all()
            ):
                contact_prop_users[cid].append((pid, uid))

        contacts_by_id: dict[int, Contact] = {}
        if contact_ids:
            contacts_by_id = {
                c.id: c for c in Contact.query.filter(Contact.id.in_(contact_ids)).all()
            }

        related_ids_by_lead: dict[int, set[int]] = {lid: set() for lid in lead_ids}
        contact_scoped_props: dict[int, dict[int, set[int]]] = defaultdict(
            lambda: defaultdict(set),
        )
        # contact_scoped_props[lead_id][contact_id] = props in that lead's user scope
        for lid in lead_ids:
            lead = by_id.get(lid)
            if lead is None:
                continue
            for cid in lead_contacts.get(lid, set()):
                for pid, uid in contact_prop_users.get(cid, []):
                    if uid != lead.owner_user_id:
                        continue
                    contact_scoped_props[lid][cid].add(pid)
                    if pid != lid:
                        related_ids_by_lead[lid].add(pid)

        def _names_for_page_lead(lead: Property) -> tuple[str | None, str | None]:
            """Match `_owner_names_for_related` using preloaded owner contacts."""
            first = (lead.owner_first_name or '').strip() or None
            last = (lead.owner_last_name or '').strip() or None
            if not first and not last:
                cid = lead_primary_contact.get(lead.id)
                if cid is None:
                    cids = lead_contacts.get(lead.id) or set()
                    cid = min(cids) if cids else None
                contact = contacts_by_id.get(cid) if cid is not None else None
                if contact is not None:
                    first = (contact.first_name or '').strip() or None
                    last = (contact.last_name or '').strip() or None
            first, last = expand_owner_name_parts(first, last)
            return (first or None), (last or None)

        # Name fallback: one candidate query per (user, last-name) bucket
        name_buckets: dict[tuple[str | None, str], list[Property]] = defaultdict(list)
        names_by_lead: dict[int, tuple[str | None, str | None]] = {}
        for lead in leads:
            first, last = _names_for_page_lead(lead)
            names_by_lead[lead.id] = (first, last)
            if not last or not is_matchable_person_name(first, last):
                continue
            name_buckets[(lead.owner_user_id, last.lower())].append(lead)

        for (uid, last_l), bucket in name_buckets.items():
            scope = self._user_property_scope_filter(uid)
            escaped = self._escape_like(last_l)
            candidates = (
                Property.query
                .filter(
                    scope,
                    or_(
                        db.func.lower(db.func.trim(Property.owner_last_name)) == last_l,
                        db.func.lower(Property.owner_first_name).like(
                            f'% {escaped}', escape='\\',
                        ),
                    ),
                )
                .limit(250)
                .all()
            )
            for lead in bucket:
                first, last = names_by_lead[lead.id]
                for other in candidates:
                    if other.id == lead.id:
                        continue
                    if not owner_names_equivalent(
                        first, last, other.owner_first_name, other.owner_last_name,
                    ):
                        continue
                    related_ids_by_lead[lead.id].add(other.id)
                    if other.id in related_ids_by_lead:
                        related_ids_by_lead[other.id].add(lead.id)

        all_prop_ids: set[int] = set(by_id.keys())
        for s in related_ids_by_lead.values():
            all_prop_ids |= s
        missing = all_prop_ids - set(by_id.keys())
        if missing:
            for p in Property.query.filter(Property.id.in_(missing)).all():
                by_id[p.id] = p

        for lid in lead_ids:
            lead = by_id.get(lid)
            if lead is None:
                continue
            # Flatten scoped props for identity helper
            scoped_flat: dict[int, set[int]] = {
                cid: props for cid, props in contact_scoped_props.get(lid, {}).items()
            }
            identity = self._person_identity_from_maps(
                lead, lead_contacts, scoped_flat, contacts_by_id,
            )

            related_by_id: dict[int, dict] = {}
            for rid in related_ids_by_lead.get(lid, set()):
                other = by_id.get(rid)
                if other is None or other.id == lid:
                    continue
                if other.owner_user_id != lead.owner_user_id:
                    continue
                if self._is_same_building(lead, other):
                    continue
                related_by_id[rid] = self._serialize_related_property(other)

            portfolio = [
                self._serialize_related_property(lead),
                *sorted(
                    related_by_id.values(),
                    key=lambda r: (-(r.get('lead_score') or -1), r['id']),
                ),
            ]
            seen: set[int] = set()
            unique: list[dict] = []
            for row in portfolio:
                rid = row.get('id')
                if rid is None or rid in seen:
                    continue
                seen.add(rid)
                unique.append(row)
            out[lid] = {
                'person_key': identity['person_key'],
                'owner_display_name': identity['owner_display_name'],
                'property_street': lead.property_street,
                'property_count': len(unique),
                'portfolio_properties': unique,
            }
        return out

    def unlink_duplicate_person_owners(self, property_id: int) -> int:
        """Unlink redundant person owner contacts that fuzzy-match a kept row.

        Prefers the primary link, then the more complete name, then lowest id.
        Returns number of PropertyContact rows removed.
        """
        from app.services.plugins.owner_name_utils import (
            is_address_like_contact,
            is_entity_contact,
            owner_names_equivalent,
        )

        rows = (
            db.session.query(Contact, PropertyContact)
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == property_id)
            .order_by(Contact.id.asc())
            .all()
        )
        people = [
            (c, link)
            for c, link in rows
            if not is_entity_contact(c.first_name, c.last_name)
            and not is_address_like_contact(c.first_name, c.last_name)
        ]
        removed = 0
        kept: list[tuple[Contact, PropertyContact]] = []
        for contact, link in people:
            match_idx = next(
                (
                    i
                    for i, (kept_c, _) in enumerate(kept)
                    if owner_names_equivalent(
                        kept_c.first_name, kept_c.last_name,
                        contact.first_name, contact.last_name,
                    )
                ),
                None,
            )
            if match_idx is None:
                kept.append((contact, link))
                continue

            kept_c, kept_link = kept[match_idx]
            prefer_new = False
            if link.is_primary and not kept_link.is_primary:
                prefer_new = True
            elif kept_link.is_primary and not link.is_primary:
                prefer_new = False
            elif len((contact.first_name or '').strip()) > len(
                (kept_c.first_name or '').strip()
            ):
                prefer_new = True
            elif contact.id < kept_c.id and len(
                (contact.first_name or '').strip()
            ) == len((kept_c.first_name or '').strip()):
                prefer_new = True

            if prefer_new:
                db.session.delete(kept_link)
                kept[match_idx] = (contact, link)
            else:
                db.session.delete(link)
            removed += 1

        if removed:
            db.session.flush()
        return removed

    def _attach_flat_phones_emails(
        self,
        contact: Contact,
        lead: Property,
        *,
        phone_source: str | None,
    ) -> None:
        existing_phones = {
            ''.join(ch for ch in (p.value or '') if ch.isdigit())
            for p in (contact.phones or [])
        }
        existing_emails = {
            (e.value or '').strip().lower()
            for e in (contact.emails or [])
        }

        for i in range(1, 8):
            raw = getattr(lead, f'phone_{i}', None)
            if not raw or not str(raw).strip():
                continue
            for value in split_phone_field(raw):
                digits = ''.join(ch for ch in value if ch.isdigit())
                if digits and digits in existing_phones:
                    continue
                if digits:
                    existing_phones.add(digits)
                db.session.add(ContactPhone(
                    contact_id=contact.id,
                    value=value[:50],
                    label='other',
                    source=phone_source,
                ))

        for i in range(1, 6):
            raw = getattr(lead, f'email_{i}', None)
            if not raw or not str(raw).strip():
                continue
            for value in split_email_field(raw):
                normalized = value.lower()
                if normalized in existing_emails:
                    continue
                existing_emails.add(normalized)
                db.session.add(ContactEmail(
                    contact_id=contact.id,
                    value=value[:255],
                    label='other',
                ))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_contact_or_raise(self, contact_id: int) -> Contact:
        """Fetch a Contact by id or raise ResourceNotFoundError."""
        contact = Contact.query.get(contact_id)
        if contact is None:
            raise ResourceNotFoundError(
                f"Contact id={contact_id} not found.",
                payload={'contact_id': contact_id},
            )
        return contact

    @staticmethod
    def _validate_name(data: dict) -> None:
        """Raise ValidationException if both first_name and last_name are empty.

        Parameters
        ----------
        data : dict
            Must contain ``first_name`` and/or ``last_name`` keys.

        Raises
        ------
        ValidationException
        """
        first = _strip_invisible(data.get('first_name') or '')
        last = _strip_invisible(data.get('last_name') or '')
        if not first and not last:
            raise ValidationException(
                "At least one of first_name or last_name is required.",
                field='first_name',
            )


def batch_owner_display_for_leads(lead_ids: list[int]) -> dict[int, dict]:
    """Batch-resolve owner display fields from PropertyContacts.

    For each lead, walks linked **owner-role** contacts primary-first then by
    join id and takes the first non-empty name, phone, and email (phone/email
    may come from a later owner contact if the primary has none).

    Returns
    -------
    dict[int, dict]
        ``lead_id -> {first_name, last_name, owner_display_name, best_phone,
        best_email}``. Leads with no linked owner contacts are omitted.
    """
    if not lead_ids:
        return {}

    rows = (
        db.session.query(PropertyContact, Contact)
        .options(
            selectinload(Contact.phones),
            selectinload(Contact.emails),
        )
        .join(Contact, Contact.id == PropertyContact.contact_id)
        .filter(PropertyContact.property_id.in_(lead_ids))
        .filter(
            db.or_(
                PropertyContact.role == 'owner',
                PropertyContact.role.is_(None),
            )
        )
        .order_by(
            PropertyContact.property_id.asc(),
            PropertyContact.is_primary.desc(),
            PropertyContact.id.asc(),
        )
        .all()
    )

    by_lead: dict[int, list[Contact]] = {}
    for pc, contact in rows:
        by_lead.setdefault(pc.property_id, []).append(contact)

    result: dict[int, dict] = {}
    for lead_id, contacts in by_lead.items():
        first_name = None
        last_name = None
        best_phone = None
        best_email = None
        for contact in contacts:
            if first_name is None and last_name is None:
                fn = (contact.first_name or '').strip() or None
                ln = (contact.last_name or '').strip() or None
                if fn or ln:
                    first_name, last_name = fn, ln
            if best_phone is None:
                for phone in (contact.phones or []):
                    value = (phone.value or '').strip()
                    if value:
                        best_phone = value
                        break
            if best_email is None:
                for email in (contact.emails or []):
                    value = (email.value or '').strip()
                    if value:
                        best_email = value
                        break
            if first_name is not None or last_name is not None:
                if best_phone is not None and best_email is not None:
                    break

        display_name = ' '.join(
            part for part in (first_name, last_name) if part
        ) or None
        if not display_name and not best_phone and not best_email:
            continue
        result[lead_id] = {
            'first_name': first_name,
            'last_name': last_name,
            'owner_display_name': display_name,
            'best_phone': best_phone,
            'best_email': best_email,
        }
    return result
