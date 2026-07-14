"""Scrub HTML tags from HubSpot LeadTimelineEntry summaries and metadata body.

Run from backend/:
    python scripts/scrub_hubspot_timeline_html.py [--apply] [--lead-id N]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('scrub_hubspot_timeline_html')

from app import create_app
from app.models import LeadTimelineEntry
from app.services.helpers.html_text import strip_html_tags
from app.services.helpers.hubspot_call_disposition import looks_like_uuid
from app.services.hubspot_timeline_import_service import HubSpotTimelineImportService


def _needs_scrub(entry: LeadTimelineEntry) -> bool:
    """Match apply-path eligibility in scrub_html_from_hubspot_entries."""
    summary = entry.summary or ''
    if '<' in summary:
        return True
    meta = entry.event_metadata if isinstance(entry.event_metadata, dict) else {}
    body = meta.get('body')
    if isinstance(body, str) and '<' in body:
        return True
    # UUID rewrite only runs for hubspot_call entries (service guard)
    if entry.event_type == 'hubspot_call' and entry.hubspot_activity_id:
        if (
            looks_like_uuid(summary)
            or looks_like_uuid(body)
            or looks_like_uuid(meta.get('disposition'))
            or looks_like_uuid(meta.get('outcome'))
        ):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Persist updates')
    parser.add_argument('--lead-id', type=int, default=None)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        q = LeadTimelineEntry.query.filter_by(source='hubspot', is_deleted=False)
        if args.lead_id is not None:
            q = q.filter_by(lead_id=args.lead_id)
        # Stream candidates — avoid loading the full HubSpot timeline into memory
        need_count = 0
        sample_before = None
        sample_after = None
        for entry in q.yield_per(500):
            if not _needs_scrub(entry):
                continue
            need_count += 1
            if sample_before is None:
                sample_before = (entry.summary or '')[:100]
                sample_after = strip_html_tags(entry.summary or '')[:100]

        print(
            f'Found {need_count} HubSpot timeline entr(ies) with HTML or '
            f'rewritable call disposition UUID',
            flush=True,
        )
        if sample_before is not None:
            print(f'Sample before: {sample_before!r}', flush=True)
            print(f'Sample after:  {sample_after!r}', flush=True)

        if not args.apply:
            print(f'Done (dry-run): would_update={need_count}', flush=True)
            return

        svc = HubSpotTimelineImportService()
        updated = svc.scrub_html_from_hubspot_entries(lead_id=args.lead_id)
        print(f'Done (applied): updated={updated}', flush=True)


if __name__ == '__main__':
    main()
