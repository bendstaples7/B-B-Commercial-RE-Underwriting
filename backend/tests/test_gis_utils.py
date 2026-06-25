r"""Unit tests for the shared GIS LIKE-escaping helper (``escape_like``).

Covers:
- ``%`` and ``_`` wildcards are backslash-escaped so they match literally
- the backslash escape char is itself escaped, and escaped FIRST so the
  backslash introduced when escaping ``%`` / ``_`` is not double-escaped
- ordinary address strings are returned unchanged
- an end-to-end check: an escaped value used as a LIKE prefix with
  ``ESCAPE '\'`` matches the literal text only (wildcards are inert)

These mirror the escaping the county GIS connectors rely on when building
``... LIKE '...%' ESCAPE '\\'`` WHERE clauses (dupage/kane/lake connectors).
"""
import sqlite3

import pytest

from app.services.gis.utils import escape_like


class TestEscapeLikeWildcards:
    """The wildcard characters must be neutralised with a backslash escape."""

    def test_percent_is_escaped(self):
        # A bare % becomes \% (single backslash + percent), never \\%.
        assert escape_like('100%') == r'100\%'

    def test_underscore_is_escaped(self):
        assert escape_like('A_B') == r'A\_B'

    def test_backslash_is_escaped(self):
        # One backslash -> two backslashes.
        assert escape_like('a\\b') == 'a\\\\b'

    def test_escape_char_is_escaped_first(self):
        # Escaping the escape char first means the backslash that escaping a
        # '%' introduces is NOT re-escaped: '%' -> r'\%', never r'\\%'.
        assert escape_like('%') == '\\%'
        assert escape_like('_') == '\\_'
        # A literal backslash followed by a percent: the backslash doubles,
        # then the percent is escaped -> r'\\' + r'\%' (three backslashes, %).
        assert escape_like('\\%') == '\\\\' + '\\%'

    def test_multiple_wildcards(self):
        assert escape_like('1_2%3') == r'1\_2\%3'


class TestEscapeLikeUnchanged:
    """Strings with no wildcard or escape characters pass through verbatim."""

    @pytest.mark.parametrize('value', [
        '',
        '123 N Oak Ave',
        'Main Street',
        "O'Hare",          # single-quote handling is the caller's concern
        'Apt 4',
        '50 cents',
    ])
    def test_plain_strings_unchanged(self, value):
        assert escape_like(value) == value


class TestEscapeLikeEndToEnd:
    """Prove escaped wildcards match literally via SQLite's LIKE ... ESCAPE.

    SQLite supports the same ``LIKE <pattern> ESCAPE '\'`` semantics the GIS
    connectors target, so it is a faithful, dependency-free stand-in for the
    end-to-end behaviour.
    """

    @staticmethod
    def _matches(pattern, rows):
        conn = sqlite3.connect(':memory:')
        try:
            conn.execute('CREATE TABLE t (addr TEXT)')
            conn.executemany(
                'INSERT INTO t (addr) VALUES (?)', [(r,) for r in rows]
            )
            # ESCAPE '\' mirrors the connectors' f"... ESCAPE '\\'" clause.
            cur = conn.execute(
                "SELECT addr FROM t WHERE addr LIKE ? ESCAPE '\\'", (pattern,)
            )
            return {row[0] for row in cur.fetchall()}
        finally:
            conn.close()

    def test_percent_prefix_matches_literally(self):
        # Escaped '100%' prefix matches the row with a literal '%' and does
        # NOT treat the '%' as a wildcard, so '1009 ...' is excluded.
        pattern = escape_like('100%') + '%'
        matched = self._matches(pattern, ['100% Off Plaza', '1009 Main St'])
        assert matched == {'100% Off Plaza'}

    def test_underscore_prefix_matches_literally(self):
        pattern = escape_like('A_B') + '%'
        matched = self._matches(pattern, ['A_B Road', 'AXB Road'])
        assert matched == {'A_B Road'}

    def test_plain_prefix_matches_normally(self):
        # Sanity check the harness: a prefix with nothing to escape still
        # matches by prefix (the trailing '%' is our intended wildcard).
        pattern = escape_like('123 Main') + '%'
        matched = self._matches(pattern, ['123 Main St', '999 Other Rd'])
        assert matched == {'123 Main St'}
