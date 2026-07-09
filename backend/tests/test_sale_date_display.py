"""Tests for consolidated Most Recent Sale display helpers."""
from datetime import date, datetime

from app.models.lead import Lead, LeadAuditTrail
from app.services.scoring_rubric import (
    display_most_recent_sale,
    humanize_sale_date_source,
    resolve_sale_date_meta,
)


def test_display_most_recent_sale_prefers_acquisition_date():
    lead = Lead(
        property_street='1 Main St',
        acquisition_date=date(2010, 6, 15),
        most_recent_sale='1/1/2000',
    )
    assert display_most_recent_sale(lead) == '06/15/2010'


def test_display_most_recent_sale_falls_back_to_import_string():
    lead = Lead(property_street='1 Main St', most_recent_sale='6/15/2010')
    assert display_most_recent_sale(lead) == '06/15/2010'


def test_display_most_recent_sale_returns_raw_when_unparseable():
    lead = Lead(property_street='1 Main St', most_recent_sale='circa 1990s')
    assert display_most_recent_sale(lead) == 'circa 1990s'


def test_humanize_sale_date_source():
    assert humanize_sale_date_source('enrichment:cook_county_assessor') == 'Cook County records'
    assert humanize_sale_date_source('import_job:42') == 'Import'
    assert humanize_sale_date_source('manual') == 'Manual'


def test_resolve_sale_date_meta_prefers_acquisition_audit(app):
    with app.app_context():
        from app import db

        lead = Lead(
            property_street='2 Main St',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
            acquisition_date=date(2015, 3, 1),
            most_recent_sale='1/1/2000',
        )
        db.session.add(lead)
        db.session.flush()

        db.session.add(LeadAuditTrail(
            lead_id=lead.id,
            field_name='most_recent_sale',
            old_value=None,
            new_value='1/1/2000',
            changed_by='import_job:1',
            changed_at=datetime(2020, 1, 1),
        ))
        db.session.add(LeadAuditTrail(
            lead_id=lead.id,
            field_name='acquisition_date',
            old_value=None,
            new_value='2015-03-01',
            changed_by='enrichment:cook_county_assessor',
            changed_at=datetime(2024, 3, 15),
        ))
        db.session.commit()

        meta = resolve_sale_date_meta(lead)
        assert meta['source'] == 'Cook County records'
        assert meta['last_updated_at'].startswith('2024-03-15')
