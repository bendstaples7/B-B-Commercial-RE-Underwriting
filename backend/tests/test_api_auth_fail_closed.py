"""Fail-closed /api auth: anonymous callers cannot hit product routes.

Public exceptions are the explicit allowlist in ``api_utils.PUBLIC_API_ROUTES``.
"""
from __future__ import annotations

import json
import re

import uuid

from app import db
from app.api_utils import PUBLIC_API_ROUTES, is_public_api_request
from app.models.lead import Lead
from app.models.user import User
from app.services.auth_service import AuthService
from tests.conftest import ANON_HEADERS


_PATH_INT = re.compile(r'<int:[^>]+>')
_PATH_TYPED = re.compile(r'<[^:>]+:[^>]+>')
_PATH_BARE = re.compile(r'<[^>]+>')


def _rule_path(rule) -> str:
    path = _PATH_INT.sub('1', rule.rule)
    path = _PATH_TYPED.sub('x', path)
    return _PATH_BARE.sub('x', path)


def _rule_method(rule) -> str | None:
    methods = {m.upper() for m in (rule.methods or set())} - {'HEAD', 'OPTIONS'}
    for preferred in ('GET', 'POST', 'PATCH', 'PUT', 'DELETE'):
        if preferred in methods:
            return preferred
    return next(iter(methods), None)


def test_public_allowlist_is_explicit_and_small():
    """Only boot/login/webhook beacons may skip the identity gate."""
    assert ('POST', '/api/auth/login') in PUBLIC_API_ROUTES
    assert ('GET', '/api/health') in PUBLIC_API_ROUTES
    assert ('POST', '/api/leads/1/do-not-contact') not in PUBLIC_API_ROUTES
    assert ('POST', '/api/contacts/') not in PUBLIC_API_ROUTES
    assert len(PUBLIC_API_ROUTES) <= 12


def test_is_public_api_request_matches_allowlist():
    assert is_public_api_request('GET', '/api/health') is True
    assert is_public_api_request('GET', '/api/version') is True
    assert is_public_api_request('POST', '/api/auth/login') is True
    assert is_public_api_request('OPTIONS', '/api/leads/1/do-not-contact') is True
    assert is_public_api_request('POST', '/api/leads/1/do-not-contact') is False
    assert is_public_api_request('POST', '/api/contacts/') is False


def test_anonymous_cannot_mark_do_not_contact(client, app):
    from app import db
    from app.models.lead import Lead

    with app.app_context():
        lead = Lead(
            property_street='99 Anon DNC St',
            lead_status='mailing_no_contact_made',
            owner_user_id='test-user',
        )
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

    resp = client.post(
        f'/api/leads/{lead_id}/do-not-contact',
        data=json.dumps({}),
        content_type='application/json',
        headers=ANON_HEADERS,
    )
    assert resp.status_code == 401
    assert resp.get_json()['error'] == 'Authentication required'
    with app.app_context():
        assert db.session.get(Lead, lead_id).lead_status == 'mailing_no_contact_made'


def test_anonymous_cannot_create_or_read_contacts(client):
    create = client.post(
        '/api/contacts/',
        json={'first_name': 'Anon', 'last_name': 'Leak'},
        headers=ANON_HEADERS,
    )
    assert create.status_code == 401
    fetch = client.get('/api/contacts/1', headers=ANON_HEADERS)
    assert fetch.status_code == 401
    delete = client.delete('/api/contacts/1', headers=ANON_HEADERS)
    assert delete.status_code == 401


def test_anonymous_cannot_read_timeline_or_recommended_action(client):
    timeline = client.get('/api/leads/1/timeline', headers=ANON_HEADERS)
    assert timeline.status_code == 401
    ra = client.get('/api/leads/1/recommended-action', headers=ANON_HEADERS)
    assert ra.status_code == 401


def test_public_health_still_anonymous(anon_client):
    resp = anon_client.get('/api/health')
    assert resp.status_code in (200, 503)
    body = resp.get_json() or {}
    assert body.get('error') != 'Authentication required'


def test_public_login_still_anonymous(anon_client):
    resp = anon_client.post(
        '/api/auth/login',
        json={'email': 'nobody@example.com', 'password': 'wrong-password'},
    )
    assert resp.status_code in (400, 401)
    body = resp.get_json() or {}
    assert body.get('error') != 'Authentication required'


def test_every_non_public_api_rule_rejects_anonymous(client, app):
    """Walk the Flask map so a new route cannot ship without the identity gate."""
    failures = []
    with app.app_context():
        for rule in app.url_map.iter_rules():
            if not rule.rule.startswith('/api'):
                continue
            method = _rule_method(rule)
            if not method:
                continue
            path = _rule_path(rule)
            if is_public_api_request(method, path):
                continue
            resp = client.open(
                path,
                method=method,
                content_type='application/json',
                headers=ANON_HEADERS,
            )
            body = resp.get_json(silent=True) or {}
            if resp.status_code != 401 or body.get('error') != 'Authentication required':
                failures.append(
                    f'{method} {path} -> {resp.status_code} {body!r}'
                )
    assert not failures, 'Anonymous callers reached protected /api routes:\n' + '\n'.join(
        failures[:40]
    )


def _persist_user(email: str) -> User:
    user = User(
        user_id=str(uuid.uuid4()),
        email=email,
        email_lower=email.lower(),
        password_hash='$2b$12$fakehashfakehashfakehashfakehashfakehashfakehash',
        display_name='Auth Gate',
        is_active=True,
        is_admin=False,
        password_set=False,
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_setup_token_cannot_read_undecorated_product_routes(client, app):
    """Password-setup JWTs must not act as a session on routes without @require_auth."""
    with app.app_context():
        user = _persist_user('setup-gate@example.com')
        lead = Lead(
            property_street='1 Setup Leak St',
            owner_user_id=user.user_id,
        )
        db.session.add(lead)
        db.session.commit()
        token = AuthService().issue_setup_token(user)

    headers = {'Authorization': f'Bearer {token}'}
    for path in (
        '/api/properties/',
        '/api/multifamily/deals',
        '/api/queues/counts',
        '/api/kanban/leads',
    ):
        resp = client.get(path, headers=headers)
        assert resp.status_code == 401, path
        assert resp.get_json()['error'] == (
            'Setup token cannot be used for authentication'
        )
        body = resp.get_json() or {}
        assert '1 Setup Leak St' not in json.dumps(body)


def test_inactive_jwt_cannot_read_undecorated_product_routes(client, app):
    """Deactivated accounts must lose access even on routes without @require_auth."""
    with app.app_context():
        user = _persist_user('inactive-gate@example.com')
        user.password_set = True
        token = AuthService().issue_token(user)
        user.is_active = False
        db.session.commit()

    resp = client.get(
        '/api/multifamily/deals',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == 401
    assert resp.get_json()['error'] == 'Authentication required'


def test_setup_token_still_reaches_set_password(client, app):
    """POST /api/auth/set-password remains the only public use of a setup JWT."""
    with app.app_context():
        user = _persist_user('setup-ok@example.com')
        token = AuthService().issue_setup_token(user)

    resp = client.post(
        '/api/auth/set-password',
        json={'new_password': 'newpass12'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code != 401
    assert (resp.get_json() or {}).get('error') != (
        'Setup token cannot be used for authentication'
    )


def test_celery_job_id_is_bound_to_deal():
    from app.controllers.multifamily_deal_controller import (
        celery_job_belongs_to_deal,
        celery_job_id_for_deal,
    )

    job_id = celery_job_id_for_deal(42, 'rent')
    assert celery_job_belongs_to_deal(job_id, 42) is True
    assert celery_job_belongs_to_deal(job_id, 99) is False
    assert celery_job_belongs_to_deal('plain-uuid', 42) is False
    assert celery_job_belongs_to_deal(None, 42) is False
