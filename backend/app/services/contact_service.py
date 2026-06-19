"""ContactService — business logic for Contact CRUD and Property-Contact linking.

Implements all operations required by the property-contact-model spec:
  - create_contact / update_contact / delete_contact
  - link_contact_to_property / unlink_contact_from_property
  - get_contacts_for_property
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
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == property_id)
            .all()
        )
        return rows

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
