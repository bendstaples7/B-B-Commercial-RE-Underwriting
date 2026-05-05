"""Integration tests for condo filter pipeline.

Tests the full pipeline end-to-end: seed leads, run analysis, verify DB state,
get results, get detail, apply override, and verify cascade effects.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 8.1, 12.2
"""
import json
import pytest
from datetime import datetime, timezone

from app import db
from app.models.lead import Lead
from app.models.address_group_analysis import AddressGroupAnalysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_commercial_leads(app):
    """Seed a realistic set of commercial leads for integration testing.

    Creates leads at multiple addresses with varying characteristics:
    - 100 Main St: 3 leads with unit markers (likely condo)
    - 200 Oak Ave: 1 lead, single owner/PIN (likely not condo)
    - 300 Elm St: 2 leads, same owner, different PINs (partial condo possible)
    """
    leads_data = [
        # 100 Main St group - unit markers indicate condo
        {
            'property_street': '100 Main St Unit 1',
            'county_assessor_pin': 'PIN-100-1',
            'owner_first_name': 'Alice',
            'owner_last_name': 'Johnson',
            'property_type': 'commercial',
            'lead_category': 'commercial',
            'mailing_address': '500 Mail Rd',
        },
        {
            'property_street': '100 Main St Unit 2',
            'county_assessor_pin': 'PIN-100-2',
            'owner_first_name': 'Bob',
            'owner_last_name': 'Williams',
            'property_type': 'commercial',
            'lead_category': 'commercial',
            'mailing_address': '501 Mail Rd',
        },
        {
            'property_street': '100 Main St Unit 3',
            'county_assessor_pin': 'PIN-100-3',
            'owner_first_name': 'Carol',
            'owner_last_name': 'Davis',
            'property_type': 'commercial',
            'lead_category': 'commercial',
            'mailing_address': '502 Mail Rd',
        },
        # 200 Oak Ave - single owner, single PIN
        {
            'property_street': '200 Oak Ave',
            'county_assessor_pin': 'PIN-200-1',
            'owner_first_name': 'David',
            'owner_last_name': 'Brown',
            'property_type': 'commercial',
            'lead_category': 'commercial',
            'mailing_address': '600 Mail Rd',
        },
        # 300 Elm St - same owner, multiple PINs (different suffixes normalize to same address)
        {
            'property_street': '300 Elm St Suite A',
            'county_assessor_pin': 'PIN-300-1',
            'owner_first_name': 'Eve',
            'owner_last_name': 'Wilson',
            'property_type': 'mixed use',
            'lead_category': 'commercial',
            'mailing_address': '700 Mail Rd',
        },
        {
            'property_street': '300 Elm St Suite B',
            'county_assessor_pin': 'PIN-300-2',
            'owner_first_name': 'Eve',
            'owner_last_name': 'Wilson',
            'property_type': 'mixed use',
            'lead_category': 'commercial',
            'mailing_address': '701 Mail Rd',
        },
    ]

    leads = []
    for data in leads_data:
        defaults = {
            'property_city': 'Chicago',
            'property_state': 'IL',
            'property_zip': '60601',
            'mailing_city': 'Chicago',
            'mailing_state': 'IL',
            'mailing_zip': '60601',
        }
        defaults.update(data)
        lead = Lead(**defaults)
        db.session.add(lead)
        leads.append(lead)

    db.session.commit()
    return leads


# ---------------------------------------------------------------------------
# Tests: Full pipeline integration
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Tests for the full condo filter pipeline end-to-end."""

    def test_full_pipeline_seed_analyze_verify(self, client, app):
        """Full pipeline: seed leads -> analyze -> verify DB state."""
        with app.app_context():
            leads = _seed_commercial_leads(app)

        # Run analysis
        resp = client.post('/api/condo-filter/analyze')
        assert resp.status_code == 200
        data = json.loads(resp.data)

        # Verify summary
        assert data['total_groups'] == 3  # 100 Main, 200 Oak, 300 Elm
        assert data['total_properties'] == 6

        # Verify DB state
        with app.app_context():
            analyses = AddressGroupAnalysis.query.all()
            assert len(analyses) == 3

            # Verify each group's classification
            addr_map = {a.normalized_address: a for a in analyses}

            # 100 Main St has unit markers -> likely_condo
            main_st = addr_map.get('100 main st')
            assert main_st is not None
            assert main_st.condo_risk_status == 'likely_condo'
            assert main_st.building_sale_possible == 'no'
            assert main_st.property_count == 3
            assert main_st.has_unit_number is True

            # 200 Oak Ave single owner/PIN -> likely_not_condo
            oak_ave = addr_map.get('200 oak ave')
            assert oak_ave is not None
            assert oak_ave.condo_risk_status == 'likely_not_condo'
            assert oak_ave.building_sale_possible == 'yes'
            assert oak_ave.property_count == 1

    def test_pipeline_get_results_after_analysis(self, client, app):
        """After analysis, GET results returns all groups."""
        with app.app_context():
            _seed_commercial_leads(app)

        client.post('/api/condo-filter/analyze')

        resp = client.get('/api/condo-filter/results')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['total'] == 3

    def test_pipeline_get_detail_with_leads(self, client, app):
        """After analysis, GET detail returns linked leads."""
        with app.app_context():
            _seed_commercial_leads(app)

        client.post('/api/condo-filter/analyze')

        with app.app_context():
            # Find the 100 Main St group (has 3 leads)
            analysis = AddressGroupAnalysis.query.filter_by(
                normalized_address='100 main st'
            ).first()
            analysis_id = analysis.id

        resp = client.get(f'/api/condo-filter/results/{analysis_id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['leads']) == 3

    def test_pipeline_override_cascades(self, client, app):
        """Override cascades to all linked leads in the group."""
        with app.app_context():
            _seed_commercial_leads(app)

        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.filter_by(
                normalized_address='100 main st'
            ).first()
            analysis_id = analysis.id

        # Apply override
        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
            'reason': 'Verified whole building sale',
        }
        resp = client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200

        # Verify all linked leads updated
        with app.app_context():
            linked_leads = Lead.query.filter_by(condo_analysis_id=analysis_id).all()
            assert len(linked_leads) == 3
            for lead in linked_leads:
                assert lead.condo_risk_status == 'likely_not_condo'
                assert lead.building_sale_possible == 'yes'


# ---------------------------------------------------------------------------
# Tests: Unique constraint enforcement
# ---------------------------------------------------------------------------

class TestUniqueConstraint:
    """Tests for unique constraint on normalized_address."""

    def test_unique_constraint_prevents_duplicates(self, client, app):
        """Cannot create two records with same normalized_address."""
        with app.app_context():
            a1 = AddressGroupAnalysis(
                normalized_address='100 main st',
                source_type='commercial',
                property_count=1,
                pin_count=1,
                owner_count=1,
                has_unit_number=False,
                has_condo_language=False,
                missing_pin_count=0,
                missing_owner_count=0,
                condo_risk_status='likely_not_condo',
                building_sale_possible='yes',
            )
            db.session.add(a1)
            db.session.commit()

            a2 = AddressGroupAnalysis(
                normalized_address='100 main st',
                source_type='commercial',
                property_count=2,
                pin_count=2,
                owner_count=2,
                has_unit_number=True,
                has_condo_language=False,
                missing_pin_count=0,
                missing_owner_count=0,
                condo_risk_status='likely_condo',
                building_sale_possible='no',
            )
            db.session.add(a2)

            with pytest.raises(Exception):
                db.session.commit()

            db.session.rollback()


# ---------------------------------------------------------------------------
# Tests: Foreign key integrity
# ---------------------------------------------------------------------------

class TestForeignKeyIntegrity:
    """Tests for foreign key integrity on condo_analysis_id."""

    def test_lead_references_valid_analysis(self, client, app):
        """After analysis, lead.condo_analysis_id references a valid record."""
        with app.app_context():
            lead = Lead(
                property_street='100 Main St',
                property_type='commercial',
                lead_category='commercial',
                owner_first_name='Test',
                owner_last_name='User',
                county_assessor_pin='PIN001',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
            )
            db.session.add(lead)
            db.session.commit()

        client.post('/api/condo-filter/analyze')

        with app.app_context():
            lead = Lead.query.filter_by(property_street='100 Main St').first()
            assert lead.condo_analysis_id is not None
            # Verify the referenced record exists
            analysis = db.session.get(AddressGroupAnalysis, lead.condo_analysis_id)
            assert analysis is not None
            assert analysis.normalized_address == '100 main st'


# ---------------------------------------------------------------------------
# Tests: Re-analysis preserves overrides
# ---------------------------------------------------------------------------

class TestReanalysisPreservesOverrides:
    """Tests for re-analysis preserving manual override fields."""

    def test_reanalysis_preserves_override_fields(self, client, app):
        """Re-analysis updates automated fields but preserves override fields."""
        with app.app_context():
            lead = Lead(
                property_street='100 Main St',
                property_type='commercial',
                lead_category='commercial',
                owner_first_name='Test',
                owner_last_name='User',
                county_assessor_pin='PIN001',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
            )
            db.session.add(lead)
            db.session.commit()

        # First analysis
        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            analysis_id = analysis.id

        # Apply override
        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
            'reason': 'User verified',
        }
        client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )

        # Re-run analysis
        client.post('/api/condo-filter/analyze')

        # Verify override preserved
        with app.app_context():
            analysis = db.session.get(AddressGroupAnalysis, analysis_id)
            assert analysis.manually_reviewed is True
            assert analysis.manual_override_status == 'likely_not_condo'
            assert analysis.manual_override_reason == 'User verified'
            # Automated fields still updated
            assert analysis.analyzed_at is not None
            assert analysis.analysis_details is not None

    def test_reanalysis_updates_analysis_details(self, client, app):
        """Re-analysis updates analysis_details even for overridden records."""
        with app.app_context():
            lead = Lead(
                property_street='100 Main St',
                property_type='commercial',
                lead_category='commercial',
                owner_first_name='Test',
                owner_last_name='User',
                county_assessor_pin='PIN001',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
            )
            db.session.add(lead)
            db.session.commit()

        # First analysis
        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            analysis_id = analysis.id

        # Apply override
        payload = {
            'condo_risk_status': 'likely_condo',
            'building_sale_possible': 'no',
            'reason': 'Override reason',
        }
        client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )

        # Re-run analysis
        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = db.session.get(AddressGroupAnalysis, analysis_id)
            # analysis_details should still be present (updated by re-analysis)
            assert analysis.analysis_details is not None
            assert 'triggered_rules' in analysis.analysis_details


# ---------------------------------------------------------------------------
# Tests: Filter application to CSV export
# ---------------------------------------------------------------------------

class TestCsvFilterIntegration:
    """Tests for filter application to CSV export in the full pipeline."""

    def test_csv_export_after_analysis_with_filter(self, client, app):
        """CSV export after analysis respects filters."""
        with app.app_context():
            _seed_commercial_leads(app)

        # Run analysis
        client.post('/api/condo-filter/analyze')

        # Export only likely_not_condo records (200 Oak Ave is the only one)
        resp = client.get('/api/condo-filter/export/csv?condo_risk_status=likely_not_condo')
        assert resp.status_code == 200
        lines = resp.data.decode().strip().split('\n')
        # Header + filtered rows (only 200 Oak Ave is likely_not_condo)
        assert len(lines) == 2  # header + 1 data row
        assert '200 oak ave' in lines[1]

    def test_csv_export_contains_all_linked_lead_data(self, client, app):
        """CSV export contains concatenated data from all linked leads."""
        with app.app_context():
            _seed_commercial_leads(app)

        client.post('/api/condo-filter/analyze')

        # Export all records
        resp = client.get('/api/condo-filter/export/csv')
        assert resp.status_code == 200
        content = resp.data.decode()

        # The 100 Main St group has 3 leads with different PINs
        # Verify multiple PINs are present in the CSV
        assert 'PIN-100-1' in content
        assert 'PIN-100-2' in content
        assert 'PIN-100-3' in content
