"""Tests for MotivationSignalService and structured motivation scoring."""
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.lead import Property
from app.models.motivation_signal import MotivationSignal
from app.services.lead_scoring_engine import DEFAULT_WEIGHTS, LeadScoringEngine
from app.services.motivation_signal_service import (
    MotivationSignalService,
    extract_signals_from_lead,
    structured_motivation_score,
)
from app.services.scoring_rubric import (
    bucket_scores,
    calculate_commercial_score,
    calculate_residential_score,
    extract_top_signals,
)


def _default_mock_weights():
    weights = MagicMock()
    for key, value in DEFAULT_WEIGHTS.items():
        setattr(weights, key, value)
    return weights


def _base_lead_kwargs():
    return dict(
        property_street="123 N Michigan Ave",
        property_city="Chicago",
        property_state="IL",
        property_zip="60601",
        county_assessor_pin="01-02-202-045-0000",
        lead_category="residential",
        source_type="absentee_owner",
        owner_user_id="test-user",
    )


def _scavenger_tax_distress():
    return {
        "scavenger_tax_sale": [{"pin": "01-02-202-045-0000", "year": "2024"}],
    }


def _distress_payload():
    return (
        _scavenger_tax_distress(),
        {
            "chicago_scofflaw": [{"pin": "01-02-202-045-0000"}],
            "chicago_building_violations": [{"violation_code": "CN101"}],
        },
    )


class TestMotivationSignalExtraction:
    def test_scavenger_tax_sale_signal(self):
        lead = Property(**_base_lead_kwargs(), tax_distress_data=_scavenger_tax_distress())
        signals = extract_signals_from_lead(lead)
        types = {s.signal_type for s in signals}
        assert "TAX_SCAVENGER_SALE" in types

    def test_sync_idempotent_on_reenrichment(self, app):
        with app.app_context():
            lead = Property(**_base_lead_kwargs(), tax_distress_data=_scavenger_tax_distress())
            db.session.add(lead)
            db.session.commit()

            svc = MotivationSignalService()
            svc.sync_from_lead(lead)
            first_count = MotivationSignal.query.filter_by(
                lead_id=lead.id, is_active=True
            ).count()

            lead.tax_distress_data = None
            db.session.add(lead)
            db.session.commit()
            svc.sync_from_lead(lead)
            deactivated = MotivationSignal.query.filter_by(
                lead_id=lead.id, is_active=False
            ).count()
            active = MotivationSignal.query.filter_by(
                lead_id=lead.id, is_active=True
            ).count()

            assert first_count >= 1
            assert deactivated >= 1
            assert active == 0


class TestStructuredMotivationScoring:
    def test_scavenger_raises_score_by_at_least_15_points(self, app):
        with app.app_context():
            baseline = Property(**_base_lead_kwargs())
            tax_data, violation_data = _distress_payload()
            distressed = Property(
                **_base_lead_kwargs(),
                tax_distress_data=tax_data,
                violation_data=violation_data,
            )
            db.session.add_all([baseline, distressed])
            db.session.commit()

            MotivationSignalService().sync_from_lead(baseline)
            MotivationSignalService().sync_from_lead(distressed)

            engine = LeadScoringEngine()
            weights = _default_mock_weights()
            with patch.object(LeadScoringEngine, '_score_engagement', return_value=0.0), \
                 patch('app.services.lead_scoring_engine._count_open_tasks', return_value=0), \
                 patch('app.services.lead_scoring_engine._has_overdue_lead_task', return_value=False), \
                 patch('app.services.lead_scoring_engine._resolve_crm_flags', return_value=(False, False, False)):
                base_result = engine.compute(baseline, weights)
                distressed_result = engine.compute(distressed, weights)

            delta = distressed_result.total_score - base_result.total_score
            structured_delta = (
                distressed_result.score_details.get("structured_motivation", 0)
                - base_result.score_details.get("structured_motivation", 0)
            )
            assert structured_delta >= 15.0, f"Expected >=15 structured motivation delta, got {structured_delta}"
            assert delta > 0, f"Expected positive lead_score delta, got {delta}"

    def test_commercial_bucket_includes_structured_motivation(self, app):
        with app.app_context():
            lead = Property(
                property_street="123 N Michigan Ave",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                county_assessor_pin="01-02-202-045-0000",
                lead_category="commercial",
                property_type="commercial",
                source_type="absentee_owner",
                owner_user_id="test-user",
                tax_distress_data=_scavenger_tax_distress(),
            )
            db.session.add(lead)
            db.session.commit()
            MotivationSignalService().sync_from_lead(lead)

            details = calculate_commercial_score(lead)["score_details"]
            assert "structured_motivation" in details
            assert details["structured_motivation"] > 0

            buckets = bucket_scores(details, 80.0, "commercial")
            assert buckets["owner_situation"] > 0

    def test_extract_top_signals_shows_structured_label(self, app):
        with app.app_context():
            lead = Property(
                **_base_lead_kwargs(),
                tax_distress_data=_scavenger_tax_distress(),
            )
            db.session.add(lead)
            db.session.commit()
            MotivationSignalService().sync_from_lead(lead)

            signals = extract_top_signals(
                calculate_residential_score(lead)["score_details"],
                lead=lead,
            )
            labels = " ".join(item["dimension"] for item in signals)
            assert "Scavenger tax sale" in labels or "structured_motivation" in labels


class TestStructuredMotivationCaps:
    def test_residential_cap_at_25(self):
        lead = Property(**_base_lead_kwargs())
        lead.tax_distress_data = {
            "scavenger_tax_sale": [{}],
            "annual_tax_sale": [{}],
        }
        lead.violation_data = {
            "chicago_building_violations": [{"violation_code": "CN101"}],
            "chicago_scofflaw": [{}],
        }
        lead.notes = "probate vacant tired landlord foreclosure"
        lead.manual_priority = 5
        score = structured_motivation_score(lead)
        assert score <= 25.0


class TestAnalystFindings:
    def test_fsbo_finding_raises_motivation_and_survives_sync(self, app):
        with app.app_context():
            lead = Property(**_base_lead_kwargs())
            db.session.add(lead)
            db.session.commit()

            svc = MotivationSignalService()
            before = structured_motivation_score(lead)
            row = svc.add_analyst_finding(
                lead, 'OWNER_SELLING_FSBO', note='Confirmed on site', actor='tester',
            )
            assert row.is_active is True
            assert row.source == 'analyst'
            assert lead.motivation_score >= before + 10

            # Enrichment sync must not wipe analyst findings.
            lead.tax_distress_data = _scavenger_tax_distress()
            db.session.add(lead)
            db.session.commit()
            svc.sync_from_lead(lead)

            active = MotivationSignal.query.filter_by(
                lead_id=lead.id, is_active=True, source='analyst',
            ).all()
            assert any(s.signal_type == 'OWNER_SELLING_FSBO' for s in active)
            assert lead.motivation_score >= 12.0

            labels = ' '.join(
                (item.get('label') or '') for item in (lead.motivation_signal_summary or [])
            )
            assert 'FSBO' in labels

    def test_selling_status_findings_are_mutually_exclusive(self, app):
        with app.app_context():
            lead = Property(**_base_lead_kwargs())
            db.session.add(lead)
            db.session.commit()

            svc = MotivationSignalService()
            svc.add_analyst_finding(lead, 'OWNER_SELLING_FSBO')
            svc.add_analyst_finding(lead, 'OWNER_NOT_SELLING')

            active_types = {
                s.signal_type
                for s in MotivationSignal.query.filter_by(
                    lead_id=lead.id, is_active=True, source='analyst',
                ).all()
            }
            assert active_types == {'OWNER_NOT_SELLING'}
            assert lead.motivation_score < 0

    def test_remove_analyst_finding(self, app):
        with app.app_context():
            lead = Property(**_base_lead_kwargs())
            db.session.add(lead)
            db.session.commit()

            svc = MotivationSignalService()
            row = svc.add_analyst_finding(lead, 'LISTED_WITH_AGENT')
            assert svc.remove_analyst_finding(lead, row.id) is True
            assert MotivationSignal.query.filter_by(
                lead_id=lead.id, is_active=True, source='analyst',
            ).count() == 0
            assert float(lead.motivation_score or 0) == 0.0

    def test_unknown_finding_key_rejected(self, app):
        with app.app_context():
            lead = Property(**_base_lead_kwargs())
            db.session.add(lead)
            db.session.commit()
            with pytest.raises(ValueError, match='Unknown finding_key'):
                MotivationSignalService().add_analyst_finding(lead, 'NOT_A_REAL_FINDING')
