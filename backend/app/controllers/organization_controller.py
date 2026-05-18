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

from app.api_utils import get_current_user_id
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
def create_organization():
    """Create a new organization.

    Request body
    ------------
    name : str (required, non-empty)
    org_type : str (optional, default 'unknown')
    status : str (optional, default 'unknown')
    notes : str (optional)
    source : str (optional)
    hubspot_company_id : str (optional)
    """
    data = request.json or {}
    changed_by = get_current_user_id()

    # Validate input via schema
    validated = _org_schema.load(data)

    org = _org_service.create(validated, changed_by=changed_by)

    return jsonify(_serialize_org(org)), 201


@organization_bp.route('/<int:org_id>', methods=['GET'])
@handle_errors
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
        raise ResourceNotFoundError(
            f"Organization id={org_id} not found.",
            payload={'org_id': org_id},
        )

    return jsonify(_serialize_org(org)), 200


@organization_bp.route('/<int:org_id>', methods=['PUT'])
@handle_errors
def update_organization(org_id):
    """Update an existing organization.

    Request body
    ------------
    Any subset of: name, org_type, status, notes, source, hubspot_company_id
    """
    data = request.json or {}
    changed_by = get_current_user_id()

    # Partial load — only validate fields that are present
    validated = _org_schema.load(data, partial=True)

    org = _org_service.update(org_id, validated, changed_by=changed_by)

    return jsonify(_serialize_org(org)), 200


@organization_bp.route('/<int:org_id>', methods=['DELETE'])
@handle_errors
def delete_organization(org_id):
    """Soft-delete an organization by setting its status to 'inactive'.

    Parameters
    ----------
    org_id : int
    """
    changed_by = get_current_user_id()
    org = _org_service.soft_delete(org_id, changed_by=changed_by)

    return jsonify({
        'message': f'Organization {org_id} has been deactivated.',
        'organization': _serialize_org(org),
    }), 200


@organization_bp.route('/<int:org_id>/audit-log', methods=['GET'])
@handle_errors
def get_organization_audit_log(org_id):
    """Get all audit log entries for an organization, oldest first.

    Parameters
    ----------
    org_id : int
    """
    entries = _org_service.get_audit_log(org_id)

    return jsonify({
        'audit_log': [_serialize_audit_entry(e) for e in entries],
        'total': len(entries),
    }), 200


@organization_bp.route('/<int:org_id>/links/properties', methods=['POST'])
@handle_errors
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

    link = _org_service.link_property(
        org_id=org_id,
        property_id=link_data['property_id'],
        role=link_data['role'],
    )

    return jsonify(_serialize_prop_link(link)), 201


@organization_bp.route('/<int:org_id>/links/properties/<int:link_id>', methods=['DELETE'])
@handle_errors
def unlink_property(org_id, link_id):
    """Remove a property link from an organization.

    Parameters
    ----------
    org_id : int
    link_id : int
    """
    _org_service.unlink_property(link_id)

    return jsonify({
        'message': f'Property link {link_id} removed from organization {org_id}.',
    }), 200


@organization_bp.route('/<int:org_id>/links/owners', methods=['POST'])
@handle_errors
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

    link = _org_service.link_owner(
        org_id=org_id,
        owner_id=link_data['owner_id'],
        role=link_data['role'],
    )

    return jsonify(_serialize_owner_link(link)), 201


@organization_bp.route('/<int:org_id>/links/owners/<int:link_id>', methods=['DELETE'])
@handle_errors
def unlink_owner(org_id, link_id):
    """Remove an owner link from an organization.

    Parameters
    ----------
    org_id : int
    link_id : int
    """
    _org_service.unlink_owner(link_id)

    return jsonify({
        'message': f'Owner link {link_id} removed from organization {org_id}.',
    }), 200
