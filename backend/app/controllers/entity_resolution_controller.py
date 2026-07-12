"""Entity resolution API — Illinois LLC → person Contact.

Routes (prefix ``/api/leads``):
  GET  /<id>/entity-resolution
  POST /<id>/entity-resolution
  POST /entity-resolution/bulk
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

from app.api_utils import require_auth
from app.controllers.decorators import handle_errors
from app.exceptions import ResourceNotFoundError
from app.services.entity_lookup import EntityLookupProviderNotConfiguredError
from app.services.entity_resolution_service import EntityResolutionService

logger = logging.getLogger(__name__)

entity_resolution_bp = Blueprint('entity_resolution', __name__)
_service = EntityResolutionService()


def _provider_error_response(exc: EntityLookupProviderNotConfiguredError):
    return jsonify({
        'error': 'Provider not configured',
        'message': str(exc),
    }), 503


def _not_found_response(exc: ResourceNotFoundError):
    return jsonify({
        'error': 'Not found',
        'message': exc.message,
        **(exc.payload or {}),
    }), getattr(exc, 'status_code', 404)


def _actor() -> str:
    return getattr(g, 'user_id', None) or 'entity_resolution'


def _json_bool(body: dict, key: str, *, default: bool) -> bool:
    value = body.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


@entity_resolution_bp.route('/<int:lead_id>/entity-resolution', methods=['GET'])
@require_auth
@handle_errors
def get_entity_resolution_status(lead_id: int):
    """Return entity-resolution status for a lead."""
    try:
        return jsonify(_service.get_status(lead_id)), 200
    except ResourceNotFoundError as exc:
        return _not_found_response(exc)


@entity_resolution_bp.route('/<int:lead_id>/entity-resolution', methods=['POST'])
@require_auth
@handle_errors
def resolve_entity(lead_id: int):
    """Resolve Illinois LLC primary contact → person Contact.

    Body (optional)::
        { "dry_run": false, "async": false }
    """
    body = request.get_json(silent=True) or {}
    dry_run = _json_bool(body, 'dry_run', default=False)
    use_async = _json_bool(body, 'async', default=False) and not dry_run

    if use_async:
        try:
            from celery_worker import entity_resolution_resolve_lead_task
            entity_resolution_resolve_lead_task.apply_async(
                args=[lead_id, _actor()], ignore_result=True,
            )
            return jsonify({
                'queued': True,
                'lead_id': lead_id,
                'message': 'Entity resolution queued',
            }), 202
        except Exception as exc:
            logger.warning(
                "Celery unavailable for entity resolution lead %s: %s — running sync",
                lead_id, exc,
            )

    try:
        result = _service.resolve_lead(lead_id, dry_run=dry_run, actor=_actor())
    except EntityLookupProviderNotConfiguredError as exc:
        return _provider_error_response(exc)
    except ResourceNotFoundError as exc:
        return _not_found_response(exc)

    return jsonify(result.to_dict()), 200


@entity_resolution_bp.route('/entity-resolution/bulk', methods=['POST'])
@require_auth
@handle_errors
def resolve_entity_bulk():
    """Queue or run entity resolution for many leads.

    Body::
        { "lead_ids": [1, 2], "dry_run": false, "async": true }
    """
    body = request.get_json(silent=True) or {}
    lead_ids = body.get('lead_ids') or []
    if not isinstance(lead_ids, list) or not lead_ids:
        raise ValueError('lead_ids must be a non-empty list')
    lead_ids = [int(x) for x in lead_ids]
    dry_run = _json_bool(body, 'dry_run', default=False)
    use_async = _json_bool(body, 'async', default=True) and not dry_run

    if use_async:
        queued = []
        try:
            from celery_worker import entity_resolution_resolve_lead_task
            for lid in lead_ids:
                entity_resolution_resolve_lead_task.apply_async(
                    args=[lid, _actor()], ignore_result=True,
                )
                queued.append(lid)
            return jsonify({
                'queued': True,
                'lead_ids': queued,
                'count': len(queued),
            }), 202
        except Exception as exc:
            # Only sync leads that were not already handed to Celery.
            remaining = [lid for lid in lead_ids if lid not in queued]
            logger.warning(
                "Celery unavailable for bulk entity resolution after %d queued: %s "
                "— syncing remaining %d",
                len(queued), exc, len(remaining),
            )
            lead_ids = remaining
            if not lead_ids:
                return jsonify({
                    'queued': True,
                    'lead_ids': queued,
                    'count': len(queued),
                    'message': 'Partial queue success; sync fallback had nothing left',
                }), 202

    results = []
    errors = []
    provider_error = None
    for lid in lead_ids:
        try:
            results.append(
                _service.resolve_lead(lid, dry_run=dry_run, actor=_actor()).to_dict()
            )
        except EntityLookupProviderNotConfiguredError as exc:
            provider_error = exc
            break
        except ResourceNotFoundError as exc:
            errors.append({
                'lead_id': lid,
                'error': 'Not found',
                'message': exc.message,
            })
        except Exception as exc:  # noqa: BLE001 — keep batch going
            logger.exception("Bulk entity resolution failed for lead %s", lid)
            errors.append({
                'lead_id': lid,
                'error': 'Resolution failed',
                'message': str(exc),
            })

    if provider_error is not None and not results and not errors:
        return _provider_error_response(provider_error)

    payload = {
        'queued': False,
        'results': results,
        'count': len(results),
        'errors': errors,
        'error_count': len(errors),
    }
    if provider_error is not None:
        payload['provider_error'] = str(provider_error)
    return jsonify(payload), 200
