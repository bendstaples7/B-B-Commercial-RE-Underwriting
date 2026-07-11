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
from app.services.contact_backfill import split_phone_field, split_email_field

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

        # Demote existing primary contacts if the new one is primary
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

    def get_contacts_for_property(self, property_id: int) -> list:
        """Return all Contacts linked to a Property, with join record metadata.

        Each element of the returned list is a tuple ``(Contact, PropertyContact)``
        so that callers have access to both the contact fields and the join
        record's ``role`` and ``is_primary`` values.

        Parameters
        ----------
        property_id : int

        Returns
        -------
        list[tuple[Contact, PropertyContact]]

        Raises
        ------
        ResourceNotFoundError
            If no Property with *property_id* exists.
        """
        if Property.query.get(property_id) is None:
            raise ResourceNotFoundError(
                f"Property id={property_id} not found.",
                payload={'property_id': property_id},
            )

        rows = (
            db.session.query(Contact, PropertyContact)
            .options(
                selectinload(Contact.phones),
                selectinload(Contact.emails),
            )
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == property_id)
            .all()
        )
        return rows

    @staticmethod
    def serialize_contact_summary(contact: Contact, pc: PropertyContact) -> dict:
        """Serialize a property-linked contact for command-center / detail payloads."""
        return {
            'id': contact.id,
            'first_name': contact.first_name,
            'last_name': contact.last_name,
            'role': pc.role,
            'is_primary': bool(pc.is_primary),
            'phones': [
                {'id': p.id, 'value': p.value, 'label': p.label}
                for p in (contact.phones or [])
            ],
            'emails': [
                {'id': e.id, 'value': e.value, 'label': e.label}
                for e in (contact.emails or [])
            ],
        }

    def get_ordered_contacts_payload(self, property_id: int) -> list[dict]:
        """Contacts for a property, primary first then by PropertyContact id.

        Shape matches PropertyDetail / CommandCenter ``contacts[]``:
        id, first_name, last_name, role, is_primary, phones[], emails[].
        """
        rows = self.get_contacts_for_property(property_id)
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
        owners: list[tuple[str | None, str | None, bool]] = []
        o1_first = (lead.owner_first_name or '').strip() or None
        o1_last = (lead.owner_last_name or '').strip() or None
        if o1_first or o1_last:
            owners.append((o1_first, o1_last, True))
        o2_first = (getattr(lead, 'owner_2_first_name', None) or '').strip() or None
        o2_last = (getattr(lead, 'owner_2_last_name', None) or '').strip() or None
        if o2_first or o2_last:
            # Owner 2 is primary when Owner 1 was absent.
            owners.append((o2_first, o2_last, not owners))

        results: list[tuple[Contact, PropertyContact]] = []
        primary_contact: Contact | None = None

        for first_name, last_name, want_primary in owners:
            contact, link = self._upsert_named_owner(
                property_id,
                first_name,
                last_name,
                is_primary=want_primary,
            )
            results.append((contact, link))
            if want_primary or primary_contact is None:
                primary_contact = contact

        if primary_contact is None and (
            any(getattr(lead, f'phone_{i}', None) for i in range(1, 8))
            or any(getattr(lead, f'email_{i}', None) for i in range(1, 6))
        ):
            # Phones/emails without names — ensure a primary owner shell exists.
            contact, link = self._upsert_named_owner(
                property_id, None, 'Owner', is_primary=True,
            )
            primary_contact = contact
            results.append((contact, link))

        if primary_contact is not None:
            self._attach_flat_phones_emails(
                primary_contact,
                lead,
                phone_source=phone_source,
            )

        if commit:
            db.session.commit()
        else:
            db.session.flush()

        if refresh_scoring:
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(property_id)

        return results

    def _upsert_named_owner(
        self,
        property_id: int,
        first_name: str | None,
        last_name: str | None,
        *,
        is_primary: bool,
    ) -> tuple[Contact, PropertyContact]:
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
            if c_first == first_norm and c_last == last_norm:
                if is_primary and not link.is_primary:
                    PropertyContact.query.filter_by(
                        property_id=property_id, is_primary=True,
                    ).update({'is_primary': False})
                    link.is_primary = True
                    link.role = link.role or 'owner'
                return contact, link

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
