"""Property-based tests for the Review Queue membership invariant.

Properties verified:
  16. Review Queue membership invariant — matches with confidence MEDIUM/LOW/UNMATCHED
      and status=pending appear in the review queue; matches with status=confirmed or
      status=rejected do not appear in the review queue regardless of confidence.

The review queue is defined as:
    HubSpotMatch.query.filter(
        HubSpotMatch.confidence.in_(['MEDIUM', 'LOW', 'UNMATCHED']),
        HubSpotMatch.status == 'pending'
    )

This test requires a Flask app context because it writes HubSpotMatch rows to the
in-memory SQLite database.  The ``app`` fixture from conftest.py provides that context.
"""
# Feature: hubspot-crm-migration, Property 16: Review queue membership invariant

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.hubspot_match import HubSpotMatch

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All valid confidence values
_CONFIDENCE_REVIEW = ['MEDIUM', 'LOW', 'UNMATCHED']
_CONFIDENCE_ALL = ['HIGH', 'MEDIUM', 'LOW', 'UNMATCHED']

_confidence_review_st = st.sampled_from(_CONFIDENCE_REVIEW)
_confidence_all_st = st.sampled_from(_CONFIDENCE_ALL)

# All valid status values
_STATUS_TERMINAL = ['confirmed', 'rejected']
_STATUS_ALL = ['pending', 'confirmed', 'rejected']

_status_terminal_st = st.sampled_from(_STATUS_TERMINAL)
_status_all_st = st.sampled_from(_STATUS_ALL)

# Record types
_record_type_st = st.sampled_from(['deal', 'contact', 'company'])

# Unique-ish hubspot IDs — use integers mapped to strings to avoid collisions
_hubspot_id_st = st.integers(min_value=1, max_value=999_999).map(lambda n: f"hs-{n}")


def _review_queue(session):
    """Return the review queue query result (list of HubSpotMatch)."""
    return session.query(HubSpotMatch).filter(
        HubSpotMatch.confidence.in_(['MEDIUM', 'LOW', 'UNMATCHED']),
        HubSpotMatch.status == 'pending',
    ).all()


def _make_match(hubspot_id: str, record_type: str, confidence: str, status: str) -> HubSpotMatch:
    """Return an unsaved HubSpotMatch with the given fields."""
    return HubSpotMatch(
        hubspot_record_type=record_type,
        hubspot_id=hubspot_id,
        confidence=confidence,
        status=status,
    )


# ---------------------------------------------------------------------------
# Property 16: Review Queue Membership Invariant
# ---------------------------------------------------------------------------


class TestReviewQueueMembershipInvariant:
    """Property 16 — review queue membership follows confidence + status rules."""

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        confidence=_confidence_review_st,
        record_type=_record_type_st,
        hubspot_id=_hubspot_id_st,
    )
    def test_pending_review_confidence_appears_in_queue(
        self, app, confidence, record_type, hubspot_id
    ):
        """Matches with MEDIUM/LOW/UNMATCHED confidence and status=pending must appear in the queue.

        **Validates: Requirements 13.1, 13.4, 13.5**
        """
        with app.app_context():
            match = _make_match(
                hubspot_id=hubspot_id,
                record_type=record_type,
                confidence=confidence,
                status='pending',
            )
            db.session.add(match)
            db.session.flush()

            queue = _review_queue(db.session)
            queue_ids = {m.id for m in queue}

            assert match.id in queue_ids, (
                f"Expected match (confidence={confidence}, status=pending) "
                f"to appear in review queue, but it was absent."
            )

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        confidence=_confidence_all_st,
        status=_status_terminal_st,
        record_type=_record_type_st,
        hubspot_id=_hubspot_id_st,
    )
    def test_terminal_status_never_appears_in_queue(
        self, app, confidence, status, record_type, hubspot_id
    ):
        """Matches with status=confirmed or status=rejected must NOT appear in the queue.

        This holds regardless of confidence level.

        **Validates: Requirements 13.1, 13.4, 13.5**
        """
        with app.app_context():
            match = _make_match(
                hubspot_id=hubspot_id,
                record_type=record_type,
                confidence=confidence,
                status=status,
            )
            db.session.add(match)
            db.session.flush()

            queue = _review_queue(db.session)
            queue_ids = {m.id for m in queue}

            assert match.id not in queue_ids, (
                f"Expected match (confidence={confidence}, status={status}) "
                f"to be absent from review queue, but it was present."
            )

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        record_type=_record_type_st,
        hubspot_id=_hubspot_id_st,
    )
    def test_high_confidence_pending_not_in_queue(
        self, app, record_type, hubspot_id
    ):
        """Matches with HIGH confidence and status=pending must NOT appear in the queue.

        HIGH confidence matches are auto-confirmed and do not require manual review.

        **Validates: Requirements 13.1, 13.4, 13.5**
        """
        with app.app_context():
            match = _make_match(
                hubspot_id=hubspot_id,
                record_type=record_type,
                confidence='HIGH',
                status='pending',
            )
            db.session.add(match)
            db.session.flush()

            queue = _review_queue(db.session)
            queue_ids = {m.id for m in queue}

            assert match.id not in queue_ids, (
                f"Expected HIGH confidence pending match to be absent from review queue, "
                f"but it was present."
            )

            db.session.rollback()

    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        confidence=_confidence_review_st,
        record_type=_record_type_st,
        hubspot_id=_hubspot_id_st,
    )
    def test_confirming_match_removes_it_from_queue(
        self, app, confidence, record_type, hubspot_id
    ):
        """After a pending match is confirmed, it must no longer appear in the queue.

        **Validates: Requirements 13.1, 13.4, 13.5**
        """
        with app.app_context():
            match = _make_match(
                hubspot_id=hubspot_id,
                record_type=record_type,
                confidence=confidence,
                status='pending',
            )
            db.session.add(match)
            db.session.flush()

            # Verify it starts in the queue
            queue_before = _review_queue(db.session)
            assert match.id in {m.id for m in queue_before}, (
                "Pre-condition failed: pending match should be in queue before confirmation."
            )

            # Confirm the match
            match.status = 'confirmed'
            db.session.flush()

            queue_after = _review_queue(db.session)
            assert match.id not in {m.id for m in queue_after}, (
                f"Expected confirmed match to be removed from review queue, "
                f"but it was still present."
            )

            db.session.rollback()

    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        confidence=_confidence_review_st,
        record_type=_record_type_st,
        hubspot_id=_hubspot_id_st,
    )
    def test_rejecting_match_removes_it_from_queue(
        self, app, confidence, record_type, hubspot_id
    ):
        """After a pending match is rejected, it must no longer appear in the queue.

        **Validates: Requirements 13.1, 13.4, 13.5**
        """
        with app.app_context():
            match = _make_match(
                hubspot_id=hubspot_id,
                record_type=record_type,
                confidence=confidence,
                status='pending',
            )
            db.session.add(match)
            db.session.flush()

            # Verify it starts in the queue
            queue_before = _review_queue(db.session)
            assert match.id in {m.id for m in queue_before}, (
                "Pre-condition failed: pending match should be in queue before rejection."
            )

            # Reject the match
            match.status = 'rejected'
            db.session.flush()

            queue_after = _review_queue(db.session)
            assert match.id not in {m.id for m in queue_after}, (
                f"Expected rejected match to be removed from review queue, "
                f"but it was still present."
            )

            db.session.rollback()

    def test_mixed_batch_queue_membership(self, app):
        """A batch of matches with mixed confidence/status produces the correct queue.

        This is a deterministic example test that verifies the queue filter
        correctly partitions a known set of records.

        **Validates: Requirements 13.1, 13.4, 13.5**
        """
        with app.app_context():
            # Records that SHOULD appear in the queue
            should_be_in = [
                _make_match('q-m1', 'deal', 'MEDIUM', 'pending'),
                _make_match('q-m2', 'contact', 'LOW', 'pending'),
                _make_match('q-m3', 'company', 'UNMATCHED', 'pending'),
            ]
            # Records that should NOT appear in the queue
            should_not_be_in = [
                _make_match('q-m4', 'deal', 'HIGH', 'pending'),       # HIGH confidence
                _make_match('q-m5', 'deal', 'MEDIUM', 'confirmed'),   # confirmed
                _make_match('q-m6', 'contact', 'LOW', 'rejected'),    # rejected
                _make_match('q-m7', 'company', 'HIGH', 'confirmed'),  # HIGH + confirmed
                _make_match('q-m8', 'deal', 'UNMATCHED', 'rejected'), # UNMATCHED but rejected
            ]

            for m in should_be_in + should_not_be_in:
                db.session.add(m)
            db.session.flush()

            queue = _review_queue(db.session)
            queue_ids = {m.id for m in queue}

            for m in should_be_in:
                assert m.id in queue_ids, (
                    f"Match (confidence={m.confidence}, status={m.status}) "
                    f"should be in queue but was absent."
                )

            for m in should_not_be_in:
                assert m.id not in queue_ids, (
                    f"Match (confidence={m.confidence}, status={m.status}) "
                    f"should NOT be in queue but was present."
                )

            db.session.rollback()
