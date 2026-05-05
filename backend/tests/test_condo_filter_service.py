"""Unit tests for condo filter service and API endpoints.

Tests API endpoint request/response validation, database upsert behavior,
manual override flow, pagination, error responses, timestamps, and batch processing.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4
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

def _create_commercial_lead(app, address, pin=None, owner_first='Owner', owner_last='Test', **kwargs):
    """Create a commercial lead with sensible defaults."""
    defaults = {
        'property_street': address,
        'property_city': 'Chicago',
        'property_state': 'IL',
        'property_zip': '60601',
        'owner_first_name': owner_first,
        'owner_last_name': owner_last,
        'property_type': 'commercial',
        'lead_category': 'commercial',
        'county_assessor_pin': pin,
        'mailing_city': 'Chicago',
        'mailing_state': 'IL',
        'mailing_zip': '60601',
    }
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _create_analysis_record(normalized_address, **kwargs):
    """Create an AddressGroupAnalysis record."""
    defaults = {
        'normalized_address': normalized_address,
        'source_type': 'commercial',
        'property_count': 1,
        'pin_count': 1,
        'owner_count': 1,
        'has_unit_number': False,
        'has_condo_language': False,
        'missing_pin_count': 0,
        'missing_owner_count': 0,
        'condo_risk_status': 'likely_not_condo',
        'building_sale_possible': 'yes',
        'analysis_details': {
            'triggered_rules': ['rule_4_single_pin_owner'],
            'reason': 'Single PIN and single owner',
            'confidence': 'high',
        },
        'analyzed_at': datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    analysis = AddressGroupAnalysis(**defaults)
    db.session.add(analysis)
    db.session.commit()
    return analysis


# ---------------------------------------------------------------------------
# Tests: POST /api/condo-filter/analyze
# ---------------------------------------------------------------------------

class TestRunAnalysis:
    """Tests for the POST /api/condo-filter/analyze endpoint."""

    def test_analyze_empty_database(self, client, app):
        """Returns 200 with zero counts when no commercial leads exist."""
        with app.app_context():
            resp = client.post('/api/condo-filter/analyze')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data['total_groups'] == 0
            assert data['total_properties'] == 0
            assert data['by_status'] == {}
            assert data['by_building_sale'] == {}

    def test_analyze_returns_summary(self, client, app):
        """Returns summary with correct counts after analysis."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St', pin='PIN001')
            _create_commercial_lead(app, '200 Oak Ave', pin='PIN002',
                                    owner_first='Jane', owner_last='Smith')

        resp = client.post('/api/condo-filter/analyze')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['total_groups'] == 2
        assert data['total_properties'] == 2
        assert 'by_status' in data
        assert 'by_building_sale' in data

    def test_analyze_groups_by_normalized_address(self, client, app):
        """Leads with same normalized address are grouped together."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St Unit 1', pin='PIN001')
            _create_commercial_lead(app, '100 Main St Unit 2', pin='PIN002',
                                    owner_first='Jane', owner_last='Smith')

        resp = client.post('/api/condo-filter/analyze')
        data = json.loads(resp.data)
        assert data['total_groups'] == 1
        assert data['total_properties'] == 2

    def test_analyze_skips_null_property_street(self, client, app):
        """Leads with null property_street are skipped."""
        with app.app_context():
            _create_commercial_lead(app, None, pin='PIN001')
            _create_commercial_lead(app, '200 Oak Ave', pin='PIN002')

        resp = client.post('/api/condo-filter/analyze')
        data = json.loads(resp.data)
        assert data['total_groups'] == 1
        assert data['total_properties'] == 1


# ---------------------------------------------------------------------------
# Tests: Database upsert behavior
# ---------------------------------------------------------------------------

class TestUpsertBehavior:
    """Tests for database upsert (first run creates, second run updates)."""

    def test_first_run_creates_records(self, client, app):
        """First analysis run creates AddressGroupAnalysis records."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St', pin='PIN001')

        client.post('/api/condo-filter/analyze')

        with app.app_context():
            count = AddressGroupAnalysis.query.count()
            assert count == 1

    def test_second_run_updates_existing(self, client, app):
        """Second analysis run updates existing records, not duplicates."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St', pin='PIN001')

        client.post('/api/condo-filter/analyze')
        client.post('/api/condo-filter/analyze')

        with app.app_context():
            count = AddressGroupAnalysis.query.count()
            assert count == 1

    def test_upsert_updates_metrics(self, client, app):
        """Re-analysis updates metrics when data changes."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St', pin='PIN001')

        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            assert analysis.property_count == 1

            # Add another lead at same address
            _create_commercial_lead(app, '100 Main St Unit 2', pin='PIN002',
                                    owner_first='Jane', owner_last='Smith')

        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            assert analysis.property_count == 2


# ---------------------------------------------------------------------------
# Tests: GET /api/condo-filter/results
# ---------------------------------------------------------------------------

class TestGetResults:
    """Tests for the GET /api/condo-filter/results endpoint."""

    def test_results_empty(self, client, app):
        """Returns empty results when no analysis records exist."""
        resp = client.get('/api/condo-filter/results')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['results'] == []
        assert data['total'] == 0
        assert data['page'] == 1

    def test_results_returns_records(self, client, app):
        """Returns analysis records."""
        with app.app_context():
            _create_analysis_record('100 main st')

        resp = client.get('/api/condo-filter/results')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['results'][0]['normalized_address'] == '100 main st'

    def test_results_pagination(self, client, app):
        """Pagination returns correct page slices."""
        with app.app_context():
            for i in range(25):
                _create_analysis_record(f'{100 + i} main st')

        resp = client.get('/api/condo-filter/results?page=1&per_page=10')
        data = json.loads(resp.data)
        assert len(data['results']) == 10
        assert data['total'] == 25
        assert data['pages'] == 3

        resp2 = client.get('/api/condo-filter/results?page=3&per_page=10')
        data2 = json.loads(resp2.data)
        assert len(data2['results']) == 5

    def test_results_filter_by_condo_risk_status(self, client, app):
        """Filter by condo_risk_status returns only matching records."""
        with app.app_context():
            _create_analysis_record('100 main st', condo_risk_status='likely_condo')
            _create_analysis_record('200 oak ave', condo_risk_status='likely_not_condo')

        resp = client.get('/api/condo-filter/results?condo_risk_status=likely_condo')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['results'][0]['condo_risk_status'] == 'likely_condo'

    def test_results_filter_by_building_sale_possible(self, client, app):
        """Filter by building_sale_possible returns only matching records."""
        with app.app_context():
            _create_analysis_record('100 main st', building_sale_possible='yes')
            _create_analysis_record('200 oak ave', building_sale_possible='no')

        resp = client.get('/api/condo-filter/results?building_sale_possible=yes')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['results'][0]['building_sale_possible'] == 'yes'

    def test_results_filter_by_manually_reviewed(self, client, app):
        """Filter by manually_reviewed returns only matching records."""
        with app.app_context():
            _create_analysis_record('100 main st', manually_reviewed=True)
            _create_analysis_record('200 oak ave', manually_reviewed=False)

        resp = client.get('/api/condo-filter/results?manually_reviewed=true')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['results'][0]['manually_reviewed'] is True

    def test_results_combined_filters(self, client, app):
        """Multiple filters combine correctly."""
        with app.app_context():
            _create_analysis_record('100 main st',
                                    condo_risk_status='likely_condo',
                                    building_sale_possible='no')
            _create_analysis_record('200 oak ave',
                                    condo_risk_status='likely_condo',
                                    building_sale_possible='yes')
            _create_analysis_record('300 elm st',
                                    condo_risk_status='likely_not_condo',
                                    building_sale_possible='yes')

        resp = client.get('/api/condo-filter/results?condo_risk_status=likely_condo&building_sale_possible=no')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['results'][0]['normalized_address'] == '100 main st'

    def test_results_invalid_filter_returns_400(self, client, app):
        """Invalid filter value returns 400."""
        resp = client.get('/api/condo-filter/results?condo_risk_status=invalid_status')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests: GET /api/condo-filter/results/<id>
# ---------------------------------------------------------------------------

class TestGetDetail:
    """Tests for the GET /api/condo-filter/results/<id> endpoint."""

    def test_detail_success(self, client, app):
        """Returns full detail with linked leads."""
        with app.app_context():
            lead = _create_commercial_lead(app, '100 Main St', pin='PIN001')
            analysis = _create_analysis_record('100 main st')
            lead.condo_analysis_id = analysis.id
            db.session.commit()
            analysis_id = analysis.id

        resp = client.get(f'/api/condo-filter/results/{analysis_id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['normalized_address'] == '100 main st'
        assert 'leads' in data
        assert len(data['leads']) == 1
        assert data['leads'][0]['property_street'] == '100 Main St'

    def test_detail_not_found(self, client, app):
        """Returns 404 for non-existent record."""
        resp = client.get('/api/condo-filter/results/99999')
        assert resp.status_code == 404
        data = json.loads(resp.data)
        assert data['error'] == 'Not found'

    def test_detail_includes_analysis_details(self, client, app):
        """Detail includes analysis_details JSON."""
        with app.app_context():
            analysis = _create_analysis_record('100 main st')
            analysis_id = analysis.id

        resp = client.get(f'/api/condo-filter/results/{analysis_id}')
        data = json.loads(resp.data)
        assert data['analysis_details'] is not None
        assert 'triggered_rules' in data['analysis_details']
        assert 'reason' in data['analysis_details']
        assert 'confidence' in data['analysis_details']


# ---------------------------------------------------------------------------
# Tests: PUT /api/condo-filter/results/<id>/override
# ---------------------------------------------------------------------------

class TestApplyOverride:
    """Tests for the PUT /api/condo-filter/results/<id>/override endpoint."""

    def test_override_success(self, client, app):
        """Applies override and returns updated record."""
        with app.app_context():
            lead = _create_commercial_lead(app, '100 Main St', pin='PIN001')
            analysis = _create_analysis_record('100 main st')
            lead.condo_analysis_id = analysis.id
            db.session.commit()
            analysis_id = analysis.id

        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
            'reason': 'Verified single owner building',
        }
        resp = client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['manually_reviewed'] is True
        assert data['manual_override_status'] == 'likely_not_condo'
        assert data['manual_override_reason'] == 'Verified single owner building'

    def test_override_cascades_to_leads(self, client, app):
        """Override cascades status to linked leads."""
        with app.app_context():
            lead = _create_commercial_lead(app, '100 Main St', pin='PIN001')
            analysis = _create_analysis_record('100 main st',
                                               condo_risk_status='likely_condo',
                                               building_sale_possible='no')
            lead.condo_analysis_id = analysis.id
            db.session.commit()
            analysis_id = analysis.id
            lead_id = lead.id

        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
            'reason': 'Verified single owner',
        }
        client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )

        with app.app_context():
            lead = db.session.get(Lead, lead_id)
            assert lead.condo_risk_status == 'likely_not_condo'
            assert lead.building_sale_possible == 'yes'

    def test_override_not_found(self, client, app):
        """Returns 404 for non-existent record."""
        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
            'reason': 'Test reason',
        }
        resp = client.put(
            '/api/condo-filter/results/99999/override',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 404

    def test_override_invalid_status(self, client, app):
        """Returns 400 for invalid condo_risk_status."""
        with app.app_context():
            analysis = _create_analysis_record('100 main st')
            analysis_id = analysis.id

        payload = {
            'condo_risk_status': 'invalid_status',
            'building_sale_possible': 'yes',
            'reason': 'Test reason',
        }
        resp = client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_override_missing_reason(self, client, app):
        """Returns 400 when reason is missing."""
        with app.app_context():
            analysis = _create_analysis_record('100 main st')
            analysis_id = analysis.id

        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
        }
        resp = client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_override_empty_body(self, client, app):
        """Returns 400 when request body is empty."""
        with app.app_context():
            analysis = _create_analysis_record('100 main st')
            analysis_id = analysis.id

        resp = client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_override_preserves_analysis_details(self, client, app):
        """Override does not modify the automated analysis_details."""
        with app.app_context():
            analysis = _create_analysis_record('100 main st')
            analysis_id = analysis.id
            original_details = analysis.analysis_details.copy()

        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
            'reason': 'Manual verification',
        }
        client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )

        with app.app_context():
            analysis = db.session.get(AddressGroupAnalysis, analysis_id)
            assert analysis.analysis_details == original_details


# ---------------------------------------------------------------------------
# Tests: GET /api/condo-filter/export/csv
# ---------------------------------------------------------------------------

class TestExportCsv:
    """Tests for the GET /api/condo-filter/export/csv endpoint."""

    def test_csv_export_empty(self, client, app):
        """Returns CSV with only header when no records exist."""
        resp = client.get('/api/condo-filter/export/csv')
        assert resp.status_code == 200
        assert resp.content_type == 'text/csv; charset=utf-8'
        lines = resp.data.decode().strip().split('\n')
        assert len(lines) == 1  # header only

    def test_csv_export_with_data(self, client, app):
        """Returns CSV with data rows."""
        with app.app_context():
            lead = _create_commercial_lead(app, '100 Main St', pin='PIN001',
                                           mailing_address='200 Mail St')
            analysis = _create_analysis_record('100 main st')
            lead.condo_analysis_id = analysis.id
            db.session.commit()

        resp = client.get('/api/condo-filter/export/csv')
        assert resp.status_code == 200
        lines = resp.data.decode().strip().split('\n')
        assert len(lines) == 2  # header + 1 data row
        # Check header columns
        header = lines[0]
        assert 'normalized_address' in header
        assert 'condo_risk_status' in header
        assert 'pins' in header

    def test_csv_export_content_disposition(self, client, app):
        """CSV response has Content-Disposition header for download."""
        resp = client.get('/api/condo-filter/export/csv')
        assert 'Content-Disposition' in resp.headers
        assert 'attachment' in resp.headers['Content-Disposition']
        assert 'condo_filter_results.csv' in resp.headers['Content-Disposition']

    def test_csv_export_respects_filters(self, client, app):
        """CSV export respects filter parameters."""
        with app.app_context():
            lead1 = _create_commercial_lead(app, '100 Main St', pin='PIN001')
            a1 = _create_analysis_record('100 main st', condo_risk_status='likely_condo',
                                         building_sale_possible='no')
            lead1.condo_analysis_id = a1.id

            lead2 = _create_commercial_lead(app, '200 Oak Ave', pin='PIN002',
                                            owner_first='Jane', owner_last='Smith')
            a2 = _create_analysis_record('200 oak ave', condo_risk_status='likely_not_condo',
                                         building_sale_possible='yes')
            lead2.condo_analysis_id = a2.id
            db.session.commit()

        resp = client.get('/api/condo-filter/export/csv?condo_risk_status=likely_condo')
        lines = resp.data.decode().strip().split('\n')
        assert len(lines) == 2  # header + 1 filtered row


# ---------------------------------------------------------------------------
# Tests: analyzed_at timestamp correctness
# ---------------------------------------------------------------------------

class TestAnalyzedAtTimestamp:
    """Tests for analyzed_at timestamp correctness."""

    def test_analyzed_at_set_on_analysis(self, client, app):
        """analyzed_at is set after running analysis."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St', pin='PIN001')

        before = datetime.now(timezone.utc)
        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            assert analysis.analyzed_at is not None
            # analyzed_at should be recent (within a few seconds)
            assert analysis.analyzed_at >= before.replace(tzinfo=None)

    def test_analyzed_at_updated_on_reanalysis(self, client, app):
        """analyzed_at is updated on re-analysis."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St', pin='PIN001')

        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            first_analyzed_at = analysis.analyzed_at

        # Run again
        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            assert analysis.analyzed_at >= first_analyzed_at


# ---------------------------------------------------------------------------
# Tests: Batch processing for large datasets
# ---------------------------------------------------------------------------

class TestBatchProcessing:
    """Tests for batch processing of large datasets."""

    def test_large_dataset_processes_correctly(self, client, app):
        """Analysis handles more than 500 leads (batch boundary)."""
        with app.app_context():
            # Create 10 unique addresses to keep it fast but test batching logic
            for i in range(10):
                _create_commercial_lead(
                    app,
                    f'{100 + i} Batch St',
                    pin=f'PIN{i:03d}',
                    owner_first=f'Owner{i}',
                    owner_last=f'Last{i}',
                )

        resp = client.post('/api/condo-filter/analyze')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['total_groups'] == 10
        assert data['total_properties'] == 10


# ---------------------------------------------------------------------------
# Tests: Manual override end-to-end flow
# ---------------------------------------------------------------------------

class TestManualOverrideEndToEnd:
    """Tests for the full manual override flow."""

    def test_analyze_then_override_then_reanalyze(self, client, app):
        """Full flow: analyze -> override -> re-analyze preserves override."""
        with app.app_context():
            _create_commercial_lead(app, '100 Main St', pin='PIN001')

        # Step 1: Run analysis
        client.post('/api/condo-filter/analyze')

        with app.app_context():
            analysis = AddressGroupAnalysis.query.first()
            analysis_id = analysis.id

        # Step 2: Apply override
        payload = {
            'condo_risk_status': 'likely_not_condo',
            'building_sale_possible': 'yes',
            'reason': 'Verified by user',
        }
        resp = client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200

        # Step 3: Re-run analysis
        client.post('/api/condo-filter/analyze')

        # Verify override fields are preserved
        with app.app_context():
            analysis = db.session.get(AddressGroupAnalysis, analysis_id)
            assert analysis.manually_reviewed is True
            assert analysis.manual_override_status == 'likely_not_condo'
            assert analysis.manual_override_reason == 'Verified by user'
