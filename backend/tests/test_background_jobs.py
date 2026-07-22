"""Tests for admin background-jobs snapshot and HubSpot pipeline stage stamps."""
from __future__ import annotations

from app.services.auth_service import AuthService


def _make_user(email: str, display_name: str, *, is_admin: bool = False):
    import uuid
    from app import db
    from app.models.user import User

    user = User(
        user_id=str(uuid.uuid4()),
        email=email,
        email_lower=email.lower(),
        password_hash='$2b$12$fakehashfakehashfakehashfakehashfakehashfakehash',
        display_name=display_name,
        is_admin=is_admin,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _auth_headers(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_pipeline_stage_round_trip(monkeypatch):
    from app.services import hubspot_pipeline_progress as prog

    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr(prog, '_redis_client', lambda: FakeRedis())
    prog.set_pipeline_stage('enrich')
    data = prog.get_pipeline_stage()
    assert data['stage'] == 'enrich'
    assert data['stage_index'] == 2
    assert data['stage_total'] == len(prog._WORK_STAGES)
    prog.clear_pipeline_stage()
    assert prog.get_pipeline_stage()['stage'] == 'idle'


def test_background_jobs_snapshot_orders_tasks(app, monkeypatch):
    from app.services import background_jobs_service as bjs

    class FakeInspect:
        def active(self):
            return {
                'worker1': [{
                    'id': 'a1',
                    'name': 'hubspot.post_import_pipeline',
                    'args': [],
                    'kwargs': {},
                    'time_start': 1.0,
                }],
            }

        def reserved(self):
            return {
                'worker1': [{
                    'id': 'r1',
                    'name': 'open_letter.submit_campaign',
                    'args': [1],
                    'kwargs': {},
                }],
            }

        def scheduled(self):
            return {}

    class FakeControl:
        def inspect(self, timeout=1.0):
            return FakeInspect()

    class FakeCelery:
        control = FakeControl()

    monkeypatch.setattr(bjs, '_peek_broker_queue', lambda limit=25: (1, [{
        'id': 'q1',
        'name': 'tasks.mark_overdue',
        'args': [],
        'kwargs': {},
        'state': 'queued',
        'worker': None,
        'time_start': None,
        'is_mail_submit': False,
        'is_hubspot_pipeline': False,
    }]))
    monkeypatch.setattr(bjs, '_mail_campaigns_in_flight', lambda celery_tasks=None, **_kw: [{
        'id': 1,
        'status': 'pending',
        'lead_count': 10,
        'olc_order_id': None,
        'created_at': None,
        'created_by': 'u1',
        'error_message': None,
        'orphan': True,
    }])
    monkeypatch.setattr(
        'app.services.hubspot_pipeline_progress.get_pipeline_stage',
        lambda: {
            'stage': 'matching',
            'stage_index': 1,
            'stage_total': 8,
            'label': 'Matching HubSpot records',
            'updated_at': None,
        },
    )

    import celery as celery_mod
    monkeypatch.setattr(celery_mod, 'current_app', FakeCelery())

    with app.app_context():
        snap = bjs.get_background_jobs_snapshot()

    assert snap['celery_inspect_ok'] is True
    assert snap['active'][0]['is_hubspot_pipeline'] is True
    assert snap['reserved'][0]['is_mail_submit'] is True
    assert snap['queued'][0]['name'] == 'tasks.mark_overdue'
    assert snap['queue_depth'] == 1
    assert snap['mail_campaigns_in_flight'][0]['id'] == 1
    assert snap['hubspot_pipeline']['stage'] == 'matching'
    assert snap['busy'] is True


def test_admin_background_jobs_forbidden_for_non_admin(client, app):
    with app.app_context():
        user = _make_user('bgjobs-user@test.com', 'BG User', is_admin=False)
        token = AuthService().issue_token(user)
    resp = client.get('/api/admin/background-jobs', headers=_auth_headers(token))
    assert resp.status_code == 403


def test_background_jobs_inspect_none_is_not_ok(app, monkeypatch):
    from app.services import background_jobs_service as bjs

    class SilentInspect:
        def active(self):
            return None

        def reserved(self):
            return None

        def scheduled(self):
            return None

    class FakeControl:
        def inspect(self, timeout=1.0):
            return SilentInspect()

    class FakeCelery:
        control = FakeControl()

    monkeypatch.setattr(bjs, '_peek_broker_queue', lambda limit=25: (0, []))
    monkeypatch.setattr(
        'app.services.hubspot_pipeline_progress.get_pipeline_stage',
        lambda: {
            'stage': 'idle',
            'stage_index': 0,
            'stage_total': 7,
            'label': 'Idle',
            'updated_at': None,
        },
    )
    import celery as celery_mod
    monkeypatch.setattr(celery_mod, 'current_app', FakeCelery())

    with app.app_context():
        snap = bjs.get_background_jobs_snapshot()

    assert snap['celery_inspect_ok'] is False


def test_mail_orphan_false_when_submit_task_active(app):
    from app.services import background_jobs_service as bjs
    from app import db
    from app.models.mail_campaign import MailCampaign

    with app.app_context():
        c = MailCampaign(status='pending', lead_count=2, created_by='u1')
        db.session.add(c)
        db.session.commit()
        cid = c.id

        with_task = bjs._mail_campaigns_in_flight(
            [{
                'is_mail_submit': True,
                'args': [cid],
                'kwargs': {},
            }],
            celery_inspect_ok=True,
        )
        assert with_task[0]['id'] == cid
        assert with_task[0]['orphan'] is False

        without_task = bjs._mail_campaigns_in_flight(
            [],
            celery_inspect_ok=True,
        )
        assert without_task[0]['orphan'] is True

        inspect_bad = bjs._mail_campaigns_in_flight(
            [],
            celery_inspect_ok=False,
        )
        assert inspect_bad[0]['orphan'] is False


def test_busy_true_when_redis_pipeline_running(app, monkeypatch):
    from app.services import background_jobs_service as bjs

    class EmptyInspect:
        def active(self):
            return {}

        def reserved(self):
            return {}

        def scheduled(self):
            return {}

    class FakeControl:
        def inspect(self, timeout=1.0):
            return EmptyInspect()

    class FakeCelery:
        control = FakeControl()

    monkeypatch.setattr(bjs, '_peek_broker_queue', lambda limit=25: (0, []))
    monkeypatch.setattr(
        'app.services.hubspot_pipeline_progress.get_pipeline_stage',
        lambda: {
            'stage': 'enrich',
            'stage_index': 2,
            'stage_total': 7,
            'label': 'Enriching leads',
            'updated_at': None,
        },
    )
    import celery as celery_mod
    monkeypatch.setattr(celery_mod, 'current_app', FakeCelery())

    with app.app_context():
        snap = bjs.get_background_jobs_snapshot()

    assert snap['busy'] is True
    assert snap['hubspot_pipeline']['pipeline_running'] is True
    assert snap['celery_inspect_ok'] is True


def test_pipeline_stage_total_excludes_done():
    from app.services import hubspot_pipeline_progress as prog

    assert 'done' in prog.PIPELINE_STAGES
    assert prog._WORK_STAGES[-1] != 'done'
    assert len(prog._WORK_STAGES) == len(prog.PIPELINE_STAGES) - 1
