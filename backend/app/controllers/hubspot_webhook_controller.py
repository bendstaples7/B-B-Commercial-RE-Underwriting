"""HubSpot Webhook Receiver endpoint.

Provides the unauthenticated POST /api/hubspot/webhook endpoint that receives
HubSpot webhook event batches.  Authentication is performed exclusively via
HMAC-SHA256 signature verification — no user session is required.

This blueprint is intentionally separate from ``hubspot_bp`` to keep the
unauthenticated webhook endpoint isolated from the authenticated import
endpoints.

URL prefix: /api/hubspot  (registered in app/__init__.py)
"""
import logging

from flask import Blueprint, jsonify, request

from app import limiter
from app.services import HubSpotWebhookService

logger = logging.getLogger(__name__)

hubspot_webhook_bp = Blueprint('hubspot_webhook', __name__)


@hubspot_webhook_bp.route('/webhook', methods=['POST'])
@limiter.limit("500 per minute")
def receive_webhook():
    """Receive a batch of HubSpot webhook events.

    Authentication
    --------------
    HMAC-SHA256 signature verification via ``X-HubSpot-Signature-v3`` and
    ``X-HubSpot-Request-Timestamp`` headers.  No user session is required.

    Returns
    -------
    200 ``{status: "accepted", count: N}`` — events accepted and queued.
    400 ``{error: "Content-Type must be application/json"}`` — wrong content type.
    401 ``{error: "Invalid signature"}`` — signature verification failed.
    """
    # 1. Read raw body BEFORE any JSON parsing — required for signature verification.
    #    Flask caches the body so subsequent get_json() calls still work.
    raw_body = request.get_data()

    # 2. Check Content-Type early so we can reject non-JSON before signature work.
    content_type = request.content_type or ''
    if 'application/json' not in content_type:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    # 3. Verify HMAC-SHA256 signature.
    sig = request.headers.get('X-HubSpot-Signature-v3')
    ts = request.headers.get('X-HubSpot-Request-Timestamp')

    # Build the full URI that HubSpot signed against — use forwarded headers
    # when behind a tunnel/proxy (dev tunnels, ngrok, etc.) so the URL matches
    # what HubSpot used to compute the signature.
    forwarded_host = request.headers.get('X-Forwarded-Host') or request.headers.get('X-Original-Host')
    forwarded_proto = request.headers.get('X-Forwarded-Proto', 'https')
    if forwarded_host:
        # Use full_path which includes query string (e.g. /api/hubspot/webhook?foo=bar)
        # Strip trailing '?' if query string is empty
        path_with_qs = request.full_path.rstrip('?')
        full_uri = f"{forwarded_proto}://{forwarded_host}{path_with_qs}"
    else:
        full_uri = request.url

    svc = HubSpotWebhookService()
    if not svc.verify_signature(
        raw_body,
        sig,
        ts,
        method='POST',
        uri=full_uri,
    ):
        logger.warning(
            "Webhook signature verification failed — IP=%s ts=%s",
            request.remote_addr,
            ts,
        )
        return jsonify({'error': 'Invalid signature'}), 401

    # 4. Parse the event batch.
    events = request.get_json(force=True) or []
    if not isinstance(events, list):
        events = [events]

    from app.services.hubspot_writeback_service import hubspot_pull_enabled
    if not hubspot_pull_enabled():
        logger.info(
            "HubSpot webhook accepted but not processed — HUBSPOT_PULL_ENABLED is false"
        )
        # Persist for audit; do not dispatch Celery.
        svc.handle_batch_skipped_disabled(events)
        return jsonify({
            'status': 'disabled',
            'reason': 'hubspot_pull_disabled',
            'count': len(events),
        }), 200

    # 5. Persist logs and dispatch Celery tasks.
    #    handle_batch() returns within milliseconds — actual processing is async.
    svc.handle_batch(events)

    return jsonify({'status': 'accepted', 'count': len(events)}), 200
