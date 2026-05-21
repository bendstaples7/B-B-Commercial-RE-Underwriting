"""Contact management API endpoints.

Provides CRUD endpoints for Contacts and nested endpoints for managing
Property ↔ Contact associations.

Blueprint `contacts_bp` is registered at `url_prefix=''` so that all routes
carry their full `/api/...` paths (matching the pattern used by `timeline_bp`).

Routes:
  POST   /api/contacts/
  GET    /api/contacts/<id>
  PUT    /api/contacts/<id>
  DELETE /api/contacts/<id>
  GET    /api/properties/<id>/contacts
  POST   /api/properties/<id>/contacts
  DELETE /api/properties/<id>/contacts/<contact_id>
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.exceptions import (
    ConflictError,
    ResourceNotFoundError,
    ValidationException,
)
from app.services.contact_service import ContactService

logger = logging.getLogger(__name__)

contacts_bp = Blueprint('contacts', __name__)

contact_service = ContactService()


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent JSON error handling across contact routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ResourceNotFoundError as e:
            logger.warning("Not found: %s", e.message)
            return jsonify({
                'error': 'Not found',
                'message': e.message,
            }), 404
        except ConflictError as e:
            logger.warning("Conflict: %s", e.message)
            return jsonify({
                'error': 'Conflict',
                'message': e.message,
            }), 409
        except ValidationException as e:
            logger.warning("Validation error: %s", e.message)
            return jsonify({
                'error': 'Validation error',
                'message': e.message,
            }), 400
        except ValidationError as e:
            logger.warning("Schema validation error: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
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
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_contact(contact):
    """Serialize a Contact to a dictionary including phones and emails."""
    return {
        'id': contact.id,
        'first_name': contact.first_name,
        'last_name': contact.last_name,
        'role': contact.role,
        'role_description': contact.role_description,
        'notes': contact.notes,
        'phones': [
            {
                'id': p.id,
                'contact_id': p.contact_id,
                'value': p.value,
                'label': p.label,
            }
            for p in contact.phones
        ],
        'emails': [
            {
                'id': e.id,
                'contact_id': e.contact_id,
                'value': e.value,
                'label': e.label,
            }
            for e in contact.emails
        ],
        'created_at': contact.created_at.isoformat() if contact.created_at else None,
        'updated_at': contact.updated_at.isoformat() if contact.updated_at else None,
    }


def _serialize_property_contact(contact, pc):
    """Serialize a Contact with join record metadata (role and is_primary from PropertyContact)."""
    data = _serialize_contact(contact)
    data['property_contact_role'] = pc.role
    data['is_primary'] = pc.is_primary
    return data


# ---------------------------------------------------------------------------
# Contact CRUD routes  (/api/contacts/*)
# ---------------------------------------------------------------------------

@contacts_bp.route('/api/contacts/', methods=['POST'])
@handle_errors
def create_contact():
    """Create a new Contact with optional phones and emails.

    Request body
    ------------
    first_name : str (optional, but at least one of first_name/last_name required)
    last_name : str (optional, but at least one of first_name/last_name required)
    role : str (optional, default 'owner')
    role_description : str (optional)
    notes : str (optional)
    phones : list of {value, label} (optional)
    emails : list of {value, label} (optional)

    Returns 201 with serialized Contact on success.
    """
    data = request.get_json(silent=True) or {}
    contact = contact_service.create_contact(data)
    return jsonify(_serialize_contact(contact)), 201


@contacts_bp.route('/api/contacts/<int:contact_id>', methods=['GET'])
@handle_errors
def get_contact(contact_id):
    """Get a Contact by ID including phones, emails, and linked properties.

    Returns 404 if the Contact does not exist.
    """
    from app.models.contact import Contact
    from app import db

    contact = db.session.get(Contact, contact_id)
    if contact is None:
        raise ResourceNotFoundError(
            f"Contact id={contact_id} not found.",
            payload={'contact_id': contact_id},
        )

    data = _serialize_contact(contact)

    # Include linked properties via property_contacts
    linked_properties = []
    for pc in contact.property_contacts.all():
        linked_properties.append({
            'property_id': pc.property_id,
            'role': pc.role,
            'is_primary': pc.is_primary,
        })
    data['linked_properties'] = linked_properties

    return jsonify(data), 200


@contacts_bp.route('/api/contacts/<int:contact_id>', methods=['PUT'])
@handle_errors
def update_contact(contact_id):
    """Update an existing Contact.

    Phones and emails are replaced atomically if provided.
    Returns 404 if the Contact does not exist.
    """
    data = request.get_json(silent=True) or {}
    contact = contact_service.update_contact(contact_id, data)
    return jsonify(_serialize_contact(contact)), 200


@contacts_bp.route('/api/contacts/<int:contact_id>', methods=['DELETE'])
@handle_errors
def delete_contact(contact_id):
    """Delete a Contact and cascade to phones, emails, and property_contacts.

    Returns 204 on success, 404 if the Contact does not exist.
    """
    contact_service.delete_contact(contact_id)
    return '', 204


# ---------------------------------------------------------------------------
# Property-Contact nested routes  (/api/properties/<id>/contacts)
# ---------------------------------------------------------------------------

@contacts_bp.route('/api/properties/<int:property_id>/contacts', methods=['GET'])
@handle_errors
def get_property_contacts(property_id):
    """List all Contacts linked to a Property, including join record metadata.

    Returns a list of contact objects each augmented with
    `property_contact_role` and `is_primary` from the join record.
    Returns 404 if the Property does not exist.
    """
    rows = contact_service.get_contacts_for_property(property_id)
    result = [_serialize_property_contact(contact, pc) for contact, pc in rows]
    return jsonify(result), 200


@contacts_bp.route('/api/properties/<int:property_id>/contacts', methods=['POST'])
@handle_errors
def link_contact_to_property(property_id):
    """Link an existing Contact to a Property.

    Request body
    ------------
    contact_id : int (required)
    role : str (required)
    is_primary : bool (required)

    Returns 201 on success.
    Returns 404 if the Property or Contact does not exist.
    Returns 409 if the link already exists.
    """
    data = request.get_json(silent=True) or {}

    contact_id = data.get('contact_id')
    role = data.get('role')
    is_primary = data.get('is_primary')

    if contact_id is None:
        return jsonify({'error': 'Validation error', 'message': 'contact_id is required'}), 400
    if role is None:
        return jsonify({'error': 'Validation error', 'message': 'role is required'}), 400
    if is_primary is None:
        return jsonify({'error': 'Validation error', 'message': 'is_primary is required'}), 400

    try:
        contact_id = int(contact_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Validation error', 'message': 'contact_id must be an integer'}), 400

    pc = contact_service.link_contact_to_property(
        property_id=property_id,
        contact_id=contact_id,
        role=role,
        is_primary=bool(is_primary),
    )

    from app.models.contact import Contact
    from app import db
    contact = db.session.get(Contact, contact_id)

    return jsonify(_serialize_property_contact(contact, pc)), 201


@contacts_bp.route('/api/properties/<int:property_id>/contacts/<int:contact_id>', methods=['DELETE'])
@handle_errors
def unlink_contact_from_property(property_id, contact_id):
    """Unlink a Contact from a Property without deleting the Contact.

    Returns 204 on success.
    Returns 404 if the link does not exist.
    """
    contact_service.unlink_contact_from_property(property_id, contact_id)
    return '', 204
