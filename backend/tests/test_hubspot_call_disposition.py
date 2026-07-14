"""Tests for HubSpot call disposition GUID mapping."""
from app.services.helpers.hubspot_call_disposition import (
    format_hubspot_call_summary,
    is_connected_disposition,
    looks_like_uuid,
    resolve_call_disposition_label,
)


def test_resolve_no_answer_guid():
    assert resolve_call_disposition_label(
        '73a0d17f-1163-4015-bdd5-ec830791da20'
    ) == 'No answer'


def test_resolve_connected_guid():
    assert resolve_call_disposition_label(
        'f240bbac-87c9-4f6e-bf70-924b57d47db7'
    ) == 'Connected'
    assert is_connected_disposition('f240bbac-87c9-4f6e-bf70-924b57d47db7') is True


def test_format_prefers_body_over_disposition():
    summary = format_hubspot_call_summary(
        body='Left a voicemail.',
        disposition='b2cf5968-551e-4856-9783-52b3da59a7d0',
        title='Call with Owner',
    )
    assert summary == 'Left a voicemail.'


def test_format_maps_guid_with_title():
    summary = format_hubspot_call_summary(
        body='73a0d17f-1163-4015-bdd5-ec830791da20',
        disposition='73a0d17f-1163-4015-bdd5-ec830791da20',
        title='Call with Gilberto Olivares',
    )
    assert summary == 'Call with Gilberto Olivares — No answer'
    assert not looks_like_uuid(summary)


def test_not_connected_is_not_connected_disposition():
    assert is_connected_disposition('Not connected') is False
    assert is_connected_disposition('Disconnected') is False
    assert is_connected_disposition('answered') is True
