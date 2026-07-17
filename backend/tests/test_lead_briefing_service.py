"""Unit tests for LeadBriefingService (create/revise + quality guards)."""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.exceptions import GeminiConfigurationError, GeminiParseError, GeminiResponseError
from app.services.lead_briefing_service import LeadBriefingService


def _make_lead(app):
    from app import db
    from app.models import Lead, LeadTask, LeadTimelineEntry

    lead = Lead(
        property_street='2553 N Drake',
        property_city='Chicago',
        property_state='IL',
        owner_first_name='Gilberto',
        owner_last_name='Olivares',
        lead_status='negotiating_remote',
        recommended_action='call_ready',
        lead_score=90.0,
        is_warm=True,
        has_phone=True,
        has_email=True,
        has_property_match=True,
        analysis_complete=True,
        data_completeness_score=60.0,
        owner_user_id='test-user',
    )
    db.session.add(lead)
    db.session.flush()
    db.session.add(LeadTask(
        lead_id=lead.id,
        title='Follow up with Gilberto',
        status='open',
        task_type='custom',
    ))
    db.session.add(LeadTimelineEntry(
        lead_id=lead.id,
        event_type='hubspot_call',
        occurred_at=datetime.now(timezone.utc),
        source='hubspot',
        actor='HubSpot',
        summary='Call with Gilberto Olivares — No answer',
    ))
    db.session.commit()
    return lead


def _five_bullets():
    return [
        'Last contact was today with a no-answer call.',
        'Next step is to catch him live and set a walkthrough.',
        'He previously floated numbers near mid-600s for the building.',
        'Voicemail has been full before, so try alternate numbers.',
        'He works a warehouse shift and may call back after hours.',
    ]


def test_init_requires_api_key(monkeypatch):
    monkeypatch.delenv('GOOGLE_AI_API_KEY', raising=False)
    with pytest.raises(GeminiConfigurationError):
        LeadBriefingService()


def test_parse_bullets_rejects_incomplete_sentence():
    svc = LeadBriefingService(api_key='test-key')
    raw = json.dumps({
        'bullets': [
            'Complete sentence one.',
            'He previously received an offer of $670K, which he was',
            'about, but it was not a deal breaker.',
            'Complete sentence three.',
            'Complete sentence four.',
            'Complete sentence five.',
            'Extra complete filler sentence for padding.',
        ]
    })
    bullets = [b for b in svc._parse_bullets(raw) if b]
    assert all(svc._is_complete_bullet(b) for b in bullets)
    assert not any(b.endswith('was') for b in bullets)
    assert not any(b.lower().startswith('about') for b in bullets)


def test_parse_bullets_strips_slot_labels():
    svc = LeadBriefingService(api_key='test-key')
    raw = json.dumps({
        'bullets': [
            'LAST CONTACT — Called yesterday with no answer.',
            'NEXT ACTION — Schedule a walkthrough after the offer chat.',
            'DEAL FACTS — Prior talk floated roughly $670K on the building.',
            'OBJECTIONS / SOFT SPOTS — Voicemail has been full before.',
            'PEOPLE / LOGISTICS — Warehouse shifts make daytime calls harder.',
        ]
    })
    bullets = svc._parse_bullets(raw)
    assert len([b for b in bullets if b]) == 5
    assert not any(b and 'LAST CONTACT' in b.upper() for b in bullets)
    assert bullets[0].startswith('Called yesterday')


def test_parse_keeps_complete_sentence_instead_of_hard_slice():
    svc = LeadBriefingService(api_key='test-key')
    long = (
        'He previously floated a purchase price of roughly six hundred seventy thousand dollars '
        'for the whole multi-unit building on the near west side and said the number itself '
        'was not a deal breaker at all for him personally.'
    )
    assert len(long) > 180
    bullets = [b for b in svc._parse_bullets(json.dumps({'bullets': [long] + _five_bullets()[1:]})) if b]
    assert bullets
    assert all(svc._is_complete_bullet(b) for b in bullets)
    assert all(len(b) <= 180 for b in bullets)
    assert not any(b.endswith(('was', 'the', 'a', 'and')) for b in bullets)


def test_rejects_open_task_page_echo():
    svc = LeadBriefingService(api_key='test-key')
    context = {
        'owner_first_name': 'Gilberto',
        'owner_last_name': 'Olivares',
        'open_tasks': [
            {'title': 'Follow up with Gilberto Olivares', 'due_date': '2026-06-30'},
        ],
    }
    echo = 'There is an open task to follow up with Gilberto Olivares, due June 30, 2026.'
    assert svc._is_page_echo(echo, context) is True
    echo2 = 'You should call Gilberto to follow up on the open task from June 30, 2026.'
    assert svc._is_page_echo(echo2, context) is True
    good = 'Ask if a weekend walkthrough works and confirm interest near the mid-600s.'
    assert svc._is_page_echo(good, context) is False
    # Full name alone in a useful contact note is allowed
    contact_note = 'Left a voicemail for Gilberto Olivares about scheduling a walkthrough.'
    assert svc._is_page_echo(contact_note, context) is False
    filtered = svc._filter_usable_bullets([echo, echo2, good], context)
    assert filtered[0] is None
    assert filtered[1] is None
    assert filtered[2] == good
    assert [b for b in filtered if b] == [good]


def test_abbreviation_not_treated_as_multi_sentence():
    svc = LeadBriefingService(api_key='test-key')
    assert svc._is_complete_bullet(
        'Spoke with Mr. Smith on St. Clair Ave. about pricing.'
    ) is True
    assert svc._is_complete_bullet(
        'Called yesterday. Ask about walkthrough next.'
    ) is False
    svc = LeadBriefingService(api_key='test-key')
    long = 'Word ' * 50
    truncated = svc._truncate_at_word(long, 40)
    assert len(truncated) <= 40
    assert not truncated.endswith(' ')


def test_is_complete_bullet_allows_the_a_an_starts():
    svc = LeadBriefingService(api_key='test-key')
    assert svc._is_complete_bullet(
        'The last HubSpot call was April 27 and left a voicemail.'
    ) is True
    assert svc._is_complete_bullet(
        'A showing was set for Sunday afternoon after the connected call.'
    ) is True
    assert svc._is_complete_bullet(
        'An evening callback is more likely to catch her live.'
    ) is True


def test_build_context_uses_metadata_body_when_summary_empty(app):
    with app.app_context():
        from app import db
        from app.models import Lead, LeadTimelineEntry

        lead = Lead(
            property_street='100 Main',
            property_city='Chicago',
            property_state='IL',
            owner_first_name='Linda',
            owner_last_name='Bobert',
            lead_status='in_person_appointment',
            recommended_action='call_ready',
            owner_user_id='test-user',
        )
        db.session.add(lead)
        db.session.flush()
        db.session.add(LeadTimelineEntry(
            lead_id=lead.id,
            event_type='hubspot_call',
            occurred_at=datetime(2026, 5, 31, 19, 56, 55, tzinfo=timezone.utc),
            source='hubspot',
            actor='HubSpot',
            summary='',
            event_metadata={
                'body': 'Connected, setup a showing for Sunday at 3:30',
                'disposition': 'Connected',
            },
        ))
        db.session.commit()

        svc = LeadBriefingService(api_key='test-key')
        ctx = svc._build_context(lead)
        assert ctx['last_activity_summary']
        assert 'showing' in ctx['last_activity_summary'].lower()
        assert any(
            'showing' in (row.get('summary') or '').lower()
            for row in ctx['recent_activity']
        )


def test_ensure_five_uses_context_not_generic_fillers():
    svc = LeadBriefingService(api_key='test-key')
    context = {
        'last_activity_at': '2026-04-27T19:44:50+00:00',
        'days_since_last_activity': 80,
        'last_activity_summary': 'Left voicemail after HubSpot call',
        'recent_activity': [
            {
                'event_type': 'hubspot_call',
                'summary': 'Connected, setup a showing for Sunday at 3:30',
            },
        ],
        'open_tasks': [],
    }
    filled = svc._ensure_five([None, None, None, None, None], context=context)
    assert len(filled) == 5
    assert 'unclear from the log' not in filled[0].lower()
    assert 'walkthrough useful' not in filled[1].lower()
    assert 'voicemail' in filled[0].lower() or 'outreach' in filled[0].lower()
    assert 'showing' in filled[1].lower() or 'walkthrough' in filled[1].lower()


def test_parse_bullets_pads_via_ensure_five():
    svc = LeadBriefingService(api_key='test-key')
    cleaned = svc._ensure_five(['Only one complete sentence here.'])
    assert len(cleaned) == 5


def test_parse_bullets_rejects_invalid_json():
    svc = LeadBriefingService(api_key='test-key')
    with pytest.raises(GeminiParseError):
        svc._parse_bullets('not-json')


def test_generate_persists_and_creates(app, monkeypatch):
    monkeypatch.setenv('GOOGLE_AI_API_KEY', 'test-key')
    with app.app_context():
        from app.models import Lead
        lead = _make_lead(app)
        svc = LeadBriefingService()
        fake = json.dumps({'bullets': _five_bullets()})
        with patch.object(svc, '_call_gemini_api', return_value=fake) as mocked:
            result = svc.generate(lead.id, persist=True)

        mocked.assert_called_once()
        assert result['mode'] == 'create'
        assert len(result['bullets']) == 5
        refreshed = Lead.query.get(lead.id)
        assert refreshed.quick_briefing is not None
        assert refreshed.quick_briefing['bullets'] == result['bullets']
        assert refreshed.quick_briefing['mode'] == 'create'


def test_generate_revises_from_previous(app, monkeypatch):
    monkeypatch.setenv('GOOGLE_AI_API_KEY', 'test-key')
    with app.app_context():
        from app.models import Lead
        lead = _make_lead(app)
        lead.quick_briefing = {
            'bullets': _five_bullets(),
            'generated_at': '2026-07-01T12:00:00+00:00',
            'updated_at': '2026-07-01T12:00:00+00:00',
            'mode': 'create',
        }
        from app import db
        db.session.add(lead)
        db.session.commit()

        svc = LeadBriefingService()
        revised = [
            'Last contact was yesterday with a callback promise.',
            'Next action is schedule a property walkthrough after the $670K offer.',
            'He nearly sold two years ago around $680K per an agent.',
            'He was lukewarm but not opposed to the recent offer level.',
            'Union warehouse schedule suggests evening outreach works better.',
        ]
        with patch.object(svc, '_call_gemini_api', return_value=json.dumps({'bullets': revised})) as mocked:
            result = svc.generate(lead.id, persist=True)

        assert result['mode'] == 'revise'
        prompt = mocked.call_args[0][0]
        assert 'PREVIOUS BULLETS' in prompt or 'REVISING' in prompt or 'revising' in prompt.lower()
        assert 'Follow up with Gilberto' in prompt or 'open_tasks' in prompt
        refreshed = Lead.query.get(lead.id)
        assert refreshed.quick_briefing['mode'] == 'revise'
        assert refreshed.quick_briefing['generated_at'] == '2026-07-01T12:00:00+00:00'


def test_briefing_endpoint_persists(client, app, monkeypatch):
    monkeypatch.setenv('GOOGLE_AI_API_KEY', 'test-key')
    with app.app_context():
        lead = _make_lead(app)
        lead_id = lead.id

    fake = {
        'lead_id': lead_id,
        'bullets': _five_bullets(),
        'generated_at': '2026-07-14T12:00:00+00:00',
        'updated_at': '2026-07-14T12:00:00+00:00',
        'timeline_entries_used': 1,
        'open_tasks_used': 1,
        'mode': 'create',
    }
    with patch(
        'app.services.lead_briefing_service.LeadBriefingService.generate',
        return_value=fake,
    ):
        resp = client.post(
            f'/api/leads/{lead_id}/briefing',
            headers={'X-User-Id': 'test-user'},
        )

    assert resp.status_code == 200
    assert resp.get_json()['bullets'] == fake['bullets']


def test_command_center_includes_quick_briefing(client, app):
    with app.app_context():
        lead = _make_lead(app)
        lead.quick_briefing = {
            'bullets': _five_bullets(),
            'generated_at': '2026-07-14T12:00:00+00:00',
            'mode': 'create',
        }
        from app import db
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

    # Patch outreach resolve — full CC path uses Postgres ANY() not available on SQLite.
    with patch(
        'app.controllers.command_center_controller.resolve_outreach_contact',
        return_value=None,
    ):
        resp = client.get(
            f'/api/leads/{lead_id}/command-center',
            headers={'X-User-Id': 'test-user'},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['quick_briefing']['bullets'][0].startswith('Last contact')
