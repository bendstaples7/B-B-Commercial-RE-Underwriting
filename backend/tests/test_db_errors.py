"""Constraint names must reach the screen instead of a blank 500."""
from sqlalchemy.exc import IntegrityError

from app.db_errors import (
    integrity_constraint_name,
    integrity_error_message,
    is_unique_integrity_error,
)


def test_reads_postgres_unique_constraint_name():
    exc = IntegrityError(
        'INSERT',
        {},
        Exception(
            'duplicate key value violates unique constraint "uq_leads_owner_assessor_pin"'
        ),
    )
    assert integrity_constraint_name(exc) == 'uq_leads_owner_assessor_pin'
    message = integrity_error_message(exc, action='Combine')
    assert message == 'Combine was blocked by database rule uq_leads_owner_assessor_pin.'
    assert 'An unexpected error occurred' not in message


def test_sqlite_unique_violation_uses_uniqueness_fallback():
    exc = IntegrityError(
        'INSERT',
        {},
        Exception('UNIQUE constraint failed: leads.owner_id, leads.assessor_pin'),
    )
    assert integrity_constraint_name(exc) is None
    assert is_unique_integrity_error(exc) is True
    assert (
        integrity_error_message(exc, action='Combine')
        == 'Combine was blocked by a database uniqueness rule.'
    )


def test_unnamed_non_unique_integrity_error_uses_generic_message():
    exc = IntegrityError(
        'INSERT',
        {},
        Exception('NOT NULL constraint failed: leads.owner_user_id'),
    )
    assert integrity_constraint_name(exc) is None
    assert is_unique_integrity_error(exc) is False
    assert (
        integrity_error_message(exc, action='Combine')
        == 'Combine was blocked by a database integrity rule.'
    )


def test_handle_errors_returns_the_index_name():
    from flask import Flask

    from app.controllers.decorators import handle_errors

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['PROPAGATE_EXCEPTIONS'] = False

    @app.route('/boom')
    @handle_errors
    def boom():
        raise IntegrityError(
            'INSERT',
            {},
            Exception(
                'duplicate key value violates unique constraint "uq_leads_owner_normalized_street"'
            ),
        )

    response = app.test_client().get('/boom')
    assert response.status_code == 409
    body = response.get_json()
    assert body['error'] == 'Conflict'
    assert body['constraint'] == 'uq_leads_owner_normalized_street'
    assert 'uq_leads_owner_normalized_street' in body['message']
    assert 'An unexpected error occurred' not in response.get_data(as_text=True)


def test_handle_errors_uses_generic_message_for_non_unique_integrity_error():
    from flask import Flask

    from app.controllers.decorators import handle_errors

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['PROPAGATE_EXCEPTIONS'] = False

    @app.route('/boom')
    @handle_errors
    def boom():
        raise IntegrityError(
            'INSERT',
            {},
            Exception('NOT NULL constraint failed: leads.owner_user_id'),
        )

    response = app.test_client().get('/boom')
    assert response.status_code == 409
    body = response.get_json()
    assert body['error'] == 'Integrity error'
    assert body['constraint'] is None
    assert body['message'] == 'This save was blocked by a database integrity rule.'
