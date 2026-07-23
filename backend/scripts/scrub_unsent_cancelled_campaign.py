"""Scrub false mail_sent artifacts for a cancelled campaign that never mailed.

Dry-run by default. Pass --apply to mutate.

Run from backend/:
    python scripts/scrub_unsent_cancelled_campaign.py --campaign-id 1
    python scripts/scrub_unsent_cancelled_campaign.py --campaign-id 1 --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('scrub_unsent_cancelled_campaign')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-id', type=int, required=True)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist scrub (default is dry-run)',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Allow scrub even when mailed/sent evidence exists',
    )
    args = parser.parse_args()

    from app import create_app
    from app.services.mail_campaign_scrub import scrub_unsent_cancelled_campaign

    app = create_app()
    with app.app_context():
        result = scrub_unsent_cancelled_campaign(
            args.campaign_id,
            apply=args.apply,
            force=args.force,
            actor='scrub_unsent_cancelled_campaign',
        )
    print(json.dumps(result, indent=2, default=str), flush=True)
    mode = 'APPLIED' if args.apply else 'DRY-RUN'
    logger.info('%s scrub for campaign %s complete', mode, args.campaign_id)


if __name__ == '__main__':
    main()
