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
