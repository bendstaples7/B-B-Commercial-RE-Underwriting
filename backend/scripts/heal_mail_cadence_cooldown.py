#!/usr/bin/env python3
"""Idempotent mail cadence heal for Deploy (dues + queue + rescore).

The Alembic revision ``mail_cad_20260905`` intentionally runs with
``rescore=False`` because it precedes scoring-weight calibration columns.
After ``flask db upgrade head``, call this so Ready-to-Mail cooldown leads
leave ``recommended_action == mail_ready``.

Usage (from backend/ on the VPS):
    FLASK_ENV=production python3.11 scripts/heal_mail_cadence_cooldown.py
"""
from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main() -> int:
    # scripts/ → backend/ (app package lives next to scripts/, not inside it)
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from app import create_app
    from app.services.mail_task_lifecycle_service import heal_mail_cadence_cooldown

    app = create_app(os.environ.get('FLASK_ENV', 'production'))
    with app.app_context():
        result = heal_mail_cadence_cooldown(commit=True, rescore=True)
    logger.info(
        'mail cadence heal: dues_fixed=%s rescored=%s removed_queue=%s affected=%s',
        result.get('rematch_dues_fixed'),
        result.get('rescored'),
        result.get('removed_queue_items'),
        len(result.get('affected_lead_ids') or []),
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
