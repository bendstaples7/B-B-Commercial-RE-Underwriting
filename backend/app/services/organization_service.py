"""OrganizationService — business logic for Organization CRUD, linking, and audit logging.

Implements all operations required by Requirements 1.1–1.6:
  - create / update / soft_delete with full audit trail
  - link_property / unlink_property (PropertyOrganizationLink)
  - link_owner / unlink_owner (OwnerOrganizationLink)
  - get_audit_log
  - list (paginated, filterable)
"""
import logging
import re
import unicodedata
from datetime import datetime
from typing import Optional

from app import db
from app.models.organization import Organization
from app.models.organization_audit_log import OrganizationAuditLog
from app.models.property_organization_link import PropertyOrganizationLink
from app.models.owner_organization_link import OwnerOrganizationLink
from app.exceptions import OrganizationValidationError, ResourceNotFoundError

logger = logging.getLogger(__name__)

# Fields that are tracked in the audit log when updated
AUDITABLE_FIELDS = ('name', 'org_type', 'status', 'notes', 'source', 'hubspot_company_id')

# Regex that matches any Unicode whitespace or control character (categories Zs and Cc).
# Used to strip all non-printable / non-visible characters before empty-check validation.
_WHITESPACE_AND_CONTROL_RE = re.compile(r'[\s\x00-\x1f\x7f-\x9f\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+')


def _strip_invisible(value: str) -> str:
    """Strip all Unicode whitespace and control characters from *value*.

    This is stricter than ``str.strip()`` which only removes ASCII whitespace.
    It handles the full Unicode Zs (space separators) and Cc (control characters)
    categories so that inputs like '\\x7f' or '\\u205f' are treated as empty.
    """
    # Remove all characters whose Unicode category starts with 'C' (control/format/etc.)
    # or is 'Zs' (space separator), then strip remaining ASCII whitespace.
    cleaned = ''.join(
        ch for ch in value
        if not (unicodedata.category(ch).startswith('C') or unicodedata.category(ch) == 'Zs')
    )
    return cleaned.strip()


class OrganizationService:
    """Service class for all Organization-related operations.

    All database writes use ``db.session`` and commit at the end of each
    operation.  Callers are responsible for providing a valid application
    context (i.e. running inside a Flask request or app-context block).
    """

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, data: dict, changed_by: str) -> Organization:
        """Create a new Organization and write a creation audit log entry.

        Parameters
        ----------
        data : dict
            Fields to set on the new Organization.  ``name`` is required
            and must be a non-empty string.
        changed_by : str
            Identifier of the user or process performing the action
            (stored in the audit log).

        Returns
        -------
        Organization
            The newly created and persisted Organization.

        Raises
        ------
        OrganizationValidationError
            If ``name`` is missing or empty.
        """
        name = _strip_invisible(data.get('name') or '')
        if not name:
            raise OrganizationValidationError(
                "Organization name must not be empty.",
                field='name',
                value=data.get('name'),
            )

        org = Organization(
            name=name,
            org_type=data.get('org_type', 'unknown'),
            status=data.get('status', 'unknown'),
            notes=data.get('notes'),
            source=data.get('source'),
            hubspot_company_id=data.get('hubspot_company_id'),
        )
        db.session.add(org)
        db.session.flush()  # populate org.id before writing audit log

        audit = OrganizationAuditLog(
            organization_id=org.id,
            field_name='__created__',
            old_value=None,
            new_value=name,
            changed_by=changed_by,
        )
        db.session.add(audit)
        db.session.commit()

        logger.info("Created Organization id=%d name=%r by %s", org.id, org.name, changed_by)
        return org

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, org_id: int, data: dict, changed_by: str) -> Organization:
        """Update an existing Organization and write per-field audit log entries.

        Only fields present in *data* are updated.  An audit log entry is
        written for each field whose value actually changes.

        Parameters
        ----------
        org_id : int
        data : dict
            Partial or full set of updatable fields.
        changed_by : str

        Returns
        -------
        Organization
            The updated Organization.

        Raises
        ------
        ResourceNotFoundError
            If no Organization with *org_id* exists.
        OrganizationValidationError
            If ``name`` is explicitly provided but is empty.
        """
        org = self._get_or_raise(org_id)

        # Validate name if provided
        if 'name' in data:
            name = _strip_invisible(data['name'] or '')
            if not name:
                raise OrganizationValidationError(
                    "Organization name must not be empty.",
                    field='name',
                    value=data['name'],
                )
            data = dict(data, name=name)

        audit_entries = []
        for field in AUDITABLE_FIELDS:
            if field not in data:
                continue
            old_val = getattr(org, field)
            new_val = data[field]
            if old_val != new_val:
                setattr(org, field, new_val)
                audit_entries.append(OrganizationAuditLog(
                    organization_id=org.id,
                    field_name=field,
                    old_value=str(old_val) if old_val is not None else None,
                    new_value=str(new_val) if new_val is not None else None,
                    changed_by=changed_by,
                ))

        org.updated_at = datetime.utcnow()
        for entry in audit_entries:
            db.session.add(entry)

        db.session.commit()
        logger.info(
            "Updated Organization id=%d (%d fields changed) by %s",
            org.id, len(audit_entries), changed_by,
        )
        return org

    # ------------------------------------------------------------------
    # Soft-delete
    # ------------------------------------------------------------------

    def soft_delete(self, org_id: int, changed_by: str) -> Organization:
        """Soft-delete an Organization by setting its status to 'inactive'.

        Writes an audit log entry recording the status change.

        Parameters
        ----------
        org_id : int
        changed_by : str

        Returns
        -------
        Organization
            The updated Organization.

        Raises
        ------
        ResourceNotFoundError
            If no Organization with *org_id* exists.
        """
        org = self._get_or_raise(org_id)

        old_status = org.status
        org.status = 'inactive'
        org.updated_at = datetime.utcnow()

        audit = OrganizationAuditLog(
            organization_id=org.id,
            field_name='status',
            old_value=str(old_status) if old_status is not None else None,
            new_value='inactive',
            changed_by=changed_by,
        )
        db.session.add(audit)
        db.session.commit()

        logger.info("Soft-deleted Organization id=%d by %s", org.id, changed_by)
        return org

    # ------------------------------------------------------------------
    # Property links
    # ------------------------------------------------------------------

    def link_property(self, org_id: int, property_id: int, role: str) -> PropertyOrganizationLink:
        """Create a link between an Organization and a property (Lead).

        Parameters
        ----------
        org_id : int
        property_id : int
            The ``leads.id`` of the property record.
        role : str
            Relationship role (e.g. 'owner', 'property_manager', 'broker').

        Returns
        -------
        PropertyOrganizationLink

        Raises
        ------
        ResourceNotFoundError
            If no Organization with *org_id* exists.
        """
        self._get_or_raise(org_id)

        link = PropertyOrganizationLink(
            organization_id=org_id,
            property_id=property_id,
            role=role,
        )
        db.session.add(link)
        db.session.commit()

        logger.info(
            "Linked property_id=%d to org_id=%d role=%r",
            property_id, org_id, role,
        )
        return link

    def unlink_property(self, link_id: int) -> None:
        """Delete a PropertyOrganizationLink by its primary key.

        Parameters
        ----------
        link_id : int

        Raises
        ------
        ResourceNotFoundError
            If no link with *link_id* exists.
        """
        link = PropertyOrganizationLink.query.get(link_id)
        if link is None:
            raise ResourceNotFoundError(
                f"PropertyOrganizationLink id={link_id} not found.",
                payload={'link_id': link_id},
            )
        db.session.delete(link)
        db.session.commit()
        logger.info("Unlinked PropertyOrganizationLink id=%d", link_id)

    # ------------------------------------------------------------------
    # Owner links
    # ------------------------------------------------------------------

    def link_owner(self, org_id: int, owner_id: int, role: str) -> OwnerOrganizationLink:
        """Create a link between an Organization and an owner (Lead).

        Parameters
        ----------
        org_id : int
        owner_id : int
            The ``leads.id`` of the owner record.
        role : str
            Relationship role (e.g. 'principal', 'member', 'attorney').

        Returns
        -------
        OwnerOrganizationLink

        Raises
        ------
        ResourceNotFoundError
            If no Organization with *org_id* exists.
        """
        self._get_or_raise(org_id)

        link = OwnerOrganizationLink(
            organization_id=org_id,
            owner_id=owner_id,
            role=role,
        )
        db.session.add(link)
        db.session.commit()

        logger.info(
            "Linked owner_id=%d to org_id=%d role=%r",
            owner_id, org_id, role,
        )
        return link

    def unlink_owner(self, link_id: int) -> None:
        """Delete an OwnerOrganizationLink by its primary key.

        Parameters
        ----------
        link_id : int

        Raises
        ------
        ResourceNotFoundError
            If no link with *link_id* exists.
        """
        link = OwnerOrganizationLink.query.get(link_id)
        if link is None:
            raise ResourceNotFoundError(
                f"OwnerOrganizationLink id={link_id} not found.",
                payload={'link_id': link_id},
            )
        db.session.delete(link)
        db.session.commit()
        logger.info("Unlinked OwnerOrganizationLink id=%d", link_id)

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def get_audit_log(self, org_id: int) -> list:
        """Return all audit log entries for an Organization, oldest first.

        Parameters
        ----------
        org_id : int

        Returns
        -------
        list[OrganizationAuditLog]

        Raises
        ------
        ResourceNotFoundError
            If no Organization with *org_id* exists.
        """
        self._get_or_raise(org_id)
        return (
            OrganizationAuditLog.query
            .filter_by(organization_id=org_id)
            .order_by(OrganizationAuditLog.changed_at.asc())
            .all()
        )

    # ------------------------------------------------------------------
    # List (paginated + filtered)
    # ------------------------------------------------------------------

    def list(
        self,
        page: int = 1,
        per_page: int = 20,
        filters: Optional[dict] = None,
    ) -> tuple:
        """Return a paginated list of Organizations with optional filters.

        Supported filter keys:
        - ``name`` (str): case-insensitive substring match
        - ``org_type`` (str): exact match against the org_type enum
        - ``status`` (str): exact match against the status enum

        Parameters
        ----------
        page : int
            1-based page number.
        per_page : int
            Number of records per page.
        filters : dict or None
            Optional filter criteria.

        Returns
        -------
        tuple[list[Organization], int]
            A 2-tuple of (records for this page, total matching count).
        """
        filters = filters or {}
        query = Organization.query

        if filters.get('name'):
            query = query.filter(
                Organization.name.ilike(f"%{filters['name']}%")
            )
        if filters.get('org_type'):
            query = query.filter(Organization.org_type == filters['org_type'])
        if filters.get('status'):
            query = query.filter(Organization.status == filters['status'])

        query = query.order_by(Organization.created_at.desc())

        total = query.count()
        records = query.offset((page - 1) * per_page).limit(per_page).all()

        return records, total

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, org_id: int) -> Organization:
        """Fetch an Organization by id or raise ResourceNotFoundError."""
        org = Organization.query.get(org_id)
        if org is None:
            raise ResourceNotFoundError(
                f"Organization id={org_id} not found.",
                payload={'org_id': org_id},
            )
        return org
