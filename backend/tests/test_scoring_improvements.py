"""Tests for contact quality, public-record distress, and outcome calibration."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.enrichment_scoring import engagement_score
from app.services.motivation_signal_service import (
    ExtractedSignal,
    compute_public_record_distress_score,
    compute_soft_motivation_score,
    compute_total_motivation_score,
)
from app.services.outcome_calibration_service import (
    CalibrationReport,
    calibrate_scoring_weights,
    suggest_weights_from_lifts,
    _normalize_weights,
    collect_outcome_bucket_samples,
    run_scheduled_calibration,
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

    def test_contact_quality_uses_batch_reachability(self):
        lead = _make_lead()
        reachability = (42.0, {
            "best_phone_confidence": 95,
            "has_email": True,
            "email_owner_or_primary": True,
        })
        with patch(
            "app.services.scoring_rubric._best_phone_confidence",
            side_effect=AssertionError("per-lead phone lookup should not run"),
        ), patch(
            "app.services.scoring_rubric._email_reachability",
            side_effect=AssertionError("per-lead email lookup should not run"),
        ):
            assert contact_quality_score(
                lead,
                contact_reachability=reachability,
            ) > 0
            assert contact_quality_modifier(
                lead,
                contact_reachability=reachability,
            ) == 5.0

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

    def test_normalize_weights_respects_bounds_after_projection(self):
        out = _normalize_weights({
            "property_characteristics_weight": 10.0,
            "data_completeness_weight": 0.01,
            "owner_situation_weight": 0.01,
            "location_desirability_weight": 0.01,
            "data_enrichment_weight": 0.01,
        })
        assert abs(sum(out.values()) - 1.0) < 0.011
        assert all(0.05 <= val <= 0.50 for val in out.values())

    def test_pre_outcome_uses_score_before_transition(self, app):
        from app.models.lead import Property
        from app.models.lead_score import LeadScore
        from app.models.lead_timeline_entry import LeadTimelineEntry
        from app import db

        with app.app_context():
            lead = Property(
                property_street="100 Calibration Ave",
                property_city="Chicago",
                property_state="IL",
                property_zip="60647",
                lead_category="residential",
                lead_status="deal_won",
                owner_user_id="test-user",
            )
            db.session.add(lead)
            db.session.flush()

            early = datetime.utcnow() - timedelta(days=10)
            transition_at = datetime.utcnow() - timedelta(days=5)
            late = datetime.utcnow() - timedelta(days=1)

            early_details = {
                "bucket_property_characteristics": 40.0,
                "bucket_data_completeness": 50.0,
                "bucket_owner_situation": 60.0,
                "bucket_location_desirability": 30.0,
                "bucket_data_enrichment": 20.0,
            }
            late_details = {
                "bucket_property_characteristics": 90.0,
                "bucket_data_completeness": 90.0,
                "bucket_owner_situation": 90.0,
                "bucket_location_desirability": 90.0,
                "bucket_data_enrichment": 90.0,
            }
            db.session.add(LeadScore(
                lead_id=lead.id,
                score_version="unified_v2_residential",
                total_score=45.0,
                score_tier="C",
                data_quality_score=50.0,
                recommended_action="nurture",
                top_signals=[],
                score_details=early_details,
                missing_data=[],
                created_at=early,
            ))
            db.session.add(LeadScore(
                lead_id=lead.id,
                score_version="unified_v2_residential",
                total_score=90.0,
                score_tier="A",
                data_quality_score=90.0,
                recommended_action="call_ready",
                top_signals=[],
                score_details=late_details,
                missing_data=[],
                created_at=late,
            ))
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type="status_changed",
                occurred_at=transition_at.replace(tzinfo=timezone.utc)
                if transition_at.tzinfo is None
                else transition_at,
                source="system",
                actor="test",
                summary="won",
                event_metadata={
                    "previous_status": "mailing_no_contact_made",
                    "new_status": "deal_won",
                },
            ))
            db.session.commit()

            positive, negative, strata = collect_outcome_bucket_samples(
                lookback_days=30,
                sample_mode="pre_outcome",
                user_id="test-user",
            )
            assert len(negative) == 0
            assert any(
                abs(row["owner_situation"] - 60.0) < 0.01 for row in positive
            ), f"expected pre-outcome buckets, got {positive}"
            assert strata.get("residential", {}).get("positive", 0) >= 1

    def test_pre_outcome_ignores_deleted_transitions(self, app):
        from app.models.lead import Property
        from app.models.lead_score import LeadScore
        from app.models.lead_timeline_entry import LeadTimelineEntry
        from app import db

        with app.app_context():
            lead = Property(
                property_street="101 Deleted Calibration Ave",
                property_city="Chicago",
                property_state="IL",
                property_zip="60647",
                lead_category="residential",
                lead_status="deal_won",
                owner_user_id="test-user",
            )
            db.session.add(lead)
            db.session.flush()

            transition_at = datetime.utcnow() - timedelta(days=5)
            db.session.add(LeadScore(
                lead_id=lead.id,
                score_version="unified_v2_residential",
                total_score=77.0,
                score_tier="B",
                data_quality_score=77.0,
                recommended_action="nurture",
                top_signals=[],
                score_details={
                    "bucket_property_characteristics": 77.0,
                    "bucket_data_completeness": 77.0,
                    "bucket_owner_situation": 77.0,
                    "bucket_location_desirability": 77.0,
                    "bucket_data_enrichment": 77.0,
                },
                missing_data=[],
                created_at=transition_at - timedelta(days=1),
            ))
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type="status_changed",
                occurred_at=transition_at,
                source="system",
                actor="test",
                summary="deleted win",
                event_metadata={
                    "previous_status": "mailing_no_contact_made",
                    "new_status": "deal_won",
                },
                is_deleted=True,
            ))
            db.session.commit()

            positive, negative, strata = collect_outcome_bucket_samples(
                lookback_days=30,
                sample_mode="pre_outcome",
                user_id="test-user",
            )

            assert positive == []
            assert negative == []
            assert strata == {}

    def test_samples_are_scoped_to_weight_owner(self, app):
        from app.models.lead import Property
        from app.models.lead_score import LeadScore
        from app.models.lead_timeline_entry import LeadTimelineEntry
        from app import db

        with app.app_context():
            transition_at = datetime.utcnow() - timedelta(days=3)
            for owner_id, bucket_value in (("owner-a", 61.0), ("owner-b", 92.0)):
                lead = Property(
                    property_street=f"{owner_id} Calibration Ave",
                    property_city="Chicago",
                    property_state="IL",
                    property_zip="60647",
                    lead_category="residential",
                    lead_status="deal_won",
                    owner_user_id=owner_id,
                )
                db.session.add(lead)
                db.session.flush()
                db.session.add(LeadScore(
                    lead_id=lead.id,
                    score_version="unified_v2_residential",
                    total_score=bucket_value,
                    score_tier="B",
                    data_quality_score=bucket_value,
                    recommended_action="nurture",
                    top_signals=[],
                    score_details={
                        "bucket_property_characteristics": bucket_value,
                        "bucket_data_completeness": bucket_value,
                        "bucket_owner_situation": bucket_value,
                        "bucket_location_desirability": bucket_value,
                        "bucket_data_enrichment": bucket_value,
                    },
                    missing_data=[],
                    created_at=transition_at - timedelta(days=1),
                ))
                db.session.add(LeadTimelineEntry(
                    lead_id=lead.id,
                    event_type="status_changed",
                    occurred_at=transition_at,
                    source="system",
                    actor="test",
                    summary="won",
                    event_metadata={
                        "previous_status": "mailing_no_contact_made",
                        "new_status": "deal_won",
                    },
                ))
            db.session.commit()

            positive, _negative, _strata = collect_outcome_bucket_samples(
                lookback_days=30,
                sample_mode="pre_outcome",
                user_id="owner-a",
            )

            assert any(abs(row["owner_situation"] - 61.0) < 0.01 for row in positive)
            assert all(abs(row["owner_situation"] - 92.0) > 0.01 for row in positive)

    def test_scheduled_apply_calibrates_each_lead_owner(self, app, monkeypatch):
        from app.models.lead import Property
        from app import db

        with app.app_context():
            for owner_id in (None, "owner-a", "owner-b"):
                db.session.add(Property(
                    property_street=f"{owner_id or 'default'} Scheduled Cal Ave",
                    property_city="Chicago",
                    property_state="IL",
                    property_zip="60647",
                    lead_category="residential",
                    owner_user_id=owner_id,
                ))
            db.session.commit()

            seen: list[str] = []

            def _fake_calibrate(user_id, **_kwargs):
                seen.append(user_id)
                return CalibrationReport(
                    positive_count=1,
                    negative_count=1,
                    applied=True,
                    leads_rescored=1,
                )

            monkeypatch.setenv("SCORING_CALIBRATION_APPLY", "1")
            with patch(
                "app.services.outcome_calibration_service.calibrate_scoring_weights",
                side_effect=_fake_calibrate,
            ):
                report = run_scheduled_calibration()

            assert seen == ["default", "owner-a", "owner-b"]
            assert report.applied is True
            assert report.leads_rescored == 3

    def test_scheduled_dry_run_calibrates_each_lead_owner(self, app, monkeypatch):
        from app.models.lead import Property
        from app import db

        with app.app_context():
            for owner_id in (None, "owner-a", "owner-b"):
                db.session.add(Property(
                    property_street=f"{owner_id or 'default'} Scheduled Dry Cal Ave",
                    property_city="Chicago",
                    property_state="IL",
                    property_zip="60647",
                    lead_category="residential",
                    owner_user_id=owner_id,
                ))
            db.session.commit()

            seen: list[tuple[str, bool, bool]] = []

            def _fake_calibrate(user_id, **kwargs):
                seen.append((user_id, kwargs["apply"], kwargs["rescore"]))
                return CalibrationReport(
                    positive_count=1,
                    negative_count=1,
                    applied=False,
                    leads_rescored=0,
                )

            monkeypatch.delenv("SCORING_CALIBRATION_APPLY", raising=False)
            with patch(
                "app.services.outcome_calibration_service.calibrate_scoring_weights",
                side_effect=_fake_calibrate,
            ):
                report = run_scheduled_calibration()

            assert seen == [
                ("default", False, False),
                ("owner-a", False, False),
                ("owner-b", False, False),
            ]
            assert report.applied is False
            assert report.skipped_reason is None

    def test_calibration_dry_run_does_not_create_weight_row(self, app):
        from app.models.lead_scoring import ScoringWeights
        from app import db

        with app.app_context():
            report = calibrate_scoring_weights("dry-run-only", apply=False)

            assert report.applied is False
            assert db.session.query(ScoringWeights).filter_by(
                user_id="dry-run-only",
            ).first() is None


class TestDistressCoverageHelpers:
    def test_lead_needs_distress_when_pin_and_no_attempt(self, app):
        from app.models.lead import Property
        from app import db
        from app.services.cook_county_enrichment_service import lead_needs_distress_enrichment

        with app.app_context():
            lead = Property(
                property_street="200 Distress St",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                county_assessor_pin="01-02-003-004-0000",
                tax_distress_data=None,
                lead_category="residential",
                owner_user_id="test-user",
            )
            db.session.add(lead)
            db.session.commit()
            assert lead_needs_distress_enrichment(lead) is True

    def test_lead_does_not_need_distress_when_json_present(self, app):
        from app.models.lead import Property
        from app import db
        from app.services.cook_county_enrichment_service import lead_needs_distress_enrichment

        with app.app_context():
            lead = Property(
                property_street="201 Distress St",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                county_assessor_pin="01-02-003-004-0001",
                tax_distress_data={"annual_tax_sale": []},
                lead_category="residential",
                owner_user_id="test-user",
            )
            db.session.add(lead)
            db.session.commit()
            assert lead_needs_distress_enrichment(lead) is False
