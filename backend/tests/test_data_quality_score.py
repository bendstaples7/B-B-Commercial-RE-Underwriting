"""Tests for redesigned data completeness (property identity + contact reachability)."""
from types import SimpleNamespace

from app.services.scoring_rubric import (
    BEST_PHONE_MAX_POINTS,
    EMAIL_BASE_POINTS,
    PROPERTY_IDENTITY_MAX,
    calculate_data_quality_score,
)


def _lead(**kwargs):
    defaults = dict(
        id=None,
        county_assessor_pin=None,
        property_street=None,
        owner_first_name=None,
        owner_last_name=None,
        mailing_address=None,
        property_type=None,
        units=None,
        square_footage=None,
        source=None,
        data_source=None,
        property_city=None,
        property_zip=None,
        condo_risk_status=None,
        building_sale_possible=None,
        violation_data=None,
        permit_data=None,
        tax_distress_data=None,
        date_skip_traced=None,
        phone_1=None,
        phone_2=None,
        phone_3=None,
        phone_4=None,
        phone_5=None,
        phone_6=None,
        phone_7=None,
        email_1=None,
        email_2=None,
        email_3=None,
        email_4=None,
        email_5=None,
        most_recent_sale=None,
        purchase_date=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestDataQualityScore:
    def test_empty_lead_is_zero(self):
        score, missing, breakdown = calculate_data_quality_score(_lead())
        assert score == 0.0
        assert breakdown["property"] == 0.0
        assert breakdown["contact"] == 0.0
        assert "phone" in missing
        assert "email" in missing

    def test_full_property_identity_caps_at_fifty(self):
        lead = _lead(
            county_assessor_pin="12-34-567-890-0000",
            property_street="123 Main St",
            owner_first_name="Bob",
            owner_last_name="Weinstein",
            mailing_address="PO Box 1",
            property_type="multi_family",
            units=6,
            source="hubspot",
        )
        score, _, breakdown = calculate_data_quality_score(lead)
        assert breakdown["property"] == PROPERTY_IDENTITY_MAX
        assert breakdown["contact"] == 0.0
        assert score == PROPERTY_IDENTITY_MAX

    def test_flat_phone_at_default_confidence_counts(self):
        lead = _lead(phone_1="555-0100")
        score, missing, breakdown = calculate_data_quality_score(lead)
        # Default confidence 50 → 35 * 0.5 = 17.5
        assert breakdown["best_phone_confidence"] == 50
        assert breakdown["contact"] == 17.5
        assert score == 17.5
        assert "phone" not in missing

    def test_email_presence_adds_base_points(self):
        lead = _lead(email_1="bob@example.com")
        score, missing, breakdown = calculate_data_quality_score(lead)
        assert breakdown["has_email"] is True
        assert breakdown["contact"] == EMAIL_BASE_POINTS
        assert score == EMAIL_BASE_POINTS
        assert "email" not in missing

    def test_phone_and_email_combine_with_property(self):
        lead = _lead(
            county_assessor_pin="12-34-567-890-0000",
            property_street="123 Main St",
            owner_first_name="Bob",
            owner_last_name="Weinstein",
            mailing_address="PO Box 1",
            property_type="multi_family",
            units=6,
            source="hubspot",
            phone_1="555-0100",
            email_1="bob@example.com",
        )
        score, _, breakdown = calculate_data_quality_score(lead)
        assert breakdown["property"] == PROPERTY_IDENTITY_MAX
        assert breakdown["contact"] == 17.5 + EMAIL_BASE_POINTS
        assert score == PROPERTY_IDENTITY_MAX + 17.5 + EMAIL_BASE_POINTS

    def test_high_confidence_phone_scores_more_than_default(self, monkeypatch):
        lead = _lead(id=101)

        monkeypatch.setattr(
            "app.services.scoring_rubric._relational_phone_confidences",
            lambda _lead_id: [90],
        )
        monkeypatch.setattr(
            "app.services.scoring_rubric._email_reachability",
            lambda _lead: (0.0, False, False),
        )

        high_score, _, high_bd = calculate_data_quality_score(lead)
        assert high_bd["best_phone_confidence"] == 90
        assert high_score == BEST_PHONE_MAX_POINTS * 0.90

        monkeypatch.setattr(
            "app.services.scoring_rubric._relational_phone_confidences",
            lambda _lead_id: [50],
        )
        low_score, _, low_bd = calculate_data_quality_score(lead)
        assert low_bd["best_phone_confidence"] == 50
        assert high_score > low_score

    def test_contact_reachability_lookups_are_reused_for_missing_data(self, monkeypatch):
        calls = {"phone": 0, "email": 0}
        lead = _lead(id=202)

        def fake_relational_phone_confidences(_lead_id):
            calls["phone"] += 1
            return [90]

        def fake_email_reachability(_lead):
            calls["email"] += 1
            return EMAIL_BASE_POINTS, True, False

        monkeypatch.setattr(
            "app.services.scoring_rubric._relational_phone_confidences",
            fake_relational_phone_confidences,
        )
        monkeypatch.setattr(
            "app.services.scoring_rubric._email_reachability",
            fake_email_reachability,
        )

        _, missing, breakdown = calculate_data_quality_score(lead)

        assert breakdown["best_phone_confidence"] == 90
        assert breakdown["has_email"] is True
        assert "phone" not in missing
        assert "email" not in missing
        assert calls == {"phone": 1, "email": 1}
