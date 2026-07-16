"""Unit tests for SearchService tokenization and Python scoring."""
import pytest

from app.services.search_service import (
    build_match_context,
    build_search_document_from_row,
    compute_python_relevance_score,
    lead_id_query,
    lead_id_search_text,
    phone_query_digits,
    tokenize_query,
)


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestTokenizeQuery:
    def test_ronald_j_keeps_single_letter_with_multi_token(self):
        assert tokenize_query('Ronald J') == ['Ronald', 'J']

    def test_single_char_prefix_matches_last_name(self):
        from app.services.search_service import _token_matches_text
        assert _token_matches_text('J', 'Jutkins', fuzzy=True) is True
        assert _token_matches_text('J', 'Ronald', fuzzy=True) is False

    def test_single_word_requires_min_length(self):
        assert tokenize_query('a') == []
        assert tokenize_query('ab') == ['ab']

    def test_strips_punctuation(self):
        assert tokenize_query('Ronald, Jutkins') == ['Ronald', 'Jutkins']


class TestPhoneQueryDetection:
    def test_address_number_does_not_become_phone_search(self):
        assert phone_query_digits('3208 W Wabansia') == ''

    def test_formatted_phone_query_keeps_digits(self):
        assert phone_query_digits('(312) 543-2084') == '3125432084'


class TestLeadIdQuery:
    def test_parses_exact_numeric_query(self):
        assert lead_id_query(' 11181 ') == 11181

    def test_rejects_mixed_query(self):
        assert lead_id_query('lead 11181') is None

    def test_rejects_non_decimal_unicode_digits(self):
        assert lead_id_query('²') is None
        assert lead_id_search_text('²²') is None

    def test_partial_numeric_query_is_available_for_incremental_search(self):
        assert lead_id_search_text('181') == '181'
        assert lead_id_search_text('1') is None

    def test_exact_id_gets_match_context_and_highest_boost(self):
        row = FakeRow(
            id=11181,
            owner_first_name='Owner',
            owner_last_name='Name',
            property_street='1 Main St',
            lead_score=0,
            is_warm=False,
            lead_status='skip_trace',
            matched_phone=None,
            matched_email=None,
        )
        score = compute_python_relevance_score(row, '11181', ['11181'])
        assert score >= 100
        assert build_match_context(row, '11181', '11181') == {
            'type': 'lead_id',
            'value': '11181',
        }

    def test_partial_id_gets_lead_id_match_context(self):
        row = FakeRow(id=11181, matched_phone=None, matched_email=None)
        assert build_match_context(row, '181', '') == {
            'type': 'lead_id',
            'value': '11181',
        }


class TestPostgresRelevanceSql:
    def test_normalizes_name_case_and_treats_like_wildcards_literally(self):
        from app.services.search_service import SearchService

        sql = SearchService(session=object())._relevance_score_sql()

        assert "lower(regexp_replace(trim(" in sql
        assert "strpos(" in sql
        assert "LIKE :q_normalized" not in sql


class TestBuildSearchDocument:
    def test_concatenates_fields(self):
        row = FakeRow(
            owner_first_name='Ronald',
            owner_last_name='Jutkins',
            property_street='1915 W Schiller',
            property_city='Chicago',
            property_state='IL',
            property_zip='60622',
        )
        doc = build_search_document_from_row(row)
        assert 'ronald' in doc
        assert 'jutkins' in doc
        assert 'schiller' in doc


class TestPythonMatching:
    def test_ronald_j_matches_jutkins_lead(self):
        from app.services.search_service import _token_matches_lead

        row = FakeRow(
            owner_first_name='Ronald',
            owner_last_name='Jutkins',
            property_street='1915 W Schiller',
        )
        tokens = tokenize_query('Ronald J')
        assert all(_token_matches_lead(t, row, fuzzy=True) for t in tokens)

    def test_fuzzy_typo_jutkin_matches_jutkins(self):
        from app.services.search_service import _token_matches_lead

        row = FakeRow(
            owner_first_name='Ronald',
            owner_last_name='Jutkins',
        )
        assert _token_matches_lead('Jutkin', row, fuzzy=True)

    def test_address_tokens(self):
        from app.services.search_service import _token_matches_lead

        row = FakeRow(
            owner_first_name='Ronald',
            owner_last_name='Jutkins',
            property_street='1915 W Schiller St',
            property_city='Chicago',
        )
        tokens = tokenize_query('1915 Schiller')
        assert all(_token_matches_lead(t, row, fuzzy=True) for t in tokens)


class TestPythonRelevanceScore:
    def test_score_is_non_negative(self):
        row = FakeRow(
            owner_first_name='Ronald',
            owner_last_name='Jutkins',
            property_street='1915 W Schiller',
            lead_score=50,
            is_warm=False,
            lead_status='mailing_no_contact_made',
        )
        score = compute_python_relevance_score(row, 'Ronald J', tokenize_query('Ronald J'))
        assert score >= 0

    def test_warm_lead_scores_higher(self):
        base = dict(
            owner_first_name='Ronald',
            owner_last_name='Test',
            property_street='100 Main St',
            lead_score=50,
            lead_status='mailing_no_contact_made',
        )
        cold = compute_python_relevance_score(
            FakeRow(**base, is_warm=False), 'Ronald', ['Ronald'],
        )
        warm = compute_python_relevance_score(
            FakeRow(**base, is_warm=True), 'Ronald', ['Ronald'],
        )
        assert warm > cold

    def test_exact_address_prefix_outranks_unrelated_warm_lead(self):
        query = '3208 W Wabansia'
        tokens = tokenize_query(query)
        address_match = compute_python_relevance_score(
            FakeRow(
                owner_first_name='Jess',
                owner_last_name='Martin',
                property_street='3208 W Wabansia Ave',
                lead_score=20,
                is_warm=False,
                lead_status='mailing_no_contact_made',
            ),
            query,
            tokens,
        )
        unrelated_warm = compute_python_relevance_score(
            FakeRow(
                owner_first_name='Other',
                owner_last_name='Owner',
                property_street='4144 N Southport Ave',
                lead_score=100,
                is_warm=True,
                lead_status='mailing_contacted_interested',
            ),
            query,
            tokens,
        )
        assert address_match > unrelated_warm

    def test_address_match_context_is_returned(self):
        row = FakeRow(
            property_street='3208 W Wabansia Ave',
            owner_first_name='Jess',
            owner_last_name='Martin',
            matched_phone=None,
            matched_email=None,
        )
        assert build_match_context(row, '3208 W Wabansia', '') == {
            'type': 'address',
            'value': '3208 W Wabansia Ave',
        }
