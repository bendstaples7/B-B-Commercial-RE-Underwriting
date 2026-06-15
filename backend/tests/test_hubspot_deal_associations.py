"""Tests for HubSpot deal → contact association backfill.

Covers:
- _backfill_deal_contact_associations merges new contact IDs into raw_payload
- Existing contact IDs are not duplicated
- Deals with no associations returned by the API are left unchanged
- HubSpotClientService.fetch_deal_contact_associations parses the v4 response correctly
"""
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import HubSpotDeal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_deal(hubspot_id, associations=None):
    """Insert a HubSpotDeal row and return it.  Must be called inside an app context."""
    deal = HubSpotDeal(
        hubspot_id=hubspot_id,
        raw_payload={
            "id": hubspot_id,
            "properties": {"dealname": f"Deal {hubspot_id}"},
            "associations": associations if associations is not None else {},
        },
    )
    db.session.add(deal)
    db.session.commit()
    return deal


def _make_client():
    from app.services.hubspot_client_service import HubSpotClientService
    config = MagicMock()
    config.encrypted_token = 'dummy'
    with patch.object(HubSpotClientService, '_decrypt_token', return_value='tok'):
        return HubSpotClientService(config)


# ---------------------------------------------------------------------------
# Unit tests for fetch_deal_contact_associations
# These don't need the DB — they only mock _post.
# ---------------------------------------------------------------------------

class TestFetchDealContactAssociations:

    def test_returns_contact_ids_from_v4_response(self):
        client = _make_client()
        mock_response = {
            "results": [
                {
                    "from": {"id": "111"},
                    "to": [
                        {"toObjectId": "aaa"},
                        {"toObjectId": "bbb"},
                    ],
                }
            ],
            "errors": [],
        }
        with patch.object(client, '_post', return_value=mock_response):
            result = client.fetch_deal_contact_associations(["111"])
        assert result == {"111": ["aaa", "bbb"]}

    def test_deal_with_no_contacts_maps_to_empty_list(self):
        client = _make_client()
        mock_response = {
            "results": [
                {"from": {"id": "222"}, "to": []},
            ],
            "errors": [],
        }
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

        assert len(post_calls) == 3  # 100 + 100 + 50
        assert len(post_calls[0]["inputs"]) == 100
        assert len(post_calls[1]["inputs"]) == 100
        assert len(post_calls[2]["inputs"]) == 50

    def test_missing_from_id_skipped(self):
        client = _make_client()
        mock_response = {
            "results": [
                {"from": {}, "to": [{"toObjectId": "zzz"}]},  # no 'id' key
            ],
            "errors": [],
        }
        with patch.object(client, '_post', return_value=mock_response):
            result = client.fetch_deal_contact_associations(["999"])
        assert result == {}

    def test_api_error_returns_partial_results(self):
        """A failure on one batch should not prevent results from other batches."""
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

        # Second batch succeeded → should have the result from batch 2
        assert "200" in result
        assert result["200"] == ["ccc"]


# ---------------------------------------------------------------------------
# Integration tests for _backfill_deal_contact_associations
# Use the shared `app` fixture from conftest.py (SQLite in-memory)
# ---------------------------------------------------------------------------

class TestBackfillDealContactAssociations:

    @pytest.fixture(autouse=True)
    def clean_deals(self, app):
        """Remove all HubSpotDeal rows before and after each test."""
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
        client.fetch_deal_contact_associations.return_value = {
            "deal-1": ["contact-A", "contact-B"]
        }

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_deal_contact_associations
            _backfill_deal_contact_associations(app, db, client)

            deal = HubSpotDeal.query.filter_by(hubspot_id="deal-1").first()
            results = deal.raw_payload["associations"]["contacts"]["results"]
            result_ids = {r["id"] for r in results}
            assert result_ids == {"contact-A", "contact-B"}

    def test_does_not_duplicate_existing_contact_ids(self, app):
        with app.app_context():
            _seed_deal("deal-2", associations={
                "contacts": {"results": [{"id": "contact-X", "type": "deal_to_contact"}]}
            })

        client = MagicMock()
        # HubSpot returns contact-X again plus a new contact-Y
        client.fetch_deal_contact_associations.return_value = {
            "deal-2": ["contact-X", "contact-Y"]
        }

        with app.app_context():
            from app.tasks.hubspot_tasks import _backfill_deal_contact_associations
            _backfill_deal_contact_associations(app, db, client)

            deal = HubSpotDeal.query.filter_by(hubspot_id="deal-2").first()
            results = deal.raw_payload["associations"]["contacts"]["results"]
            result_ids = [r["id"] for r in results]
            # contact-X must appear exactly once
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
