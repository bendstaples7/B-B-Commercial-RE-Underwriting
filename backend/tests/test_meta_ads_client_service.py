"""Unit tests for MetaAdsClientService helpers (no live Graph calls)."""
from app.services.meta_ads_client_service import MetaAdsClientService


def test_link_clicks_prefers_link_click_only():
    actions = [
        {'action_type': 'outbound_click', 'value': '10'},
        {'action_type': 'link_click', 'value': '3'},
    ]
    assert MetaAdsClientService._link_clicks_from_actions(actions) == 3


def test_link_clicks_zero_when_missing():
    assert MetaAdsClientService._link_clicks_from_actions(None) == 0
    assert MetaAdsClientService._link_clicks_from_actions([]) == 0


def test_insights_do_not_reintroduce_missing_campaigns(monkeypatch):
    """Campaigns only present in insights must not re-enter the sync set."""
    client = MetaAdsClientService('token', 'act_123')

    def fake_paginate(url, params):
        if 'insights' in url:
            return [
                {
                    'campaign_id': 'only_in_insights',
                    'spend': '9.99',
                    'impressions': '10',
                    'actions': [{'action_type': 'link_click', 'value': '2'}],
                }
            ]
        return [{'id': 'listed', 'name': 'Live', 'status': 'ACTIVE'}]

    monkeypatch.setattr(client, '_paginate', fake_paginate)
    rows = client.list_campaigns_with_insights()
    ids = {r['meta_campaign_id'] for r in rows}
    assert ids == {'listed'}
    assert 'only_in_insights' not in ids
