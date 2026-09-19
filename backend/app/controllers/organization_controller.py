"""Organization management API endpoints.

Provides CRUD, soft-delete, audit log, and link management endpoints for
Organization records.  All routes are protected by the ``@handle_errors``
decorator for consistent JSON error responses.

URL prefix: /api/organizations  (registered in app/__init__.py)
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.api_utils import (
    current_user_is_admin,
    get_current_user_id,
    load_authorized_lead,
    owned_lead_ids_for_current_user,
    require_auth,
    user_can_access_association_target,
    user_can_access_lead,
)
from app.exceptions import (
    OrganizationValidationError,
    ResourceNotFoundError,
    RealEstateAnalysisException,
)
from app.schemas import (
    OrganizationSchema,
    OrganizationAuditLogSchema,
    PropertyOrganizationLinkSchema,
    OwnerOrganizationLinkSchema,
)
from app.models.organization_audit_log import OrganizationAuditLog
from app.services.organization_service import OrganizationService

logger = logging.getLogger(__name__)

organization_bp = Blueprint('organization', __name__)

_org_service = OrganizationService()
_org_schema = OrganizationSchema()
_audit_schema = OrganizationAuditLogSchema()
_prop_link_schema = PropertyOrganizationLinkSchema()
_owner_link_schema = OwnerOrganizationLinkSchema()

DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent JSON error handling on all organization routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
        except OrganizationValidationError as e:
            logger.warning("Organization validation error: %s", e.message)
            return jsonify({
                'error': 'Validation error',
                'message': e.message,
                **e.payload,
            }), e.status_code
        except ResourceNotFoundError as e:
            logger.warning("Resource not found: %s", e.message)
            return jsonify({
                'error': 'Not found',
                'message': e.message,
                **e.payload,
            }), e.status_code
        except RealEstateAnalysisException as e:
            logger.warning("Application error (%d): %s", e.status_code, e.message)
            return jsonify({
                'error': 'Application error',
                'message': e.message,
                **e.payload,
            }), e.status_code
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Invalid request',
                'message': str(e),
            }), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': getattr(e, 'name', 'HTTP error'),
                    'message': e.description,
                }), e.code
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_pagination(args):
    """Extract and validate pagination parameters from query string."""
    try:
        page = int(args.get('page', DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE
    try:
        per_page = int(args.get('per_page', DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE

    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _serialize_org(org):
    """Serialize an Organization using OrganizationSchema."""
    return _org_schema.dump(org)


def _org_not_found(org_id: int):
    raise ResourceNotFoundError(
        f"Organization id={org_id} not found.",
        payload={'org_id': org_id},
    )


def _org_created_by_current_user(org) -> bool:
    created = OrganizationAuditLog.query.filter_by(
        organization_id=org.id,
        field_name='__created__',
    ).order_by(OrganizationAuditLog.id.asc()).first()
    return bool(created and created.changed_by == get_current_user_id())


def _require_org_access(org) -> None:
    """404 when the org is not linked to a lead the caller can see."""
    if not user_can_access_association_target('organization', org.id):
        _org_not_found(org.id)


def _require_exclusive_org_access(org) -> None:
    """404 when any linked lead is outside the caller's scope.

    A company tied to someone else's property must not be renamed or
    deactivated from a property you also share.
    """
    if current_user_is_admin():
        return
    from app import db
    from app.models.lead import Lead
    from app.models.owner_organization_link import OwnerOrganizationLink
    from app.models.property_organization_link import PropertyOrganizationLink

    links = [
        link.property_id
        for link in PropertyOrganizationLink.query.filter_by(organization_id=org.id).all()
    ]
    links.extend(
        link.owner_id
        for link in OwnerOrganizationLink.query.filter_by(organization_id=org.id).all()
    )
    if not links:
        if _org_created_by_current_user(org):
            return
        _org_not_found(org.id)
    saw_owned = False
    for lead_id in links:
        lead = db.session.get(Lead, lead_id)
        if user_can_access_lead(lead):
            saw_owned = True
        elif lead is not None and getattr(lead, 'owner_user_id', None) is None:
            continue
        elif lead is not None:
            _org_not_found(org.id)
    if not saw_owned:
        _org_not_found(org.id)


def _load_authorized_org(org_id: int, *, allow_unlinked: bool = False):
    from app.models.organization import Organization
    from app import db

    org = db.session.get(Organization, org_id)
    if org is None:
        _org_not_found(org_id)
    if allow_unlinked:
        from app.api_utils import current_user_is_admin
        from app.models.owner_organization_link import OwnerOrganizationLink
        from app.models.property_organization_link import PropertyOrganizationLink
        if current_user_is_admin():
            return org
        property_link = PropertyOrganizationLink.query.filter_by(
            organization_id=org.id,
        ).first()
        owner_link = OwnerOrganizationLink.query.filter_by(
            organization_id=org.id,
        ).first()
        if property_link is None and owner_link is None:
            if not _org_created_by_current_user(org):
                _org_not_found(org.id)
            return org
    _require_org_access(org)
    return org


def _serialize_audit_entry(entry):
    """Serialize an OrganizationAuditLog entry."""
    return _audit_schema.dump(entry)


def _serialize_prop_link(link):
    """Serialize a PropertyOrganizationLink."""
    return _prop_link_schema.dump(link)


def _serialize_owner_link(link):
    """Serialize an OwnerOrganizationLink."""
    return _owner_link_schema.dump(link)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@organization_bp.route('/', methods=['GET'])
@handle_errors
@require_auth
def list_organizations():
    """List organizations with pagination and optional filters.

    Query parameters
    ----------------
    page : int (default 1)
    per_page : int (default 20, max 100)
    name : str — case-insensitive substring match on organization name
    org_type : str — exact match (llc/trust/corporation/brokerage/law_firm/property_management/unknown)
    status : str — exact match (active/inactive/unknown)
    """
    args = request.args
    page, per_page = _parse_pagination(args)

    filters = {}
    if args.get('name'):
        filters['name'] = args['name']
    if args.get('org_type'):
        filters['org_type'] = args['org_type']
    if args.get('status'):
        filters['status'] = args['status']

    scope = owned_lead_ids_for_current_user()
    if scope is not None:
        filters['linked_lead_ids'] = scope

    records, total = _org_service.list(page=page, per_page=per_page, filters=filters)

    return jsonify({
        'organizations': [_serialize_org(org) for org in records],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
    }), 200


@organization_bp.route('/', methods=['POST'])
@handle_errors
@require_auth
def create_organization():
    """Create a new organization.

    Request body
    ------------
    name : str (required, non-empty)
    org_type : str (optional, default 'unknown')
    status : str (optional, default 'unknown')
    notes : str (optional)
    source : str (optional)
    """
    data = request.json or {}
    changed_by = get_current_user_id()

    # Validate input via schema
    validated = _org_schema.load(data)

    org = _org_service.create(validated, changed_by=changed_by)

    return jsonify(_serialize_org(org)), 201


@organization_bp.route('/<int:org_id>', methods=['GET'])
@handle_errors
@require_auth
def get_organization(org_id):
    """Get a single organization by ID.

    Parameters
    ----------
    org_id : int
        Primary key of the organization.
    """
    # Use the service's internal helper via a list query with exact id
    # (service exposes _get_or_raise indirectly through other methods;
    # we query directly here for a clean GET)
    from app.models.organization import Organization
    from app import db

    org = db.session.get(Organization, org_id)
    if org is None:
        _org_not_found(org_id)
    _require_org_access(org)

    return jsonify(_serialize_org(org)), 200


@organization_bp.route('/<int:org_id>', methods=['PUT'])
@handle_errors
@require_auth
def update_organization(org_id):
    """Update an existing organization.

    Request body
    ------------
    Any subset of: name, org_type, status, notes, source
    """
    data = request.json or {}
    changed_by = get_current_user_id()
    org = _load_authorized_org(org_id, allow_unlinked=True)
    _require_exclusive_org_access(org)

    # Partial load — only validate fields that are present
    validated = _org_schema.load(data, partial=True)

    org = _org_service.update(org_id, validated, changed_by=changed_by)

    return jsonify(_serialize_org(org)), 200


@organization_bp.route('/<int:org_id>', methods=['DELETE'])
@handle_errors
@require_auth
def delete_organization(org_id):
    """Soft-delete an organization by setting its status to 'inactive'.

    Parameters
    ----------
    org_id : int
    """
    changed_by = get_current_user_id()
    org = _load_authorized_org(org_id, allow_unlinked=True)
    _require_exclusive_org_access(org)
    org = _org_service.soft_delete(org_id, changed_by=changed_by)

    return jsonify({
        'message': f'Organization {org_id} has been deactivated.',
        'organization': _serialize_org(org),
    }), 200


@organization_bp.route('/<int:org_id>/audit-log', methods=['GET'])
@handle_errors
@require_auth
def get_organization_audit_log(org_id):
    """Get all audit log entries for an organization, oldest first.

    Parameters
    ----------
    org_id : int
    """
    _load_authorized_org(org_id)
    entries = _org_service.get_audit_log(org_id)

    return jsonify({
        'audit_log': [_serialize_audit_entry(e) for e in entries],
        'total': len(entries),
    }), 200


@organization_bp.route('/<int:org_id>/links/properties', methods=['POST'])
@handle_errors
@require_auth
def link_property(org_id):
    """Link a property (Lead) to an organization.

    Request body
    ------------
    property_id : int (required)
    role : str (required, e.g. 'owner', 'property_manager', 'broker')
    """
    data = request.json or {}

    # Validate via schema (organization_id is server-set, not from body)
    link_data = _prop_link_schema.load({
        'property_id': data.get('property_id'),
        'organization_id': org_id,
        'role': data.get('role'),
    })

    _lead, err = load_authorized_lead(link_data['property_id'])
    if err is not None:
        return err
    _load_authorized_org(org_id, allow_unlinked=True)

    link = _org_service.link_property(
        org_id=org_id,
        property_id=link_data['property_id'],
        role=link_data['role'],
    )

    return jsonify(_serialize_prop_link(link)), 201


@organization_bp.route('/<int:org_id>/links/properties/<int:link_id>', methods=['DELETE'])
@handle_errors
@require_auth
def unlink_property(org_id, link_id):
    """Remove a property link from an organization.

    Parameters
    ----------
    org_id : int
    link_id : int
    """
    _load_authorized_org(org_id)
    from app.models.property_organization_link import PropertyOrganizationLink
    from app.models.lead import Lead
    from app import db
    link = PropertyOrganizationLink.query.filter_by(
        id=link_id, organization_id=org_id,
    ).first()
    if link is None:
        _org_not_found(org_id)
    lead = db.session.get(Lead, link.property_id)
    if not user_can_access_lead(lead):
        _org_not_found(org_id)
    _org_service.unlink_property(link_id, organization_id=org_id)

    return jsonify({
        'message': f'Property link {link_id} removed from organization {org_id}.',
    }), 200


@organization_bp.route('/<int:org_id>/links/owners', methods=['POST'])
@handle_errors
@require_auth
def link_owner(org_id):
    """Link an owner (Lead) to an organization.

    Request body
    ------------
    owner_id : int (required)
    role : str (required, e.g. 'principal', 'member', 'attorney', 'broker')
    """
    data = request.json or {}

    # Validate via schema
    link_data = _owner_link_schema.load({
        'owner_id': data.get('owner_id'),
        'organization_id': org_id,
        'role': data.get('role'),
    })

    _load_authorized_org(org_id, allow_unlinked=True)
    _lead, err = load_authorized_lead(link_data['owner_id'])
    if err is not None:
        return err

    link = _org_service.link_owner(
        org_id=org_id,
        owner_id=link_data['owner_id'],
        role=link_data['role'],
    )

    return jsonify(_serialize_owner_link(link)), 201


@organization_bp.route('/<int:org_id>/links/owners/<int:link_id>', methods=['DELETE'])
@handle_errors
@require_auth
def unlink_owner(org_id, link_id):
    """Remove an owner link from an organization.

    Parameters
    ----------
    org_id : int
    link_id : int
    """
    _load_authorized_org(org_id)
    from app.models.owner_organization_link import OwnerOrganizationLink
    from app.models.lead import Lead
    from app import db
    link = OwnerOrganizationLink.query.filter_by(
        id=link_id, organization_id=org_id,
    ).first()
    if link is None:
        _org_not_found(org_id)
    lead = db.session.get(Lead, link.owner_id)
    if not user_can_access_lead(lead):
        _org_not_found(org_id)
    _org_service.unlink_owner(link_id, organization_id=org_id)

    return jsonify({
        'message': f'Owner link {link_id} removed from organization {org_id}.',
    }), 200
