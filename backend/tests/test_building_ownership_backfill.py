"""Tests for commercial building ownership backfill."""
from datetime import datetime, timedelta, timezone

from app import db
from app.models.address_group_analysis import AddressGroupAnalysis
from app.models.lead import Lead
from app.services.building_ownership_backfill import (
    is_commercial_cook_county_lead,
    lead_needs_building_ownership_analysis,
    query_lead_ids_for_building_ownership_backfill,
)


def _commercial_lead(app, street='3017 W George St', **kwargs):
    with app.app_context():
        lead = Lead(
            owner_first_name='Test',
            owner_last_name='Owner',
            property_street=street,
            property_city='Chicago',
            property_state='IL',
            property_zip='60618',
            lead_category='commercial',
            lead_status=kwargs.get('lead_status', 'skip_trace'),
            lead_score=50,
            has_property_match=True,
            source_type='import',
        )
        db.session.add(lead)
        db.session.commit()
        return lead.id


class TestBuildingOwnershipBackfill:
    def test_commercial_chicago_lead_is_eligible(self, app):
        with app.app_context():
            lead = db.session.get(Lead, _commercial_lead(app))
            assert is_commercial_cook_county_lead(lead) is True
            assert lead_needs_building_ownership_analysis(lead) is True

    def test_residential_lead_not_eligible(self, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='Res',
                owner_last_name='Owner',
                property_street='100 Main St',
                property_city='Chicago',
                property_state='IL',
                lead_category='residential',
                lead_status='skip_trace',
                lead_score=50,
                has_property_match=True,
                source_type='import',
            )
            db.session.add(lead)
            db.session.commit()
            assert lead_needs_building_ownership_analysis(lead) is False

    def test_manual_override_skips_reanalysis(self, app):
        with app.app_context():
            lead_id = _commercial_lead(app)
            lead = db.session.get(Lead, lead_id)
            analysis = AddressGroupAnalysis(
                normalized_address='3017 W GEORGE ST',
                source_type='commercial',
                condo_risk_status='likely_not_condo',
                building_sale_possible='yes',
                manually_reviewed=True,
                manual_override_status='likely_not_condo',
                analyzed_at=datetime.now(timezone.utc) - timedelta(days=90),
            )
            db.session.add(analysis)
            db.session.flush()
            lead.condo_analysis_id = analysis.id
            db.session.commit()
            assert lead_needs_building_ownership_analysis(lead) is False

    def test_query_returns_commercial_leads(self, app):
        lead_id = _commercial_lead(app)
        with app.app_context():
            ids = query_lead_ids_for_building_ownership_backfill(last_id=0, limit=50)
            assert lead_id in ids
