"""Integration tests for Lead API endpoints."""
import json
import pytest
from datetime import date, datetime

from app import db
from app.models import (
    AnalysisSession,
    Lead,
    LeadAuditTrail,
    MarketingList,
    MarketingListMember,
    ScoringWeights,
    WorkflowStep,
    DataSource,
    EnrichmentRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_lead(app, **overrides):
    """Create a lead record with sensible defaults."""
    defaults = {
        'property_street': '100 Test St',
        'property_city': 'Chicago',
        'property_state': 'IL',
        'property_zip': '60601',
        'owner_first_name': 'John',
        'owner_last_name': 'Doe',
        'property_type': 'single_family',
        'mailing_city': 'Chicago',
        'mailing_state': 'IL',
        'mailing_zip': '60601',
        'lead_score': 50.0,
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _create_leads_batch(app, count, base_score=50.0):
    """Create *count* leads with unique addresses and incrementing scores."""
    leads = []
    for i in range(count):
        lead = Lead(
            property_street=f'{100 + i} Batch St',
            owner_first_name=f'Owner',
            owner_last_name=f'Batch{i}',
            property_type='single_family',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            lead_score=base_score + i,
        )
        db.session.add(lead)
        leads.append(lead)
    db.session.commit()
    return leads


# ---------------------------------------------------------------------------
# Tests: GET /api/leads/
# ---------------------------------------------------------------------------

class TestListLeads:
    """Tests for the lead listing endpoint."""

    def test_list_leads_empty(self, client, app):
        """Empty database returns empty list with correct pagination."""
        response = client.get('/api/leads/')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['leads'] == []
        assert data['total'] == 0
        assert data['page'] == 1

    def test_list_leads_returns_leads(self, client, app):
        """Returns created leads."""
        with app.app_context():
            _create_lead(app)
        response = client.get('/api/leads/')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['total'] == 1
        assert data['leads'][0]['property_street'] == '100 Test St'

    def test_list_leads_pagination(self, client, app):
        """Pagination returns correct page slices."""
        with app.app_context():
            _create_leads_batch(app, 25)

        resp1 = client.get('/api/leads/?page=1&per_page=10')
        d1 = json.loads(resp1.data)
        assert len(d1['leads']) == 10
        assert d1['total'] == 25
        assert d1['pages'] == 3

        resp3 = client.get('/api/leads/?page=3&per_page=10')
        d3 = json.loads(resp3.data)
        assert len(d3['leads']) == 5

    def test_list_leads_filter_property_type(self, client, app):
        """Filter by property_type returns only matching leads."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', property_type='single_family')
            _create_lead(app, property_street='2 B St', property_type='multi_family')

        resp = client.get('/api/leads/?property_type=single_family')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['leads'][0]['property_type'] == 'single_family'

    def test_list_leads_filter_city(self, client, app):
        """Filter by city (case-insensitive)."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', mailing_city='Chicago')
            _create_lead(app, property_street='2 B St', mailing_city='Denver')

        resp = client.get('/api/leads/?city=chicago')
        data = json.loads(resp.data)
        assert data['total'] == 1

    def test_list_leads_filter_state(self, client, app):
        """Filter by state (case-insensitive)."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', mailing_state='IL')
            _create_lead(app, property_street='2 B St', mailing_state='CO')

        resp = client.get('/api/leads/?state=il')
        data = json.loads(resp.data)
        assert data['total'] == 1

    def test_list_leads_filter_zip(self, client, app):
        """Filter by zip code (exact match)."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', mailing_zip='60601')
            _create_lead(app, property_street='2 B St', mailing_zip='80202')

        resp = client.get('/api/leads/?zip=60601')
        data = json.loads(resp.data)
        assert data['total'] == 1

    def test_list_leads_filter_owner_name(self, client, app):
        """Filter by owner name (partial, case-insensitive)."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', owner_first_name='Alice', owner_last_name='Smith')
            _create_lead(app, property_street='2 B St', owner_first_name='Bob', owner_last_name='Jones')

        resp = client.get('/api/leads/?owner_name=alice')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['leads'][0]['owner_first_name'] == 'Alice'

    def test_list_leads_filter_score_range(self, client, app):
        """Filter by score range."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', lead_score=30.0)
            _create_lead(app, property_street='2 B St', lead_score=60.0)
            _create_lead(app, property_street='3 C St', lead_score=90.0)

        resp = client.get('/api/leads/?score_min=50&score_max=70')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['leads'][0]['lead_score'] == 60.0

    def test_list_leads_filter_marketing_list(self, client, app):
        """Filter by marketing list membership."""
        with app.app_context():
            lead1 = _create_lead(app, property_street='1 A St')
            lead2 = _create_lead(app, property_street='2 B St')
            ml = MarketingList(name='Hot Leads', user_id='user1')
            db.session.add(ml)
            db.session.flush()
            ml_id = ml.id
            member = MarketingListMember(marketing_list_id=ml.id, lead_id=lead1.id)
            db.session.add(member)
            db.session.commit()

        resp = client.get(f'/api/leads/?marketing_list_id={ml_id}')
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert data['leads'][0]['property_street'] == '1 A St'

    def test_list_leads_sort_by_score_asc(self, client, app):
        """Sort by lead_score ascending."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', lead_score=80.0)
            _create_lead(app, property_street='2 B St', lead_score=20.0)
            _create_lead(app, property_street='3 C St', lead_score=50.0)

        resp = client.get('/api/leads/?sort_by=lead_score&sort_order=asc')
        data = json.loads(resp.data)
        scores = [l['lead_score'] for l in data['leads']]
        assert scores == sorted(scores)

    def test_list_leads_sort_by_score_desc(self, client, app):
        """Sort by lead_score descending (default)."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', lead_score=80.0)
            _create_lead(app, property_street='2 B St', lead_score=20.0)
            _create_lead(app, property_street='3 C St', lead_score=50.0)

        resp = client.get('/api/leads/?sort_by=lead_score&sort_order=desc')
        data = json.loads(resp.data)
        scores = [l['lead_score'] for l in data['leads']]
        assert scores == sorted(scores, reverse=True)

    def test_list_leads_invalid_sort_field_falls_back(self, client, app):
        """Invalid sort_by falls back to created_at."""
        with app.app_context():
            _create_lead(app)
        resp = client.get('/api/leads/?sort_by=invalid_field')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: GET /api/leads/<lead_id>
# ---------------------------------------------------------------------------

class TestGetLead:
    """Tests for the lead detail endpoint."""

    def test_get_lead_success(self, client, app):
        """Returns full lead detail."""
        with app.app_context():
            lead = _create_lead(app)
            lead_id = lead.id

        resp = client.get(f'/api/leads/{lead_id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['id'] == lead_id
        assert data['property_street'] == '100 Test St'
        assert 'enrichment_records' in data
        assert 'marketing_lists' in data
        assert 'analysis_session' in data

    def test_get_lead_not_found(self, client, app):
        """Returns 404 for non-existent lead."""
        resp = client.get('/api/leads/99999')
        assert resp.status_code == 404
        data = json.loads(resp.data)
        assert data['error'] == 'Lead not found'

    def test_get_lead_with_enrichment_records(self, client, app):
        """Detail includes enrichment records."""
        with app.app_context():
            lead = _create_lead(app)
            ds = DataSource(name='County Records')
            db.session.add(ds)
            db.session.flush()
            er = EnrichmentRecord(
                lead_id=lead.id,
                data_source_id=ds.id,
                status='success',
                retrieved_data={'tax_value': 250000},
            )
            db.session.add(er)
            db.session.commit()
            lead_id = lead.id

        resp = client.get(f'/api/leads/{lead_id}')
        data = json.loads(resp.data)
        assert len(data['enrichment_records']) == 1
        assert data['enrichment_records'][0]['status'] == 'success'
        assert data['enrichment_records'][0]['data_source_name'] == 'County Records'

    def test_get_lead_with_marketing_lists(self, client, app):
        """Detail includes marketing list memberships."""
        with app.app_context():
            lead = _create_lead(app)
            ml = MarketingList(name='Campaign A', user_id='user1')
            db.session.add(ml)
            db.session.flush()
            member = MarketingListMember(
                marketing_list_id=ml.id,
                lead_id=lead.id,
                outreach_status='contacted',
            )
            db.session.add(member)
            db.session.commit()
            lead_id = lead.id

        resp = client.get(f'/api/leads/{lead_id}')
        data = json.loads(resp.data)
        assert len(data['marketing_lists']) == 1
        assert data['marketing_lists'][0]['marketing_list_name'] == 'Campaign A'
        assert data['marketing_lists'][0]['outreach_status'] == 'contacted'

    def test_get_lead_with_analysis_session(self, client, app):
        """Detail includes linked analysis session."""
        with app.app_context():
            session = AnalysisSession(
                session_id='linked-session',
                user_id='user1',
                current_step=WorkflowStep.PROPERTY_FACTS,
            )
            db.session.add(session)
            db.session.flush()
            lead = _create_lead(app, analysis_session_id=session.id)
            lead_id = lead.id

        resp = client.get(f'/api/leads/{lead_id}')
        data = json.loads(resp.data)
        assert data['analysis_session'] is not None
        assert data['analysis_session']['session_id'] == 'linked-session'


# ---------------------------------------------------------------------------
# Tests: POST /api/leads/<lead_id>/analyze
# ---------------------------------------------------------------------------

class TestAnalyzeLead:
    """Tests for creating an analysis session from a lead."""

    def test_analyze_lead_success(self, client, app):
        """Creates an AnalysisSession linked to the lead."""
        with app.app_context():
            lead = _create_lead(
                app,
                bedrooms=3,
                bathrooms=2.0,
                square_footage=1500,
                lot_size=5000,
                year_built=1990,
            )
            lead_id = lead.id

        resp = client.post(
            f'/api/leads/{lead_id}/analyze',
            data=json.dumps({'user_id': 'user1'}),
            content_type='application/json',
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert 'session_id' in data
        assert data['lead_id'] == lead_id
        assert data['current_step'] == 'PROPERTY_FACTS'
        assert data['pre_populated']['address'] == '100 Test St'
        assert data['pre_populated']['bedrooms'] == 3
        assert data['pre_populated']['square_footage'] == 1500

    def test_analyze_lead_not_found(self, client, app):
        """Returns 404 for non-existent lead."""
        resp = client.post(
            '/api/leads/99999/analyze',
            data=json.dumps({'user_id': 'user1'}),
            content_type='application/json',
        )
        assert resp.status_code == 404

    def test_analyze_lead_missing_user_id(self, client, app):
        """Returns 400 when user_id is missing."""
        with app.app_context():
            lead = _create_lead(app)
            lead_id = lead.id

        resp = client.post(
            f'/api/leads/{lead_id}/analyze',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_analyze_lead_links_session(self, client, app):
        """After analysis, the lead's analysis_session_id is set."""
        with app.app_context():
            lead = _create_lead(app)
            lead_id = lead.id

        resp = client.post(
            f'/api/leads/{lead_id}/analyze',
            data=json.dumps({'user_id': 'user1'}),
            content_type='application/json',
        )
        data = json.loads(resp.data)

        detail_resp = client.get(f'/api/leads/{lead_id}')
        detail = json.loads(detail_resp.data)
        assert detail['analysis_session'] is not None
        assert detail['analysis_session']['session_id'] == data['session_id']


# ---------------------------------------------------------------------------
# Tests: GET /api/leads/scoring/weights
# ---------------------------------------------------------------------------

class TestGetScoringWeights:
    """Tests for retrieving scoring weights."""

    def test_get_weights_default(self, client, app):
        """Returns default weights when none exist for user."""
        resp = client.get('/api/leads/scoring/weights?user_id=new_user')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['user_id'] == 'new_user'
        assert data['property_characteristics_weight'] == 0.30
        assert data['data_completeness_weight'] == 0.20
        assert data['owner_situation_weight'] == 0.30
        assert data['location_desirability_weight'] == 0.20

    def test_get_weights_existing(self, client, app):
        """Returns existing weights for user."""
        with app.app_context():
            sw = ScoringWeights(
                user_id='existing_user',
                property_characteristics_weight=0.40,
                data_completeness_weight=0.10,
                owner_situation_weight=0.30,
                location_desirability_weight=0.20,
            )
            db.session.add(sw)
            db.session.commit()

        resp = client.get('/api/leads/scoring/weights?user_id=existing_user')
        data = json.loads(resp.data)
        assert data['property_characteristics_weight'] == 0.40
        assert data['data_completeness_weight'] == 0.10


# ---------------------------------------------------------------------------
# Tests: PUT /api/leads/scoring/weights
# ---------------------------------------------------------------------------

class TestUpdateScoringWeights:
    """Tests for updating scoring weights."""

    def test_update_weights_success(self, client, app):
        """Updates weights and returns new values."""
        payload = {
            'user_id': 'user1',
            'property_characteristics_weight': 0.25,
            'data_completeness_weight': 0.25,
            'owner_situation_weight': 0.25,
            'location_desirability_weight': 0.25,
        }
        resp = client.put(
            '/api/leads/scoring/weights',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['property_characteristics_weight'] == 0.25
        assert 'leads_rescored' in data

    def test_update_weights_invalid_sum(self, client, app):
        """Returns 400 when weights don't sum to 1.0."""
        payload = {
            'user_id': 'user1',
            'property_characteristics_weight': 0.50,
            'data_completeness_weight': 0.50,
            'owner_situation_weight': 0.50,
            'location_desirability_weight': 0.50,
        }
        resp = client.put(
            '/api/leads/scoring/weights',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_update_weights_missing_field(self, client, app):
        """Returns 400 when a weight field is missing."""
        payload = {
            'user_id': 'user1',
            'property_characteristics_weight': 0.25,
        }
        resp = client.put(
            '/api/leads/scoring/weights',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_update_weights_missing_user_id(self, client, app):
        """Returns 400 when user_id is missing."""
        payload = {
            'property_characteristics_weight': 0.25,
            'data_completeness_weight': 0.25,
            'owner_situation_weight': 0.25,
            'location_desirability_weight': 0.25,
        }
        resp = client.put(
            '/api/leads/scoring/weights',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_update_weights_no_body(self, client, app):
        """Returns 400 when request body is empty."""
        resp = client.put(
            '/api/leads/scoring/weights',
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_update_weights_rescores_leads(self, client, app):
        """After updating weights, existing leads are rescored."""
        with app.app_context():
            _create_lead(
                app,
                property_street='1 Score St',
                lead_score=50.0,
                bedrooms=3,
                bathrooms=2.0,
                square_footage=1500,
                phone_1='555-1234',
            )

        payload = {
            'user_id': 'user1',
            'property_characteristics_weight': 0.25,
            'data_completeness_weight': 0.25,
            'owner_situation_weight': 0.25,
            'location_desirability_weight': 0.25,
        }
        resp = client.put(
            '/api/leads/scoring/weights',
            data=json.dumps(payload),
            content_type='application/json',
        )
        data = json.loads(resp.data)
        assert data['leads_rescored'] >= 1


# ---------------------------------------------------------------------------
# Tests: Combined filter + sort + pagination
# ---------------------------------------------------------------------------

class TestCombinedFilters:
    """Tests for combining multiple filters, sorting, and pagination."""

    def test_filter_and_sort(self, client, app):
        """Combine state filter with score sort."""
        with app.app_context():
            _create_lead(app, property_street='1 A St', mailing_state='IL', lead_score=80.0)
            _create_lead(app, property_street='2 B St', mailing_state='IL', lead_score=40.0)
            _create_lead(app, property_street='3 C St', mailing_state='CO', lead_score=90.0)

        resp = client.get('/api/leads/?state=IL&sort_by=lead_score&sort_order=desc')
        data = json.loads(resp.data)
        assert data['total'] == 2
        assert data['leads'][0]['lead_score'] == 80.0
        assert data['leads'][1]['lead_score'] == 40.0

    def test_per_page_capped_at_max(self, client, app):
        """per_page is capped at MAX_PER_PAGE (100)."""
        with app.app_context():
            _create_leads_batch(app, 5)

        resp = client.get('/api/leads/?per_page=500')
        data = json.loads(resp.data)
        assert data['per_page'] == 100
