"""Remove persisted typeface (font_name) from mail creative JSON.

Dry-run by default. Pass --apply to mutate.

Run from backend/:
    python scripts/scrub_mail_font_name.py
    python scripts/scrub_mail_font_name.py --apply
    python scripts/scrub_mail_font_name.py --apply --limit 100
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('scrub_mail_font_name')

BATCH_SIZE = 100


def _strip_font_name(payload: Any) -> tuple[Any, bool]:
    """Return (cleaned, changed) for a creative dict or preset list.

    Recurses into nested dict/list values so ``font_name`` at any depth is cleared.
    """
    if isinstance(payload, list):
        changed = False
        out = []
        for item in payload:
            cleaned, item_changed = _strip_font_name(item)
            out.append(cleaned)
            changed = changed or item_changed
        return out, changed
    if not isinstance(payload, dict):
        return payload, False
    out: dict[str, Any] = {}
    changed = False
    for key, value in payload.items():
        if key == 'font_name' and value is not None:
            out[key] = None
            changed = True
        else:
            cleaned, nested_changed = _strip_font_name(value)
            out[key] = cleaned
            changed = changed or nested_changed
    return out, changed


def scrub_font_names(*, apply: bool, limit: int | None = None) -> dict[str, Any]:
    from sqlalchemy.orm.attributes import flag_modified

    from app import create_app, db
    from app.models.mail_campaign import MailCampaign
    from app.models.open_letter_config import OpenLetterConfig

    app = create_app()
    campaigns_touched = 0
    presets_touched = 0
    with app.app_context():
        campaign_q = MailCampaign.query.order_by(MailCampaign.id)
        if limit is not None:
            campaign_q = campaign_q.limit(limit)
        pending = 0
        for campaign in campaign_q.yield_per(BATCH_SIZE):
            creative = campaign.creative
            cleaned, changed = _strip_font_name(creative)
            if not changed:
                continue
            campaigns_touched += 1
            logger.info(
                'campaign %s font_name %r -> None',
                campaign.id,
                (creative or {}).get('font_name') if isinstance(creative, dict) else None,
            )
            if apply:
                campaign.creative = cleaned
                flag_modified(campaign, 'creative')
                pending += 1
                if pending >= BATCH_SIZE:
                    db.session.commit()
                    pending = 0

        if apply and pending:
            db.session.commit()
            pending = 0

        config_q = OpenLetterConfig.query.order_by(OpenLetterConfig.id)
        if limit is not None:
            config_q = config_q.limit(limit)
        for config in config_q.yield_per(BATCH_SIZE):
            presets = config.creative_presets
            cleaned, changed = _strip_font_name(presets)
            if not changed:
                continue
            presets_touched += 1
            logger.info('open_letter_config %s creative_presets font_name cleared', config.id)
            if apply:
                config.creative_presets = cleaned
                flag_modified(config, 'creative_presets')
                pending += 1
                if pending >= BATCH_SIZE:
                    db.session.commit()
                    pending = 0

        if apply and pending:
            db.session.commit()

    return {
        'mode': 'apply' if apply else 'dry-run',
        'campaigns_touched': campaigns_touched,
        'configs_touched': presets_touched,
        'limit': limit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist scrub (default is dry-run)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Max campaigns and configs to scan (each)',
    )
    args = parser.parse_args()
    result = scrub_font_names(apply=args.apply, limit=args.limit)
    print(json.dumps(result, indent=2), flush=True)
    logger.info('%s complete', result['mode'].upper())


if __name__ == '__main__':
    main()
