"""Tests for contact quality, public-record distress, and outcome calibration."""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.enrichment_scoring import engagement_score
from app.services.motivation_signal_service import (
    ExtractedSignal,
    compute_public_record_distress_score,
    compute_soft_motivation_score,
    compute_total_motivation_score,
)
from app.services.outcome_calibration_service import (
    suggest_weights_from_lifts,
    _normalize_weights,
)
from app.services.scoring_rubric import (
    calculate_residential_score,
    contact_quality_modifier,
    contact_quality_score,
)


def _make_lead(**kwargs):
    lead = MagicMock()
    defaults = {
        "id": None,
        "property_type": "multi_family",
        "property_city": "Chicago",
        "property_zip": "60647",
        "units": 3,
        "mailing_address": "1 Main",
        "mailing_city": "Chicago",
        "mailing_state": "IL",
        "mailing_zip": "60647",
        "property_street": "2 Oak",
        "acquisition_date": date(2000, 1, 1),
        "notes": None,
        "manual_priority": None,
        "source_type": None,
        "tax_distress_data": None,
        "violation_data": None,
        "permit_data": None,
        "lead_category": "residential",
        "do_not_contact": False,
        "county_assessor_pin": "123",
        "owner_first_name": "Pat",
        "owner_last_name": "Owner",
        "source": "test",
        "data_source": None,
        "square_footage": 1800,
        "date_skip_traced": date(2024, 1, 15),
        "phone_1": None,
        "email_1": None,
        "phone_2": None,
        "phone_3": None,
        "phone_4": None,
        "phone_5": None,
        "phone_6": None,
        "phone_7": None,
        "email_2": None,
        "email_3": None,
        "email_4": None,
        "email_5": None,
        "socials": None,
        "year_built": 1975,
        "lot_size": 3000,
        "mailer_history": None,
        "has_phone": False,
        "has_email": False,
        "follow_up_date": None,
        "bedrooms": 3,
        "bathrooms": 2,
        "most_recent_sale": None,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(lead, k, v)
    return lead


class TestContactQuality:
    def test_untrusted_contacts_score_zero(self, monkeypatch):
        lead = _make_lead(
            acquisition_date=date.today() - timedelta(days=30),
            date_skip_traced=date.today() - timedelta(days=400),
            phone_1="555-0100",
        )
        assert contact_quality_score(lead) == 0.0
        assert contact_quality_modifier(lead) == -12.0

    def test_high_confidence_flat_phone_scores(self, monkeypatch):
        lead = _make_lead(phone_1="555-0199", has_phone=True)
        # Flat phones use DEFAULT_CONFIDENCE=50 → mid quality, no prior-owner.
        score = contact_quality_score(lead)
        assert score > 0
        assert score < 15
        assert contact_quality_modifier(lead) == 0.0

    def test_engagement_ignores_phone_email_flags(self):
        lead = _make_lead(has_phone=True, has_email=True)
        assert engagement_score(lead) == 0.0
        lead2 = _make_lead(mailer_history=[{"sent": True}], follow_up_date=date.today())
        assert engagement_score(lead2) == 10.0


class TestPublicRecordDistress:
    def test_distress_split_from_soft_motivation(self):
        lead = _make_lead(source_type="foreclosure")
        signals = [
            ExtractedSignal(
                signal_type="SOURCE_TYPE_DISTRESS",
                severity="medium",
                points=10.0,
                source="lead_field",
            ),
            ExtractedSignal(
                signal_type="NOTES_KEYWORD",
                severity="medium",
                points=10.0,
                source="notes",
            ),
            ExtractedSignal(
                signal_type="OWNER_SELLING_FSBO",
                severity="high",
                points=12.0,
                source="analyst",
            ),
        ]
        soft = compute_soft_motivation_score(lead, signals=signals)
        public = compute_public_record_distress_score(lead, signals=signals)
        total = compute_total_motivation_score(lead, signals=signals)
        assert public == 10.0
        assert soft == 15.0  # 10+12 capped at residential soft cap 15
        assert total == 25.0

    def test_residential_score_includes_public_record_dim(self):
        lead = _make_lead(source_type="tax_distress")
        result = calculate_residential_score(lead)
        details = result["score_details"]
        assert "public_record_distress" in details
        assert details["public_record_distress"] == 10.0
        assert details["structured_motivation"] == 0.0
        assert result["score_version"] == "unified_v2_residential"


class TestOutcomeCalibration:
    def test_suggest_weights_normalize_and_respect_floors(self):
        current = {
            "property_characteristics_weight": 0.25,
            "data_completeness_weight": 0.15,
            "owner_situation_weight": 0.30,
            "location_desirability_weight": 0.15,
            "data_enrichment_weight": 0.15,
        }
        lifts = {
            "property_characteristics": 5.0,
            "data_completeness": -10.0,
            "owner_situation": 20.0,
            "location_desirability": 0.0,
            "data_enrichment": -5.0,
        }
        suggested = suggest_weights_from_lifts(current, lifts, learning_rate=0.15)
        assert abs(sum(suggested.values()) - 1.0) < 0.011
        for val in suggested.values():
            assert 0.05 <= val <= 0.50
        # Owner situation should rise vs completeness
        assert (
            suggested["owner_situation_weight"]
            > suggested["data_completeness_weight"]
        )

    def test_normalize_weights_handles_zeros(self):
        out = _normalize_weights({
            "property_characteristics_weight": 0,
            "data_completeness_weight": 0,
            "owner_situation_weight": 0,
            "location_desirability_weight": 0,
            "data_enrichment_weight": 0,
        })
        assert abs(sum(out.values()) - 1.0) < 0.011
