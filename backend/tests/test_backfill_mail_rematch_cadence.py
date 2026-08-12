"""Tests for the mail rematch cadence backfill script."""
from datetime import date, timedelta
import sys

from app import db
from app.models.lead import Lead
from app.models.lead_task import LeadTask


def _make_lead(street: str, *, lead_status: str = 'mailing_no_contact_made') -> Lead:
    lead = Lead(
        property_street=street,
        property_city='Chicago',
        property_state='IL',
        property_zip='60601',
        lead_status=lead_status,
        lead_score=50,
        source_type='import',
    )
    db.session.add(lead)
    db.session.flush()
    return lead


def _make_task(
    lead: Lead,
    *,
    title: str,
    task_type: str,
    due_date=None,
    **kwargs,
) -> LeadTask:
    task = LeadTask(
        lead_id=lead.id,
        task_type=task_type,
        title=title,
        status='open',
        due_date=due_date,
        created_by='test',
        **kwargs,
    )
    db.session.add(task)
    db.session.flush()
    return task


def test_limit_filters_converted_rematches_before_limiting(app):
    """Already-converted rematches should not consume a limited backfill batch."""
    from scripts.backfill_mail_rematch_cadence import (
        _find_open_legacy_or_call_rematch_tasks,
    )

    with app.app_context():
        lead = _make_lead('1 Limit Rematch St')
        for idx in range(3):
            _make_task(
                lead,
                task_type='add_to_mail_batch',
                title=f'Add to next mailer - converted {idx}',
            )
        first_legacy = _make_task(
            lead,
            task_type='call_owner_today',
            title='Follow up after mailer - first legacy',
        )
        second_legacy = _make_task(
            lead,
            task_type='call_owner_today',
            title='Follow up after mailer - second legacy',
        )
        db.session.commit()

        tasks = _find_open_legacy_or_call_rematch_tasks(limit=2)

        assert [task.id for task in tasks] == [first_legacy.id, second_legacy.id]


def test_candidate_query_excludes_hubspot_backed_tasks(app):
    """Backfill leaves HubSpot-backed rows for explicit CRM-aware handling."""
    from scripts.backfill_mail_rematch_cadence import (
        _find_open_legacy_or_call_rematch_tasks,
    )

    with app.app_context():
        lead = _make_lead('1 HubSpot Rematch St')
        _make_task(
            lead,
            task_type='call_owner_today',
            title='Follow up after mailer - hubspot',
            hubspot_task_id='hs-rematch-1',
        )
        local = _make_task(
            lead,
            task_type='call_owner_today',
            title='Follow up after mailer - local',
        )
        db.session.commit()

        tasks = _find_open_legacy_or_call_rematch_tasks(limit=None)

        assert [task.id for task in tasks] == [local.id]


def test_dry_run_skips_conversion_without_last_sent(app, monkeypatch, capsys):
    """A legacy task without send history must not keep its old due date as rematch."""
    import scripts.backfill_mail_rematch_cadence as script

    with app.app_context():
        lead = _make_lead('2 No Send Rematch St')
        _make_task(
            lead,
            task_type='call_owner_today',
            title='Follow up after mailer - no send',
            due_date=date.today() - timedelta(days=30),
        )
        db.session.commit()

    monkeypatch.setattr(script, 'create_app', lambda: app)
    monkeypatch.setattr(script, 'get_last_mailed_at_by_lead_ids', lambda _ids: {})
    monkeypatch.setattr(sys, 'argv', ['backfill_mail_rematch_cadence.py'])

    script.main()

    output = capsys.readouterr().out
    assert 'skip (no send)' in output
    assert 'Dry-run: would convert=0 would cancel=0 skipped=1' in output
