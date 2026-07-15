"""Mail queue and campaign API endpoints."""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

from app.api_utils import require_auth
from app.controllers.mail_api_errors import handle_mail_api_errors as handle_errors
from app.controllers.request_parsing import parse_bool, parse_positive_int
from app.models import MailQueueItem
from app.services.mail_campaign_service import MailCampaignService
from app.services.mail_queue_service import (
    MAX_MAIL_ENQUEUE_LEADS,
    MailQueueService,
)
from app.services.scoring_rubric import format_last_sale_at

logger = logging.getLogger(__name__)

mail_queue_bp = Blueprint('mail_queue', __name__)

_queue_service = MailQueueService()
_campaign_service = MailCampaignService()


def _serialize_queue_item(item: MailQueueItem, *, last_mailed_at: str | None = None) -> dict:
    lead = item.lead
    owner = ''
    if lead:
        parts = [lead.owner_first_name or '', lead.owner_last_name or '']
        owner = ' '.join(p for p in parts if p).strip()

    return {
        'id': item.id,
        'lead_id': item.lead_id,
        'user_id': item.user_id,
        'status': item.status,
        'validation_error': item.validation_error,
        'campaign_id': item.campaign_id,
        'created_at': item.created_at.isoformat() if item.created_at else None,
        'owner_name': owner or None,
        'property_street': getattr(lead, 'property_street', None) if lead else None,
        'mailing_address': getattr(lead, 'mailing_address', None) if lead else None,
        'mailing_city': getattr(lead, 'mailing_city', None) if lead else None,
        'mailing_state': getattr(lead, 'mailing_state', None) if lead else None,
        'mailing_zip': getattr(lead, 'mailing_zip', None) if lead else None,
        'last_mailed_at': last_mailed_at,
        'last_sale_at': format_last_sale_at(lead) if lead else None,
    }


@mail_queue_bp.route('/', methods=['GET'])
@require_auth
@handle_errors
def get_queue():
    from app.services.last_mailed_service import format_last_mailed_at, get_last_mailed_at_by_lead_ids

    user_id = g.user_id
    summary = _queue_service.get_summary(user_id)
    items = _queue_service.list_queued(user_id)
    last_mailed = get_last_mailed_at_by_lead_ids([item.lead_id for item in items])
    return jsonify({
        **summary,
        'items': [
            _serialize_queue_item(
                item,
                last_mailed_at=format_last_mailed_at(last_mailed.get(item.lead_id)),
            )
            for item in items
        ],
    }), 200


@mail_queue_bp.route('/', methods=['POST'])
@require_auth
@handle_errors
def enqueue():
    data = request.get_json(silent=True) or {}
    lead_ids = data.get('lead_ids') or []
    if not isinstance(lead_ids, list):
        return jsonify({'error': 'lead_ids must be a list'}), 400
    try:
        parsed_ids = list(dict.fromkeys(int(x) for x in lead_ids))
    except (TypeError, ValueError):
        return jsonify({'error': 'lead_ids must contain integers'}), 400
    if len(parsed_ids) > MAX_MAIL_ENQUEUE_LEADS:
        return jsonify({
            'error': (
                f'No more than {MAX_MAIL_ENQUEUE_LEADS} leads '
                'may be queued at once'
            ),
        }), 400
    source_queue = data.get('source_queue')
    if source_queue is not None and not isinstance(source_queue, str):
        return jsonify({'error': 'source_queue must be a string'}), 400
    if isinstance(source_queue, str):
        source_queue = source_queue.strip() or None
        if source_queue and len(source_queue) > 100:
            return jsonify({'error': 'source_queue must be 100 characters or fewer'}), 400
    result = _queue_service.enqueue_leads(
        parsed_ids,
        g.user_id,
        source_queue=source_queue,
    )
    summary = _queue_service.get_summary(g.user_id)
    return jsonify({**result, **summary}), 201


@mail_queue_bp.route('/enqueue-candidates', methods=['POST'])
@require_auth
@handle_errors
def enqueue_candidates():
    data = request.get_json(silent=True) or {}
    limit = data.get('limit')
    if limit is not None:
        try:
            limit = parse_positive_int(limit, default=1, field_name='limit')
        except ValueError as exc:
            return jsonify({'error': 'Invalid request', 'message': str(exc)}), 400
    dry_run = parse_bool(data.get('dry_run'))
    result = _queue_service.enqueue_candidates(g.user_id, limit=limit, dry_run=dry_run)
    return jsonify(result), 200 if dry_run else 201


@mail_queue_bp.route('/attempts', methods=['GET'])
@require_auth
@handle_errors
def list_enqueue_attempts():
    try:
        limit = parse_positive_int(
            request.args.get('limit'),
            default=20,
            maximum=100,
            field_name='limit',
        )
    except ValueError as exc:
        return jsonify({'error': 'Invalid request', 'message': str(exc)}), 400
    return jsonify({'attempts': _queue_service.list_attempts(g.user_id, limit=limit)}), 200


@mail_queue_bp.route('/attempts/<int:attempt_id>', methods=['GET'])
@require_auth
@handle_errors
def get_enqueue_attempt(attempt_id: int):
    return jsonify(_queue_service.get_attempt(attempt_id, g.user_id)), 200


@mail_queue_bp.route('/<int:item_id>', methods=['DELETE'])
@require_auth
@handle_errors
def remove_item(item_id: int):
    _queue_service.remove_item(item_id, g.user_id)
    summary = _queue_service.get_summary(g.user_id)
    return jsonify(summary), 200


@mail_queue_bp.route('/send', methods=['POST'])
@require_auth
@handle_errors
def send_batch():
    data = request.get_json(silent=True) or {}
    force = parse_bool(data.get('force'))
    campaign = _campaign_service.create_and_dispatch_send(g.user_id, force=force)
    return jsonify(_campaign_service.serialize_campaign(campaign)), 202


@mail_queue_bp.route('/campaigns', methods=['GET'])
@require_auth
@handle_errors
def list_campaigns():
    try:
        page = parse_positive_int(request.args.get('page'), default=1, field_name='page')
        per_page = parse_positive_int(
            request.args.get('per_page'), default=25, maximum=100, field_name='per_page',
        )
    except ValueError as exc:
        return jsonify({'error': 'Invalid request', 'message': str(exc)}), 400
    campaigns, total = _campaign_service.list_campaigns(g.user_id, page=page, per_page=per_page)
    return jsonify({
        'campaigns': [_campaign_service.serialize_campaign(c) for c in campaigns],
        'total': total,
        'page': page,
        'per_page': per_page,
    }), 200


@mail_queue_bp.route('/campaigns/<int:campaign_id>', methods=['GET'])
@require_auth
@handle_errors
def get_campaign(campaign_id: int):
    user_id = g.user_id
    campaign = _campaign_service.get_campaign(campaign_id, user_id)
    if request.args.get('refresh') == 'true' and campaign.olc_order_id:
        try:
            campaign = _campaign_service.sync_campaign_analytics(campaign_id)
        except Exception as exc:
            logger.warning('Analytics refresh failed for campaign %s: %s', campaign_id, exc)
    return jsonify(_campaign_service.serialize_campaign(campaign)), 200


@mail_queue_bp.route('/campaigns/for-lead/<int:lead_id>', methods=['GET'])
@require_auth
@handle_errors
def campaigns_for_lead(lead_id: int):
    try:
        days = parse_positive_int(request.args.get('days'), default=90, field_name='days')
    except ValueError as exc:
        return jsonify({'error': 'Invalid request', 'message': str(exc)}), 400
    campaigns = _campaign_service.get_recent_for_lead(lead_id, g.user_id, days=days)
    return jsonify({
        'campaigns': [_campaign_service.serialize_campaign(c) for c in campaigns],
    }), 200
