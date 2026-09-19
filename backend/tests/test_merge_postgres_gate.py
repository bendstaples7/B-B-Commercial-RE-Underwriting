"""Production Postgres must be able to combine two leads.

The parallel pytest suite uses SQLite and ``create_all()``. That schema does
not include ``uq_leads_owner_normalized_street`` or
``uq_leads_owner_assessor_pin``. Combine shipped green and then 500'd on
every real merge. This file runs only when ``POSTGRES_MERGE_GATE=1``, against
a database that has already been through ``flask db upgrade``.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('POSTGRES_MERGE_GATE') != '1',
    reason='POSTGRES_MERGE_GATE=1 runs this against a migrated Postgres database',
)

REQUIRED_INDEXES = (
    'uq_leads_owner_normalized_street',
    'uq_leads_owner_assessor_pin',
)


@pytest.fixture(scope='module')
def gate_app():
    url = os.environ.get('DATABASE_URL', '')
    if not url.startswith('postgres'):
        pytest.fail(
            f'POSTGRES_MERGE_GATE requires a Postgres DATABASE_URL, got {url!r}'
        )
    env = {
        'DATABASE_URL': url,
        'FLASK_ENV': 'testing',
        'SECRET_KEY': os.environ.get('SECRET_KEY', 'postgres-merge-gate-secret'),
        'JWT_SECRET_KEY': os.environ.get('JWT_SECRET_KEY', 'postgres-merge-gate-jwt'),
        'KIRO_MIGRATION': '1',
    }
    with patch.dict(os.environ, env, clear=False):
        from app import create_app

        app = create_app('testing')
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = url
        yield app


def _index_names(gate_app) -> set[str]:
    from sqlalchemy import text

    from app import db

    with gate_app.app_context():
        assert db.engine.dialect.name == 'postgresql'
        rows = db.session.execute(text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname IN (
                'uq_leads_owner_normalized_street',
                'uq_leads_owner_assessor_pin'
              )
            """
        )).scalars().all()
    return set(rows)


def test_migrated_postgres_has_dedup_unique_indexes(gate_app):
    missing = set(REQUIRED_INDEXES) - _index_names(gate_app)
    assert not missing, (
        'flask db upgrade did not create production dedup indexes: '
        + ', '.join(sorted(missing))
    )


def _owner(user_id: str):
    from app.models.user import User

    email = f'merge-gate-{uuid.uuid4().hex[:8]}@example.com'
    user = User(
        user_id=user_id,
        email=email,
        email_lower=email.lower(),
        password_hash='not-used',
        display_name='Merge Gate',
    )
    return user


def _post_combine(gate_app, loser_id: int, winner_id: int, user_id: str, choices: dict):
    with patch(
        'app.services.property_address_service.ensure_lead_property_address_complete',
    ), patch(
        'app.services.lead_refresh.refresh_lead_scoring',
    ):
        client = gate_app.test_client()
        return client.post(
            f'/api/leads/{loser_id}/merge-into/{winner_id}',
            json={'choices': choices},
            headers={'X-User-Id': user_id},
        )


def test_combine_keeps_pin_and_selected_person(gate_app):
    """The dialog POST. Same account, other lead still holds the PIN and name."""
    from app import db
    from app.models.lead import Lead

    user_id = str(uuid.uuid4())
    pin = '14092030010000'
    choices = {
        'property_street': '10 Gate St',
        'property_city': None,
        'property_state': None,
        'property_zip': None,
        'county_assessor_pin': pin,
        'property_type': None,
        'units': None,
        'lead_status': 'skip_trace',
        'source': None,
        'deal_source': None,
        'data_source': None,
        'people_names': ['Grace Hopper'],
        'keep_incoming_people': True,
        'keep_primary_people': False,
        'keep_incoming_activities': True,
        'keep_primary_activities': True,
        'keep_incoming_companies': True,
        'keep_primary_companies': True,
    }
    winner_id = loser_id = None
    with gate_app.app_context():
        owner = _owner(user_id)
        db.session.add(owner)
        db.session.commit()
        try:
            winner = Lead(
                property_street='10 Gate St',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                owner_user_id=user_id,
                lead_status='skip_trace',
            )
            loser = Lead(
                property_street='10 Gate St',
                owner_first_name='Grace',
                owner_last_name='Hopper',
                owner_user_id=user_id,
                county_assessor_pin=pin,
                lead_status='skip_trace',
            )
            db.session.add_all([winner, loser])
            db.session.commit()
            winner_id, loser_id = winner.id, loser.id

            response = _post_combine(gate_app, loser_id, winner_id, user_id, choices)
            body = response.get_json(silent=True)
            assert response.status_code == 200, body
            assert body['merged'] is True
            assert 'An unexpected error occurred' not in str(body)
            db.session.expire_all()
            assert db.session.get(Lead, loser_id) is None
            saved = db.session.get(Lead, winner_id)
            assert saved.county_assessor_pin == pin
            assert saved.owner_first_name == 'Grace'
            assert saved.owner_last_name == 'Hopper'
        finally:
            db.session.rollback()
            for lead_id in (loser_id, winner_id):
                if lead_id is None:
                    continue
                row = db.session.get(Lead, lead_id)
                if row is not None:
                    db.session.delete(row)
            leftover = db.session.get(type(owner), owner.id) if owner.id else None
            if leftover is not None:
                db.session.delete(leftover)
            db.session.commit()


def test_combine_aligns_street_for_the_same_owner(gate_app):
    from app import db
    from app.models.lead import Lead
    from app.services.lead_merge_utils import streets_match_normalized

    user_id = str(uuid.uuid4())
    with gate_app.app_context():
        owner = _owner(user_id)
        db.session.add(owner)
        db.session.commit()
        winner_id = loser_id = None
        try:
            winner = Lead(
                property_street='2834 N Drake',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                owner_user_id=user_id,
                lead_status='skip_trace',
            )
            loser = Lead(
                property_street='2834 N Drake Rear',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                owner_user_id=user_id,
                lead_status='skip_trace',
            )
            db.session.add_all([winner, loser])
            db.session.commit()
            winner_id, loser_id = winner.id, loser.id
            assert winner.normalized_street != loser.normalized_street
            assert streets_match_normalized(winner.property_street, loser.property_street)

            response = _post_combine(
                gate_app,
                loser_id,
                winner_id,
                user_id,
                {
                    'property_street': '2834 N Drake Rear',
                    'people_names': ['Francisco R Solis'],
                    'county_assessor_pin': None,
                    'lead_status': 'skip_trace',
                    'keep_primary_people': True,
                    'keep_incoming_people': True,
                    'keep_primary_activities': True,
                    'keep_incoming_activities': True,
                    'keep_primary_companies': True,
                    'keep_incoming_companies': True,
                },
            )
            body = response.get_json(silent=True)
            assert response.status_code == 200, body
            assert 'An unexpected error occurred' not in str(body)
            db.session.expire_all()
            saved = db.session.get(Lead, winner_id)
            assert saved.property_street == '2834 N Drake Rear'
            assert db.session.get(Lead, loser_id) is None
        finally:
            db.session.rollback()
            for lead_id in (loser_id, winner_id):
                if lead_id is None:
                    continue
                row = db.session.get(Lead, lead_id)
                if row is not None:
                    db.session.delete(row)
            leftover_owner = db.session.get(type(owner), owner.id)
            if leftover_owner is not None:
                db.session.delete(leftover_owner)
            db.session.commit()
