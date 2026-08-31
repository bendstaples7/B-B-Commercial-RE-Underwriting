"""Unit tests for Channel ROI projection math and service helpers."""
from decimal import Decimal

from app.services.channel_roi_service import (
    cost_per_response,
    projected_roi_multiplier,
    response_rate,
)


def test_projected_roi_multiplier_basic():
    # 2 responses × $10k profit × 10% close / $500 spend = 4.0×
    assert projected_roi_multiplier(
        responses=2,
        spend=Decimal('500'),
        expected_profit_per_deal=Decimal('10000'),
        assumed_close_rate=Decimal('0.1'),
    ) == 4.0


def test_projected_roi_none_when_knobs_or_spend_missing():
    assert projected_roi_multiplier(
        responses=1,
        spend=Decimal('100'),
        expected_profit_per_deal=None,
        assumed_close_rate=Decimal('0.1'),
    ) is None
    assert projected_roi_multiplier(
        responses=1,
        spend=Decimal('0'),
        expected_profit_per_deal=Decimal('1000'),
        assumed_close_rate=Decimal('0.1'),
    ) is None


def test_cost_per_response_and_rate():
    assert cost_per_response(Decimal('100'), 4) == 25.0
    assert cost_per_response(Decimal('100'), 0) is None
    assert response_rate(2, 100) == 0.02
    assert response_rate(2, 0) is None
    assert response_rate(2, None) is None
