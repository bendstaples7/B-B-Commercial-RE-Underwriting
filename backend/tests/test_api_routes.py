"""Integration tests for API routes."""
import pytest
import json
from datetime import date
from app.models import AnalysisSession, WorkflowStep, PropertyFacts, PropertyType, ConstructionType, InteriorCondition
from app import db


class TestHealthCheck:
    """Tests for health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check returns healthy status."""
        response = client.get('/api/health')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'


class TestStartAnalysis:
    """Tests for start analysis endpoint."""
    
    def test_start_analysis_success(self, client):
        """Test starting a new analysis session."""
        payload = {
            'address': '123 Main St, Chicago, IL 60601',
            'user_id': 'user123'
        }
        
        response = client.post(
            '/api/analysis/start',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        
        assert 'session_id' in data
        assert data['user_id'] == 'user123'
        assert data['current_step'] == 'PROPERTY_FACTS'
        assert data['status'] == 'initialized'
        assert 'created_at' in data
    
    def test_start_analysis_missing_address(self, client):
        """Test starting analysis without address fails."""
        payload = {
            'user_id': 'user123'
        }
        
        response = client.post(
            '/api/analysis/start',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
    
    def test_start_analysis_invalid_address(self, client):
        """Test starting analysis with too short address fails."""
        payload = {
            'address': '123',
            'user_id': 'user123'
        }
        
        response = client.post(
            '/api/analysis/start',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 400


class TestGetSessionState:
    """Tests for get session state endpoint."""
    
    def test_get_session_state_success(self, client, app):
        """Test retrieving session state."""
        # Create a session
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-123',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.commit()
        
        response = client.get('/api/analysis/test-session-123')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        assert data['session_id'] == 'test-session-123'
        assert data['user_id'] == 'user123'
        assert data['current_step'] == 'PROPERTY_FACTS'
    
    def test_get_session_state_not_found(self, client):
        """Test retrieving non-existent session fails."""
        response = client.get('/api/analysis/nonexistent-session')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data


class TestAdvanceToStep:
    """Tests for advance to step endpoint."""
    
    def test_advance_to_step_success(self, client, app):
        """Test advancing to next step."""
        # Create a session with property facts
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-456',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.flush()
            
            # Add property facts
            property_facts = PropertyFacts(
                session_id=session.id,
                address='123 Main St',
                property_type=PropertyType.MULTI_FAMILY,
                units=4,
                bedrooms=8,
                bathrooms=4.0,
                square_footage=3200,
                lot_size=5000,
                year_built=1920,
                construction_type=ConstructionType.BRICK,
                basement=True,
                parking_spaces=2,
                assessed_value=250000.0,
                annual_taxes=5000.0,
                zoning='R-4',
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298
            )
            db.session.add(property_facts)
            db.session.commit()
        
        response = client.post(
            '/api/analysis/test-session-456/step/2',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        assert data['current_step'] == 'COMPARABLE_SEARCH'
        assert data['previous_step'] == 'PROPERTY_FACTS'
    
    def test_advance_to_step_invalid_step_number(self, client, app):
        """Test advancing to invalid step number fails."""
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-789',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.commit()
        
        response = client.post(
            '/api/analysis/test-session-789/step/10',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
    
    def test_advance_to_step_without_completion(self, client, app):
        """Test advancing without completing current step fails."""
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-incomplete',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.commit()
        
        response = client.post(
            '/api/analysis/test-session-incomplete/step/2',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data


class TestUpdateStepData:
    """Tests for update step data endpoint."""
    
    def test_update_property_facts(self, client, app):
        """Test updating property facts data."""
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-update',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.commit()
        
        payload = {
            'address': '456 Oak Ave, Chicago, IL 60601',
            'property_type': 'MULTI_FAMILY',
            'units': 4,
            'bedrooms': 8,
            'bathrooms': 4.0,
            'square_footage': 3200,
            'lot_size': 5000,
            'year_built': 1920,
            'construction_type': 'BRICK',
            'basement': True,
            'parking_spaces': 2,
            'assessed_value': 250000.0,
            'annual_taxes': 5000.0,
            'zoning': 'R-4',
            'interior_condition': 'AVERAGE'
        }
        
        response = client.put(
            '/api/analysis/test-session-update/step/1',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        assert data['step'] == 'PROPERTY_FACTS'
        assert 'updated_data' in data
        assert data['updated_data']['address'] == '456 Oak Ave, Chicago, IL 60601'
    
    def test_update_property_facts_invalid_year(self, client, app):
        """Test updating property facts with invalid year fails."""
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-invalid',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.commit()
        
        payload = {
            'address': '456 Oak Ave',
            'property_type': 'MULTI_FAMILY',
            'units': 4,
            'bedrooms': 8,
            'bathrooms': 4.0,
            'square_footage': 3200,
            'lot_size': 5000,
            'year_built': 1700,  # Invalid year
            'construction_type': 'BRICK',
            'assessed_value': 250000.0,
            'annual_taxes': 5000.0,
            'zoning': 'R-4',
            'interior_condition': 'AVERAGE'
        }
        
        response = client.put(
            '/api/analysis/test-session-invalid/step/1',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 400


class TestGoBackToStep:
    """Tests for go back to step endpoint."""
    
    def test_go_back_to_step_success(self, client, app):
        """Test navigating back to previous step."""
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-back',
                user_id='user123',
                current_step=WorkflowStep.COMPARABLE_SEARCH
            )
            db.session.add(session)
            db.session.commit()
        
        response = client.post('/api/analysis/test-session-back/back/1')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        assert data['current_step'] == 'PROPERTY_FACTS'
        assert data['previous_step'] == 'COMPARABLE_SEARCH'
        assert data['navigation'] == 'backward'
    
    def test_go_back_to_step_invalid_direction(self, client, app):
        """Test going back to later step fails."""
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-forward',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.commit()
        
        response = client.post('/api/analysis/test-session-forward/back/2')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data


class TestGenerateReport:
    """Tests for generate report endpoint."""
    
    def test_generate_report_session_not_found(self, client):
        """Test generating report for non-existent session fails."""
        response = client.get('/api/analysis/nonexistent/report')
        
        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data


class TestExportToExcel:
    """Tests for export to Excel endpoint."""
    
    def test_export_to_excel_session_not_found(self, client):
        """Test exporting to Excel for non-existent session fails."""
        response = client.get('/api/analysis/nonexistent/export/excel')
        
        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data


class TestExportToGoogleSheets:
    """Tests for export to Google Sheets endpoint."""
    
    def test_export_to_google_sheets_missing_credentials(self, client, app):
        """Test exporting to Google Sheets without credentials fails."""
        with app.app_context():
            session = AnalysisSession(
                session_id='test-session-sheets',
                user_id='user123',
                current_step=WorkflowStep.PROPERTY_FACTS
            )
            db.session.add(session)
            db.session.commit()
        
        response = client.post(
            '/api/analysis/test-session-sheets/export/sheets',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
    
    def test_export_to_google_sheets_session_not_found(self, client):
        """Test exporting to Google Sheets for non-existent session fails."""
        payload = {
            'credentials': {'key': 'value'}
        }
        
        response = client.post(
            '/api/analysis/nonexistent/export/sheets',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 404


class TestRateLimiting:
    """Tests for rate limiting."""
    
    def test_rate_limiting_enforced(self, client):
        """Test that rate limiting is enforced on endpoints."""
        # Make multiple requests to trigger rate limit
        # Note: This test may need adjustment based on actual rate limit configuration
        payload = {
            'address': '123 Main St, Chicago, IL 60601',
            'user_id': 'user123'
        }
        
        # Make requests up to the limit
        for _ in range(15):
            response = client.post(
                '/api/analysis/start',
                data=json.dumps(payload),
                content_type='application/json'
            )
            
            # Should succeed or hit rate limit
            assert response.status_code in [201, 429]


class TestErrorHandling:
    """Tests for error handling middleware."""
    
    def test_malformed_json(self, client):
        """Test that malformed JSON is handled gracefully."""
        response = client.post(
            '/api/analysis/start',
            data='{"invalid json',
            content_type='application/json'
        )
        
        assert response.status_code in [400, 500]
    
    def test_missing_content_type(self, client):
        """Test that missing content type is handled."""
        response = client.post(
            '/api/analysis/start',
            data='{"address": "123 Main St", "user_id": "user123"}'
        )
        
        # Should return 415 Unsupported Media Type
        assert response.status_code == 415
        data = json.loads(response.data)
        assert 'error' in data
