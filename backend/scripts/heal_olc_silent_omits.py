"""Heal silent OLC omits for a mail campaign (dry-run or apply).

Uses MailCampaignService.heal_silent_omits (same path as analytics sync).
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-id', type=int, required=True)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist requeue / support escalations (default is dry-run)',
    )
    args = parser.parse_args(argv)

    from app import create_app
    from app.models import MailCampaign
    from app.services.mail_campaign_service import MailCampaignService, collapse_recipients_by_lead
    from app.services.open_letter_config_service import OpenLetterConfigService

    app = create_app()
    with app.app_context():
        campaign = MailCampaign.query.get(args.campaign_id)
        if campaign is None:
            print(f'Campaign {args.campaign_id} not found', file=sys.stderr)
            return 1
        if not campaign.olc_order_id:
            print(f'Campaign {args.campaign_id} has no OLC order', file=sys.stderr)
            return 1

        client = OpenLetterConfigService().get_client(campaign.created_by)
        recipients = []
        for row in client.iter_order_contacts(campaign.olc_order_id):
            recip = row.get('recipient') or row.get('contact') or row
            if isinstance(recip, dict):
                recipients.append(recip)
        tracked = set(collapse_recipients_by_lead(recipients).keys())

        svc = MailCampaignService()
        result = svc.heal_silent_omits(
            campaign.id,
            tracked,
            dry_run=not args.apply,
        )
        print(
            f'campaign={result.get("campaign_id")} tracked={result.get("tracked")} '
            f'omitted={result.get("omitted")} skipped={result.get("skipped")} '
            f'dry_run={result.get("dry_run")} touched={result.get("touched")}'
        )
        if result.get('reason'):
            print(f'  reason={result["reason"]}')
        for lid in (result.get('omitted_lead_ids') or [])[:25]:
            print(f'  omit lead_id={lid}')
        omitted_ids = result.get('omitted_lead_ids') or []
        if len(omitted_ids) > 25:
            print(f'  ... +{len(omitted_ids) - 25} more')
        if not args.apply:
            print('Dry-run only. Pass --apply to heal.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
