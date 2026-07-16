"""Helpers for action-safety regression assertions."""


def assert_action_error_is_specific(body: dict) -> None:
    """Fail if the API returns a bare generic Invalid request with no detail."""
    error = body.get('error')
    message = body.get('message')
    reason_code = body.get('reason_code')
    error_type = body.get('error_type')
    if error == 'Invalid request':
        assert message, (
            'Invalid request must include a specific message field; '
            f'got body={body!r}'
        )
    if error_type == 'action_not_applicable':
        assert reason_code, f'action_not_applicable missing reason_code: {body!r}'
        assert message, f'action_not_applicable missing message: {body!r}'
