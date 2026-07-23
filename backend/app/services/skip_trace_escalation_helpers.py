"""Safe helper to escalate invalid mail → skip-trace ladder."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def escalate_invalid_mail_safe(
    lead_id: int,
    *,
    actor: str,
    mail_queue_item_id: int | None = None,
    olc_order_id: str | None = None,
    validation_error: str | None = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    """Call SkipTraceEscalationService; never raise into mail writers."""
    try:
        from app.services.skip_trace_escalation_service import SkipTraceEscalationService

        return SkipTraceEscalationService().escalate_from_invalid_mail(
            lead_id,
            actor=actor,
            mail_queue_item_id=mail_queue_item_id,
            olc_order_id=olc_order_id,
            validation_error=validation_error,
            commit=commit,
        )
    except Exception:
        logger.exception(
            'skip-trace escalation failed for lead %s (mail continues)',
            lead_id,
        )
        return None
