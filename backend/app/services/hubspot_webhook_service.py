"""HubSpotWebhookService — handles webhook signature verification, batch ingestion,
log querying, and retry dispatch for HubSpot webhook events."""
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timedelta

from app import db
from app.models import HubSpotWebhookLog, HubSpotConfig

logger = logging.getLogger(__name__)


class HubSpotWebhookService:
    """Service layer for HubSpot webhook processing.

    Responsibilities:
    - Verify HMAC-SHA256 signatures on incoming webhook requests
    - Parse and persist batches of webhook events as HubSpotWebhookLog records
    - Query 24-hour log summaries
    - Re-dispatch failed events to Celery
    """

    # ------------------------------------------------------------------ #
    # Signature verification                                               #
    # ------------------------------------------------------------------ #

    def verify_signature(
        self,
        raw_body: bytes,
        signature_header: str,
        timestamp_header: str,
        method: str = 'POST',
        uri: str = '/api/hubspot/webhook',
    ) -> bool:
        """Verify the HubSpot v3 HMAC-SHA256 webhook signature.

        Args:
            raw_body: The raw request body bytes (must be read before JSON parsing).
            signature_header: Value of the ``X-HubSpot-Signature-v3`` header.
            timestamp_header: Value of the ``X-HubSpot-Request-Timestamp`` header.
            method: HTTP method (default ``'POST'``).
            uri: Request URI (default ``'/api/hubspot/webhook'``).

        Returns:
            ``True`` if the signature is valid and the timestamp is fresh,
            ``False`` otherwise.
        """
        # Missing or empty headers → reject immediately
        if not signature_header or not timestamp_header:
            logger.warning(
                "Webhook signature verification failed: missing header(s) "
                "(signature_present=%s, timestamp_present=%s)",
                bool(signature_header),
                bool(timestamp_header),
            )
            return False

        # Reject stale timestamps (replay attack prevention).
        # HubSpot v3 sends the timestamp in milliseconds — divide by 1000 to
        # convert to seconds before comparing against time.time().
        try:
            ts_int = int(timestamp_header)
        except (ValueError, TypeError):
            logger.warning(
                "Webhook signature verification failed: unparseable timestamp header"
            )
            return False

        # Handle both millisecond (13-digit) and second (10-digit) timestamps
        ts_seconds = ts_int / 1000 if ts_int > 1e12 else ts_int

        if abs(time.time() - ts_seconds) > 300:
            logger.warning(
                "Webhook signature verification failed: timestamp is stale "
                "(age=%.1fs, limit=300s)",
                abs(time.time() - ts_seconds),
            )
            return False

        # Fetch and decrypt the client secret
        client_secret = self._get_client_secret()
        if not client_secret:
            logger.warning(
                "Webhook signature verification failed: client secret is not configured"
            )
            return False

        # Build the message: method + uri + body + timestamp
        # HubSpot v3: HMAC-SHA256(secret, method + uri + body + timestamp)
        try:
            body_str = raw_body.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning(
                "Webhook signature verification failed: request body is not valid UTF-8"
            )
            return False

        message = f"{method}{uri}{body_str}{timestamp_header}".encode('utf-8')
        # HubSpot v3 sends the signature as base64-encoded HMAC-SHA256
        import base64
        expected_bytes = hmac.new(
            client_secret.encode('utf-8'), message, hashlib.sha256
        ).digest()
        expected_b64 = base64.b64encode(expected_bytes).decode('utf-8')

        # Constant-time comparison to prevent timing attacks
        result = hmac.compare_digest(expected_b64, signature_header)
        if not result:
            logger.warning(
                "Webhook signature verification failed: HMAC mismatch "
                "(method=%s, uri=%s)",
                method,
                uri,
            )
        return result

    def _get_client_secret(self) -> str | None:
        """Decrypt and return the stored HubSpot client secret, or None."""
        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None or not config.encrypted_client_secret:
            return None

        try:
            from cryptography.fernet import Fernet, InvalidToken

            raw_key = os.environ.get('HUBSPOT_ENCRYPTION_KEY')
            if not raw_key:
                logger.error(
                    "HUBSPOT_ENCRYPTION_KEY environment variable is not set; "
                    "cannot decrypt client secret"
                )
                return None

            f = Fernet(raw_key.encode())
            return f.decrypt(config.encrypted_client_secret.encode()).decode()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to decrypt HubSpot client secret: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # Batch ingestion                                                      #
    # ------------------------------------------------------------------ #

    def handle_batch(self, events: list[dict]) -> list:
        """Parse a batch of HubSpot webhook events, persist them, and dispatch Celery tasks.

        For each event:
        1. Parse ``object_type`` from ``subscriptionType`` (e.g. ``deal.creation`` → ``deal``)
        2. Parse ``object_id`` from the ``objectId`` field
        3. Insert a ``HubSpotWebhookLog`` with ``status='pending'``

        All inserts are committed in a single transaction.  After the commit,
        ``process_webhook_event.delay(log.id)`` is dispatched for each log.

        If Celery is unavailable the logs are still returned — events are stored
        and will be processed when the worker comes back.

        Args:
            events: List of raw HubSpot event dicts from the webhook payload.

        Returns:
            List of created ``HubSpotWebhookLog`` instances.
        """
        logs = []

        for event in events:
            subscription_type = event.get('subscriptionType', '')
            # Parse object type: "deal.creation" → "deal"
            object_type = subscription_type.split('.')[0] if subscription_type else 'unknown'
            object_id = str(event.get('objectId', ''))
            event_type = subscription_type

            log = HubSpotWebhookLog(
                hubspot_object_type=object_type,
                hubspot_object_id=object_id,
                event_type=event_type,
                subscription_type=subscription_type,
                raw_payload=event,
                status='pending',
            )
            db.session.add(log)
            logs.append(log)

        try:
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to commit webhook log batch: %s", exc)
            db.session.rollback()
            raise

        # Dispatch Celery tasks after successful commit
        for log in logs:
            try:
                # Lazy import to avoid circular imports (tasks import services)
                from celery_worker import process_webhook_event
                process_webhook_event.delay(log.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to dispatch process_webhook_event for log_id=%s: %s",
                    log.id,
                    exc,
                )
                # Do not re-raise — events are stored; worker will pick them up

        return logs

    # ------------------------------------------------------------------ #
    # Log summary                                                          #
    # ------------------------------------------------------------------ #

    def get_log_summary(self) -> dict:
        """Return a 24-hour summary of webhook log statuses.

        Queries ``HubSpotWebhookLog`` records received in the last 24 hours
        and returns counts by status plus the most recent ``processed_at``
        timestamp.

        Returns:
            Dict matching ``WebhookLogSummarySchema``:
            ``{processed_count, failed_count, deduplicated_count, last_synced_at}``
        """
        cutoff = datetime.utcnow() - timedelta(hours=24)

        recent_logs = HubSpotWebhookLog.query.filter(
            HubSpotWebhookLog.received_at >= cutoff
        ).all()

        processed_count = sum(1 for log in recent_logs if log.status == 'processed')
        failed_count = sum(1 for log in recent_logs if log.status == 'failed')
        deduplicated_count = sum(1 for log in recent_logs if log.status == 'deduplicated')

        # Most recent processed_at across all logs (not just last 24h)
        last_processed = (
            HubSpotWebhookLog.query
            .filter(HubSpotWebhookLog.processed_at.isnot(None))
            .order_by(HubSpotWebhookLog.processed_at.desc())
            .first()
        )
        last_synced_at = last_processed.processed_at if last_processed else None

        return {
            'processed_count': processed_count,
            'failed_count': failed_count,
            'deduplicated_count': deduplicated_count,
            'last_synced_at': last_synced_at,
        }

    # ------------------------------------------------------------------ #
    # Retry                                                                #
    # ------------------------------------------------------------------ #

    def retry_failed_event(self, log_id: int) -> None:
        """Reset a failed webhook log entry and re-dispatch it to Celery.

        Args:
            log_id: Primary key of the ``HubSpotWebhookLog`` to retry.

        Raises:
            ValueError: If the log is not found or is not in ``'failed'`` status.
        """
        log = HubSpotWebhookLog.query.get(log_id)
        if log is None:
            raise ValueError(f"HubSpotWebhookLog with id={log_id} not found")

        if log.status != 'failed':
            raise ValueError(
                f"Cannot retry log id={log_id}: status is '{log.status}', expected 'failed'"
            )

        log.status = 'pending'
        log.error_message = None
        db.session.commit()

        # Lazy import to avoid circular imports
        from app.tasks.hubspot_webhook_tasks import process_webhook_event
        process_webhook_event.delay(log_id)
