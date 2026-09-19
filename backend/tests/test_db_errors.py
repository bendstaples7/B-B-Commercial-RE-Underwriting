"""Constraint names must reach the screen instead of a blank 500."""
from sqlalchemy.exc import IntegrityError

from app.db_errors import integrity_constraint_name, integrity_error_message


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


def test_reads_sqlite_unique_index_name():
    exc = IntegrityError(
        'INSERT',
        {},
        Exception(
            "UNIQUE constraint failed: index 'uq_leads_owner_normalized_street'"
        ),
    )
    assert integrity_constraint_name(exc) == 'uq_leads_owner_normalized_street'


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
