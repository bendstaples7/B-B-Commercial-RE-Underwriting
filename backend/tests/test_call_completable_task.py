"""Tests for call-completable task matching."""
from app.utils.call_completable_task import (
    find_call_completable_task,
    is_call_completable_task,
    is_mail_or_email_outreach_task,
    is_superseded_by_mail_task,
)


def test_call_owner_today_always_matches():
    assert is_call_completable_task('call_owner_today', 'Anything') is True
    assert is_superseded_by_mail_task('call_owner_today', 'Anything') is True


def test_research_task_not_superseded_by_mail():
    assert is_superseded_by_mail_task('research_missing_pin', 'Find PIN') is False


def test_mail_batch_never_matches():
    assert is_call_completable_task('add_to_mail_batch', 'Add to mail') is False


def test_email_title_never_matches_custom():
    assert is_call_completable_task('custom', 'Email outreach to owner') is False
    assert is_call_completable_task('custom', 'Send mail letter') is False


def test_send_only_title_not_excluded():
    """'send' alone should not classify a task as mail/email outreach."""
    assert is_mail_or_email_outreach_task('custom', 'Send contract to owner') is False
    assert is_mail_or_email_outreach_task('custom', 'Send mail letter') is True
    found = find_call_completable_task([{
        'id': 1,
        'task_type': 'custom',
        'title': 'Send contract to owner',
        'status': 'open',
        'source': 'native',
    }])
    assert found is not None
    assert found['id'] == 1


def test_call_title_custom_matches():
    assert is_call_completable_task('custom', 'Call owner back') is True
    assert is_call_completable_task('custom', 'Phone follow-up') is True


def test_follow_up_title_matches():
    assert is_call_completable_task('custom', 'Follow up on 1726 W Roscoe St') is True
    assert is_call_completable_task('custom', 'Follow-up with owner') is True


def test_non_call_builtin_never_matches():
    assert is_call_completable_task('research_missing_pin', 'Call for PIN') is False


def test_find_single_follow_up_task():
    tasks = [{
        'id': 1,
        'task_type': 'custom',
        'title': 'Mobile (555) 123-4567',
        'status': 'open',
        'source': 'native',
    }]
    found = find_call_completable_task(tasks)
    assert found is not None
    assert found['id'] == 1


def test_find_hubspot_follow_up_task():
    tasks = [{
        'id': 'hs-99',
        'task_type': 'custom',
        'title': 'Follow up on 1726 W Roscoe St',
        'status': 'overdue',
        'source': 'hubspot',
    }]
    found = find_call_completable_task(tasks)
    assert found is not None
    assert found['id'] == 'hs-99'


def test_llc_search_not_call_completable_or_sole_fallback():
    assert is_call_completable_task('custom', 'LLC Search') is False
    assert is_call_completable_task('custom', 'LLC search') is False
    found = find_call_completable_task([{
        'id': 5616,
        'task_type': 'custom',
        'title': 'LLC Search',
        'status': 'open',
        'source': 'hubspot',
    }])
    assert found is None
