"""Tests for HubSpot deal↔contact association backfill and import health check.

Covers:
- _backfill_deal_contact_associations merges new contact IDs into raw_payload
- _backfill_contact_deal_associations merges new deal IDs into raw_payload
- Existing IDs are not duplicated in either direction
- Records with no associations returned by the API are left unchanged
- _check_association_health marks the import run partial when >90% empty
- HubSpotClientService.fetch_deal_contact_associations /
  fetch_contact_deal_associations parse the v4 response correctly and batch at 100
"""
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import HubSpotDeal, HubSpotContact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_deal(hubspot_id, associations=None, run_id=None):
    deal = HubSpotDeal(
        hubspot_id=hubspot_id,
        import_run_id=run_id,
        raw_payload={
            "id": hubspot_id,
            "properties": {"dealname": f"Deal {hubspot_id}"},
            "associations": associations if associations is not None else {},
        },
    )
    db.session.add(deal)
    db.session.commit()
    return deal


def _seed_contact(hubspot_id, associations=None, run_id=None):
    contact = HubSpotContact(
        hubspot_id=hubspot_id,
        import_run_id=run_id,
        raw_payload={
            "id": hubspot_id,
            "properties": {"firstname": "Test", "lastname": hubspot_id},
            "associations": associations if associations is not None else {},
        },
    )
    db.session.add(contact)
    db.session.commit()
    return contact


def _make_client():
    from app.services.hubspot_client_service import HubSpotClientService
    config = MagicMock()
    config.encrypted_token = 'dummy'
    with patch.object(HubSpotClientService, '_decrypt_token', return_value='tok'):
        return HubSpotClientService(config)


# ---------------------------------------------------------------------------
# Unit tests for fetch_deal_contact_associations /
#                fetch_contact_deal_associations
# ---------------------------------------------------------------------------

class TestFetchAssociations:

    def test_returns_contact_ids_from_v4_response(self):
        client = _make_client()
        mock_response = {
            "results": [
                {
                    "from": {"id": "111"},
                    "to": [{"toObjectId": "aaa"}, {"toObjectId": "bbb"}],
                }
            ],
            "errors": [],
        }
        with patch.object(client, '_post', return_value=mock_response):
            result = client.fetch_deal_contact_associations(["111"])
        assert result == {"111": ["aaa", "bbb"]}

    def test_fetch_contact_deal_uses_correct_path(self):
        client = _make_client()
        captured = {}

        def fake_post(path, body):
            captured['path'] = path
            return {"results": [], "errors": []}

        with patch.object(client, '_post', side_effect=fake_post):
            client.fetch_contact_deal_associations(["c1"])

        assert 'contacts/deals' in captured['path']

    def test_deal_with_no_contacts_maps_to_empty_list(self):
        client = _make_client()
        mock_response = {"results": [{"from": {"id": "222"}, "to": []}], "errors": []}
        with patch.object(client, '_post', return_value=mock_response):
            result = client.fetch_deal_contact_associations(["222"])
        assert result == {"222": []}

    def test_batches_requests_at_100(self):
        client = _make_client()
        post_calls = []

        def fake_post(path, body):
            post_calls.append(body)
            return {"results": [], "errors": []}

        deal_ids = [str(i) for i in range(250)]
        with patch.object(client, '_post', side_effect=fake_post):
            client.fetch_deal_contact_associations(deal_ids)

        assert len(post_calls) == 3
        assert len(post_calls[0]["inputs"]) == 100
        assert len(post_calls[1]["inputs"]) == 100
        assert len(post_calls[2]["inputs"]) == 50

    def test_missing_from_id_skipped(self):
        client = _make_client()
        mock_response = {
            "results": [{"from": {}, "to": [{"toObjectId": "zzz"}]}],
            "errors": [],
        }
        with patch.object(client, '_post', return_value=mock_response):
            result = client.fetch_deal_contact_associations(["999"])
        assert result == {}

    def test_api_error_returns_partial_results(self):
        from app.exceptions import ExternalServiceError
        client = _make_client()
        call_count = [0]

        def fake_post(path, body):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ExternalServiceError("network error")
            return {
                "results": [{"from": {"id": "200"}, "to": [{"toObjectId": "ccc"}]}],
                "errors": [],
            }

        deal_ids = [str(i) for i in range(150)]
        with patch.object(client, '_post', side_effect=fake_post):
            result = client.fetch_deal_contact_associations(deal_ids)

        assert "200" in result
        assert result["200"] == ["ccc"]


# ---------------------------------------------------------------------------
# Integration tests for _backfill_deal_contact_associations
# ---------------------------------------------------------------------------

class TestBackfillDealContactAssociations:

    @pytest.fixture(autouse=True)
    def clean_deals(self, app):
        with app.app_context():
            HubSpotDeal.query.delete()
            db.session.commit()
        yield
        with app.app_context():
            HubSpotDeal.query.delete()
            db.session.commit()

    def test_merges_contact_ids_into_raw_payload(self, app):
        with app.app_context():
            _seed_deal("deal-1")

        client = MagicMock()
        client.fetch_deal_contact_associations.return_value = {"deal-1": ["contact-A", "contact-B"]}

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_deal_contact_associations
            _backfill_deal_contact_associations(app, db, client)
            deal = HubSpotDeal.query.filter_by(hubspot_id="deal-1").first()
            result_ids = {r["id"] for r in deal.raw_payload["associations"]["contacts"]["results"]}
            assert result_ids == {"contact-A", "contact-B"}

    def test_does_not_duplicate_existing_contact_ids(self, app):
        with app.app_context():
            _seed_deal("deal-2", associations={
                "contacts": {"results": [{"id": "contact-X", "type": "deal_to_contact"}]}
            })

        client = MagicMock()
        client.fetch_deal_contact_associations.return_value = {"deal-2": ["contact-X", "contact-Y"]}

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_deal_contact_associations
            _backfill_deal_contact_associations(app, db, client)
            deal = HubSpotDeal.query.filter_by(hubspot_id="deal-2").first()
            result_ids = [r["id"] for r in deal.raw_payload["associations"]["contacts"]["results"]]
            assert result_ids.count("contact-X") == 1
            assert "contact-Y" in result_ids

    def test_deal_with_no_associations_returned_unchanged(self, app):
        with app.app_context():
            _seed_deal("deal-3")

        client = MagicMock()
        client.fetch_deal_contact_associations.return_value = {"deal-3": []}

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_deal_contact_associations
            _backfill_deal_contact_associations(app, db, client)
            deal = HubSpotDeal.query.filter_by(hubspot_id="deal-3").first()
            assert deal.raw_payload.get("associations") == {}

    def test_deal_not_in_api_response_unchanged(self, app):
        with app.app_context():
            _seed_deal("deal-4")

        client = MagicMock()
        client.fetch_deal_contact_associations.return_value = {}

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_deal_contact_associations
            _backfill_deal_contact_associations(app, db, client)
            deal = HubSpotDeal.query.filter_by(hubspot_id="deal-4").first()
            assert deal.raw_payload.get("associations") == {}


# ---------------------------------------------------------------------------
# Integration tests for _backfill_contact_deal_associations
# ---------------------------------------------------------------------------

class TestBackfillContactDealAssociations:

    @pytest.fixture(autouse=True)
    def clean_contacts(self, app):
        with app.app_context():
            HubSpotContact.query.delete()
            db.session.commit()
        yield
        with app.app_context():
            HubSpotContact.query.delete()
            db.session.commit()

    def test_merges_deal_ids_into_raw_payload(self, app):
        with app.app_context():
            _seed_contact("contact-1")

        client = MagicMock()
        client.fetch_contact_deal_associations.return_value = {"contact-1": ["deal-A", "deal-B"]}

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_contact_deal_associations
            _backfill_contact_deal_associations(app, db, client)
            contact = HubSpotContact.query.filter_by(hubspot_id="contact-1").first()
            result_ids = {r["id"] for r in contact.raw_payload["associations"]["deals"]["results"]}
            assert result_ids == {"deal-A", "deal-B"}

    def test_does_not_duplicate_existing_deal_ids(self, app):
        with app.app_context():
            _seed_contact("contact-2", associations={
                "deals": {"results": [{"id": "deal-X", "type": "contact_to_deal"}]}
            })

        client = MagicMock()
        client.fetch_contact_deal_associations.return_value = {"contact-2": ["deal-X", "deal-Y"]}

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_contact_deal_associations
            _backfill_contact_deal_associations(app, db, client)
            contact = HubSpotContact.query.filter_by(hubspot_id="contact-2").first()
            result_ids = [r["id"] for r in contact.raw_payload["associations"]["deals"]["results"]]
            assert result_ids.count("deal-X") == 1
            assert "deal-Y" in result_ids

    def test_contact_with_no_associations_returned_unchanged(self, app):
        with app.app_context():
            _seed_contact("contact-3")

        client = MagicMock()
        client.fetch_contact_deal_associations.return_value = {"contact-3": []}

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_contact_deal_associations
            _backfill_contact_deal_associations(app, db, client)
            contact = HubSpotContact.query.filter_by(hubspot_id="contact-3").first()
            assert contact.raw_payload.get("associations") == {}


# ---------------------------------------------------------------------------
# Integration tests for _check_association_health
# ---------------------------------------------------------------------------

class TestCheckAssociationHealth:

    @pytest.fixture(autouse=True)
    def clean_all(self, app):
        with app.app_context():
            HubSpotDeal.query.delete()
            HubSpotContact.query.delete()
            from app.models import HubSpotImportRun
            HubSpotImportRun.query.delete()
            db.session.commit()
        yield
        with app.app_context():
            HubSpotDeal.query.delete()
            HubSpotContact.query.delete()
            from app.models import HubSpotImportRun
            HubSpotImportRun.query.delete()
            db.session.commit()

    def _make_run(self, app, status='success'):
        from app.models import HubSpotImportRun
        with app.app_context():
            run = HubSpotImportRun(object_type='deals', status=status, total_fetched=10, created_count=10)
            db.session.add(run)
            db.session.commit()
            return run.id

    def test_marks_run_partial_when_all_empty(self, app):
        """All 10 deals have empty associations → run is marked partial."""
        run_id = self._make_run(app)
        with app.app_context():
            for i in range(10):
                _seed_deal(f"deal-h-{i}", run_id=run_id)
            from app.tasks.hubspot_tasks import _check_association_health
            _check_association_health(db, 'deals', run_id)
            from app.models import HubSpotImportRun
            run = HubSpotImportRun.query.get(run_id)
            assert run.status == 'partial'
            assert run.error_message is not None

    def test_does_not_mark_partial_when_enough_populated(self, app):
        """If >10% of deals have associations, run stays success."""
        run_id = self._make_run(app)
        with app.app_context():
            for i in range(8):
                _seed_deal(f"deal-empty-{i}", run_id=run_id)
            _seed_deal("deal-pop-1", associations={"contacts": {"results": [{"id": "c1"}]}}, run_id=run_id)
            _seed_deal("deal-pop-2", associations={"contacts": {"results": [{"id": "c2"}]}}, run_id=run_id)
            from app.tasks.hubspot_tasks import _check_association_health
            _check_association_health(db, 'deals', run_id)
            from app.models import HubSpotImportRun
            run = HubSpotImportRun.query.get(run_id)
            assert run.status == 'success'

    def test_contacts_branch_marks_partial_when_all_empty(self, app):
        """All 10 contacts have empty deal associations → run is marked partial."""
        from app.models import HubSpotImportRun
        with app.app_context():
            run = HubSpotImportRun(object_type='contacts', status='success', total_fetched=10, created_count=10)
            db.session.add(run)
            db.session.commit()
            run_id = run.id

        with app.app_context():
            for i in range(10):
                _seed_contact(f"contact-h-{i}", run_id=run_id)
            from app.tasks.hubspot_tasks import _check_association_health
            _check_association_health(db, 'contacts', run_id)
            from app.models import HubSpotImportRun
            run = HubSpotImportRun.query.get(run_id)
            assert run.status == 'partial'
            assert run.error_message is not None

    def test_contacts_branch_stays_success_when_enough_populated(self, app):
        """If >10% of contacts have deal associations, run stays success."""
        from app.models import HubSpotImportRun
        with app.app_context():
            run = HubSpotImportRun(object_type='contacts', status='success', total_fetched=10, created_count=10)
            db.session.add(run)
            db.session.commit()
            run_id = run.id

        with app.app_context():
            for i in range(8):
                _seed_contact(f"contact-empty-{i}", run_id=run_id)
            _seed_contact("contact-pop-1", associations={"deals": {"results": [{"id": "d1"}]}}, run_id=run_id)
            _seed_contact("contact-pop-2", associations={"deals": {"results": [{"id": "d2"}]}}, run_id=run_id)
            from app.tasks.hubspot_tasks import _check_association_health
            _check_association_health(db, 'contacts', run_id)
            from app.models import HubSpotImportRun
            run = HubSpotImportRun.query.get(run_id)
            assert run.status == 'success'
