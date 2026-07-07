"""Tests for Cook County sheriff foreclosure listing parser."""
from app.services.plugins.cook_county_sheriff_foreclosure import (
    _parse_html_table,
    _parse_sale_date,
    parse_sheriff_property_address,
)


class TestSheriffForeclosureParser:
    def test_parse_address_with_two_word_city(self):
        street, city, state = parse_sheriff_property_address(
            '2900 NORTH HARLEM AVENUE  ELMWOOD PARK 60707'
        )
        assert street == '2900 NORTH HARLEM AVENUE'
        assert city == 'ELMWOOD PARK'
        assert state == 'IL'

    def test_parse_html_table_extracts_open_rows(self):
        html = """
        <table>
        <tr><th>Case</th><th>File</th><th>Address</th><th>Bid</th><th>Atty</th><th>Date</th><th>Status</th></tr>
        <tr>
          <td>2024CH08121</td><td>260015_001F</td>
          <td>1831 WEST RACE AVENUE  CHICAGO 60622</td>
          <td>Not Set</td><td>Law LLC</td><td>7/14/2026</td><td>Open</td>
        </tr>
        <tr>
          <td>2025CH08101</td><td>260021_001F</td>
          <td>6000 S HARLEM  SUMMIT 60501</td>
          <td>Not Set</td><td>Law LLC</td><td>7/17/2026</td><td>Cancelled</td>
        </tr>
        </table>
        """
        rows = _parse_html_table(html)
        assert len(rows) == 2
        assert rows[0]['case_number'] == '2024CH08121'
        assert rows[0]['property_city'] == 'CHICAGO'
        assert rows[1]['case_status'] == 'Cancelled'

    def test_parse_sale_date_unrecognized_returns_none(self):
        assert _parse_sale_date('TBD next month') is None

    def test_parse_sale_date_slash_format(self):
        assert _parse_sale_date('7/14/2026') == '2026-07-14'
