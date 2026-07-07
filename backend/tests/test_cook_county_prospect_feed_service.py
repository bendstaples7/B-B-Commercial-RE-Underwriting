"""Tests for Cook County prospect feed address extraction, motivation gates, and feed status."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.motivation_signal import ProspectCandidate, ProspectFeedState
from app.services.cook_county_prospect_config import (
    get_prospect_min_motivation_pct,
    min_motivation_score_for_queue,
    motivation_pct,
)
from app.services.cook_county_prospect_feed_service import (
    ProspectContribution,
    _apply_pin_address,
    _external_key,
    _row_address,
    _signals_for_feed,
    _signals_to_payload,
    backfill_prospect_candidate_addresses,
    upsert_pin_stacked_candidates,
)
from app.services.motivation_signal_service import points_with_recency, recency_multiplier
from app.services.prospect_review_service import (
    approve_candidate,
    get_prospect_feed_status,
    list_candidates,
)


class TestMotivationPct:
    def test_annual_tax_sale_is_40_percent(self):
        assert motivation_pct(10.0) == 40.0

    def test_sixty_percent_threshold_raw_score(self):
        assert min_motivation_score_for_queue() == 15.0
        assert get_prospect_min_motivation_pct() == 60.0


class TestProspectOwnerConfig:
    def test_resolve_explicit_user_id(self, monkeypatch):
        from app.services.cook_county_prospect_config import resolve_cook_county_prospect_owner_user_id

        monkeypatch.setenv('COOK_COUNTY_PROSPECT_OWNER_USER_ID', 'user-abc')
        monkeypatch.delenv('COOK_COUNTY_PROSPECT_OWNER_EMAIL', raising=False)
        assert resolve_cook_county_prospect_owner_user_id() == 'user-abc'

    def test_raises_when_unconfigured(self, monkeypatch):
        from app.services.cook_county_prospect_config import resolve_cook_county_prospect_owner_user_id

        monkeypatch.delenv('COOK_COUNTY_PROSPECT_OWNER_USER_ID', raising=False)
        monkeypatch.delenv('COOK_COUNTY_PROSPECT_OWNER_EMAIL', raising=False)
        with pytest.raises(ValueError, match='COOK_COUNTY_PROSPECT_OWNER'):
            resolve_cook_county_prospect_owner_user_id()


class TestChicagoApiConfig:
    def test_placeholder_key_not_configured(self, monkeypatch):
        from app.services.cook_county_prospect_config import chicago_data_api_configured

        monkeypatch.setenv('CHICAGO_DATA_API_KEY', 'your-chicago-data-api-key')
        monkeypatch.delenv('SOCRATA_APP_TOKEN', raising=False)
        assert chicago_data_api_configured() is False

    def test_real_key_is_configured(self, monkeypatch):
        from app.services.cook_county_prospect_config import chicago_data_api_configured

        monkeypatch.setenv('CHICAGO_DATA_API_KEY', 'abc123real-token')
        assert chicago_data_api_configured() is True


class TestRowAddress:
    def test_annual_tax_sale_uses_township_not_default_city(self):
        row = {'pin': '14284000080000', 'township_name': 'Rogers Park'}
        street, city, state, township = _row_address('annual_tax_sale', row)
        assert street == ''
        assert city == ''
        assert state == 'IL'
        assert township == 'Rogers Park'

    def test_chicago_feed_defaults_city(self):
        row = {'address': '123 N MAIN ST'}
        street, city, state, township = _row_address('chicago_scofflaw', row)
        assert street == '123 N MAIN ST'
        assert city == 'Chicago'
        assert township is None


class TestApplyPinAddress:
    @patch('app.services.cook_county_prospect_feed_service._resolve_address_from_pin')
    def test_resolves_when_street_missing(self, mock_resolve):
        mock_resolve.return_value = ('2553 N DRAKE AVE', 'CHICAGO', 'IL')
        street, city, state = _apply_pin_address('14-28-400-008-0000', '', '', 'IL')
        assert street == '2553 N DRAKE AVE'
        assert city == 'CHICAGO'
        assert state == 'IL'

    @patch('app.services.cook_county_prospect_feed_service._resolve_address_from_pin')
    def test_keeps_existing_street(self, mock_resolve):
        street, city, state = _apply_pin_address('14-28-400-008-0000', '100 MAIN ST', '', 'IL')
        assert street == '100 MAIN ST'
        mock_resolve.assert_not_called()


class TestBackfillAddresses:
    @patch('app.services.cook_county_prospect_feed_service._apply_pin_address')
    def test_backfill_updates_empty_street(self, mock_apply, app, db_session):
        mock_apply.return_value = ('500 W MADISON ST', 'Chicago', 'IL')
        candidate = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street=None,
            property_city=None,
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:test-1',
            status='pending',
        )
        db_session.add(candidate)
        db_session.commit()

        summary = backfill_prospect_candidate_addresses()
        assert summary['updated'] == 1
        db_session.refresh(candidate)
        assert candidate.property_street == '500 W MADISON ST'
        assert candidate.property_city == 'Chicago'

    @patch('app.services.cook_county_prospect_feed_service._apply_pin_address')
    def test_backfill_marks_no_address_and_clears_stale_chicago(self, mock_apply, app, db_session):
        mock_apply.return_value = ('', '', 'IL')
        candidate = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street=None,
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:test-2',
            status='pending',
        )
        db_session.add(candidate)
        db_session.commit()

        summary = backfill_prospect_candidate_addresses()
        assert summary['marked_no_address'] == 1
        db_session.refresh(candidate)
        assert candidate.property_city is None
        assert candidate.status == 'rejected'
        assert candidate.rejection_reason == 'auto:no_address'


class TestMotivationRecency:
    def test_recent_violation_full_points(self):
        recent = datetime.utcnow().strftime('%Y-%m-%dT00:00:00.000')
        row = {'violation_code': 'MILD', 'violation_date': recent}
        signals = _signals_for_feed('chicago_violations', row)
        assert signals[0].points == 5.0
        assert signals[0].recency_multiplier is None

    def test_year_old_violation_seventy_five_percent(self):
        old = (datetime.utcnow() - timedelta(days=200)).strftime('%Y-%m-%dT00:00:00.000')
        row = {'violation_code': 'CN101', 'violation_date': old}
        signals = _signals_for_feed('chicago_violations', row)
        assert signals[0].points == 6.0
        assert signals[0].base_points == 8.0
        assert signals[0].recency_multiplier == 0.75

    def test_two_year_old_violation_fifty_percent(self):
        old = (datetime.utcnow() - timedelta(days=500)).strftime('%Y-%m-%dT00:00:00.000')
        adjusted, base, mult, _ = points_with_recency(
            'BUILDING_VIOLATION',
            'residential',
            {'violation_date': old},
            severe=False,
        )
        assert base == 5.0
        assert mult == 0.5
        assert adjusted == 2.5

    def test_recency_multiplier_buckets(self):
        ref = datetime(2026, 7, 1)
        assert recency_multiplier(datetime(2026, 6, 1), reference=ref) == 1.0
        assert recency_multiplier(datetime(2026, 1, 1), reference=ref) == 0.75
        assert recency_multiplier(datetime(2025, 1, 1), reference=ref) == 0.5
        assert recency_multiplier(datetime(2023, 1, 1), reference=ref) == 0.25


class TestPinStacking:
    def test_severe_chicago_violation_scores_eight_points(self):
        row = {'address': '100 MAIN ST', 'violation_id': 'V-severe', 'violation_code': 'CN101010'}
        signals = _signals_for_feed('chicago_violations', row)
        assert len(signals) == 1
        assert signals[0].points == 8.0

    def test_non_severe_chicago_violation_scores_five_points(self):
        row = {'address': '100 MAIN ST', 'violation_id': 'V-mild', 'violation_code': 'MILD'}
        signals = _signals_for_feed('chicago_violations', row)
        assert signals[0].points == 5.0

    @patch('app.services.cook_county_prospect_feed_service._apply_pin_address')
    def test_stacked_tax_sale_and_violation_meets_threshold(self, mock_apply, app, db_session):
        mock_apply.return_value = ('100 MAIN ST', 'Chicago', 'IL')
        pin = '14-28-400-008-0000'
        tax_row = {'pin': pin, 'township_name': 'Rogers Park'}
        viol_row = {'address': '100 MAIN ST', 'violation_id': 'V-1'}
        tax_signals = _signals_for_feed('annual_tax_sale', tax_row)
        viol_signals = _signals_for_feed('chicago_violations', viol_row)
        contributions = [
            ProspectContribution(
                feed='annual_tax_sale',
                row=tax_row,
                external_key=_external_key('annual_tax_sale', tax_row),
                pin=pin,
                street='',
                city='',
                state='IL',
                township_hint='Rogers Park',
                signals=tax_signals,
            ),
            ProspectContribution(
                feed='chicago_violations',
                row=viol_row,
                external_key=_external_key('chicago_violations', viol_row),
                pin=pin,
                street='100 MAIN ST',
                city='Chicago',
                state='IL',
                township_hint=None,
                signals=viol_signals,
            ),
        ]

        summary = upsert_pin_stacked_candidates(contributions, 'user-1')
        assert summary['created'] == 1
        assert summary['skipped_low_motivation'] == 0

        candidate = ProspectCandidate.query.filter_by(owner_user_id='user-1').one()
        assert candidate.source_feed == 'stacked'
        assert candidate.motivation_score == 15.0
        assert motivation_pct(candidate.motivation_score) == 60.0
        assert candidate.status == 'pending'
        assert len(candidate.signals) == 2
        assert candidate.property_street == '100 MAIN ST'

    @patch('app.services.cook_county_prospect_feed_service._apply_pin_address')
    def test_single_signal_below_threshold_not_queued(self, mock_apply, app, db_session):
        mock_apply.return_value = ('100 MAIN ST', 'Chicago', 'IL')
        pin = '14-28-400-008-0001'
        tax_row = {'pin': pin}
        contributions = [
            ProspectContribution(
                feed='annual_tax_sale',
                row=tax_row,
                external_key=_external_key('annual_tax_sale', tax_row),
                pin=pin,
                street='',
                city='',
                state='IL',
                township_hint=None,
                signals=_signals_for_feed('annual_tax_sale', tax_row),
            ),
        ]

        summary = upsert_pin_stacked_candidates(contributions, 'user-1')
        assert summary['created'] == 0
        assert summary['skipped_low_motivation'] == 1
        assert ProspectCandidate.query.filter_by(owner_user_id='user-1').count() == 0

    @patch('app.services.cook_county_prospect_feed_service._apply_pin_address')
    def test_reopens_rejected_candidate_when_stacked_score_qualifies(self, mock_apply, app, db_session):
        mock_apply.return_value = ('200 MAIN ST', 'Chicago', 'IL')
        pin = '14-28-400-008-0002'
        existing = ProspectCandidate(
            owner_user_id='user-1',
            pin=pin,
            property_street='200 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=10.0,
            signals=_signals_to_payload(_signals_for_feed('annual_tax_sale', {'pin': pin})),
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:old',
            status='rejected',
            rejection_reason='auto:below_min_motivation',
        )
        db_session.add(existing)
        db_session.commit()

        viol_row = {'address': '200 MAIN ST', 'violation_id': 'V-2'}
        contributions = [
            ProspectContribution(
                feed='annual_tax_sale',
                row={'pin': pin},
                external_key=_external_key('annual_tax_sale', {'pin': pin}),
                pin=pin,
                street='',
                city='',
                state='IL',
                township_hint=None,
                signals=_signals_for_feed('annual_tax_sale', {'pin': pin}),
            ),
            ProspectContribution(
                feed='chicago_violations',
                row=viol_row,
                external_key=_external_key('chicago_violations', viol_row),
                pin=pin,
                street='200 MAIN ST',
                city='Chicago',
                state='IL',
                township_hint=None,
                signals=_signals_for_feed('chicago_violations', viol_row),
            ),
        ]

        summary = upsert_pin_stacked_candidates(contributions, 'user-1')
        assert summary['updated'] == 1
        assert summary['reopened'] == 1
        db_session.refresh(existing)
        assert existing.status == 'pending'
        assert existing.rejection_reason is None
        assert existing.motivation_score == 15.0
        assert existing.source_feed == 'stacked'

    @patch('app.services.cook_county_prospect_feed_service._apply_pin_address')
    def test_foreclosure_plus_violation_meets_threshold(self, mock_apply, app, db_session):
        mock_apply.return_value = ('100 MAIN ST', 'Chicago', 'IL')
        pin = '14-28-400-008-0003'
        contributions = [
            ProspectContribution(
                feed='cook_county_foreclosure',
                row={'case_number': '2024CH08121', 'property_street': '100 MAIN ST', 'property_city': 'CHICAGO'},
                external_key='cook_county_foreclosure:2024CH08121',
                pin=pin,
                street='100 MAIN ST',
                city='Chicago',
                state='IL',
                township_hint=None,
                signals=_signals_for_feed('cook_county_foreclosure', {
                    'case_number': '2024CH08121',
                    'property_street': '100 MAIN ST',
                    'property_city': 'CHICAGO',
                }),
            ),
            ProspectContribution(
                feed='chicago_violations',
                row={'address': '100 MAIN ST', 'violation_id': 'V-3'},
                external_key='chicago_violations:V-3',
                pin=pin,
                street='100 MAIN ST',
                city='Chicago',
                state='IL',
                township_hint=None,
                signals=_signals_for_feed('chicago_violations', {'address': '100 MAIN ST', 'violation_id': 'V-3'}),
            ),
        ]
        summary = upsert_pin_stacked_candidates(contributions, 'user-1')
        assert summary['created'] == 1
        candidate = ProspectCandidate.query.filter_by(owner_user_id='user-1').one()
        assert candidate.motivation_score == 17.0
        assert motivation_pct(candidate.motivation_score) == 68.0

    def test_list_excludes_low_motivation_and_no_street(self, app, db_session):
        eligible = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street='100 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:eligible',
            status='pending',
        )
        low_motivation = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0001',
            property_street='200 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=10.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:low',
            status='pending',
        )
        no_street = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0002',
            property_street=None,
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:nostreet',
            status='pending',
        )
        db_session.add_all([eligible, low_motivation, no_street])
        db_session.commit()

        rows, total, _area = list_candidates('user-1', status='pending')
        assert total == 1
        assert rows[0].id == eligible.id

    def test_approve_rejects_missing_street(self, app, db_session):
        candidate = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street=None,
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:approve',
            status='pending',
        )
        db_session.add(candidate)
        db_session.commit()

        try:
            approve_candidate(candidate.id, 'user-1', reviewer_id='user-1')
            assert False, 'expected ValueError'
        except ValueError as exc:
            assert 'street address' in str(exc).lower()


class TestReconcilePending:
    def test_reconcile_marks_ineligible_pending(self, app, db_session):
        from app.services.cook_county_prospect_feed_service import reconcile_ineligible_pending_candidates

        low = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street='100 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=10.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:reconcile-low',
            status='pending',
        )
        no_street = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0001',
            property_street=None,
            property_city='Chicago',
            property_state='IL',
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='annual_tax_sale',
            external_key='annual_tax_sale:reconcile-nostreet',
            status='pending',
        )
        db_session.add_all([low, no_street])
        db_session.commit()

        summary = reconcile_ineligible_pending_candidates()
        assert summary['reconciled'] == 2
        db_session.refresh(low)
        db_session.refresh(no_street)
        assert low.status == 'rejected'
        assert low.rejection_reason == 'auto:below_min_motivation'
        assert no_street.status == 'rejected'
        assert no_street.rejection_reason == 'auto:no_address'


class TestProspectFeedStatus:
    def test_get_prospect_feed_status(self, app, db_session):
        db_session.add(ProspectFeedState(
            feed_name='annual_tax_sale',
            last_synced_at=datetime(2026, 7, 6, 18, 15, 0),
            rows_processed=49,
        ))
        db_session.add(ProspectFeedState(
            feed_name='scavenger_tax_sale',
            last_synced_at=datetime(2026, 7, 5, 4, 0, 0),
            rows_processed=10,
        ))
        db_session.commit()

        status = get_prospect_feed_status()
        assert status['last_sync_at'].startswith('2026-07-06')
        assert status['next_scheduled_label'] == '11:00 PM Central'
        assert 'chicago_api_configured' in status
        assert len(status['feeds']) == 2
        assert status['feeds'][0]['feed_name'] == 'annual_tax_sale'
