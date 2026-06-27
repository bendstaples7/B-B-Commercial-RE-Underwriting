"""Tests for engagement-based scoring in LeadScoringEngine."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app import create_app, db
from app.models import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.lead_scoring_engine import LeadScoringEngine
import os


@pytest.fixture
def app_ctx():
    previous_db = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
    if previous_db is not None:
        os.environ['DATABASE_URL'] = previous_db
    elif 'DATABASE_URL' in os.environ:
        del os.environ['DATABASE_URL']


def _make_weights():
    w = MagicMock()
    w.property_characteristics_weight = 0.25
    w.data_completeness_weight = 0.25
    w.owner_situation_weight = 0.25
    w.location_desirability_weight = 0.25
    return w


def test_answered_call_increases_engagement_score(app_ctx):
    with app_ctx.app_context():
        lead = Lead(
            property_street='1 Engage St',
            lead_status='mailing_no_contact_made',
            has_phone=True,
            has_email=True,
            has_property_match=True,
            analysis_complete=True,
            lead_score=0.0,
        )
        db.session.add(lead)
        db.session.commit()

        db.session.add(LeadTimelineEntry(
            lead_id=lead.id,
            event_type='call_logged',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor='user',
            summary='Call logged: answered',
            event_metadata={'outcome': 'answered'},
        ))
        db.session.commit()

        engine = LeadScoringEngine()
        base = engine.compute_score(lead, _make_weights(), signals=[])
        assert base >= 10.0


def test_wrong_number_call_decreases_engagement_score(app_ctx):
    with app_ctx.app_context():
        lead = Lead(
            property_street='2 Engage St',
            lead_status='mailing_no_contact_made',
            has_phone=True,
            has_email=True,
            has_property_match=True,
            analysis_complete=True,
            lead_score=50.0,
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
        )
        db.session.add(lead)
        db.session.commit()

        db.session.add(LeadTimelineEntry(
            lead_id=lead.id,
            event_type='call_logged',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor='user',
            summary='Call logged: wrong_number',
            event_metadata={'outcome': 'wrong_number'},
        ))
        db.session.commit()

        engine = LeadScoringEngine()
        score = engine.compute_score(lead, _make_weights(), signals=[])
        assert score <= 25.0
