"""Unit inventory validation — duplicate labels, NaN, fractional ints."""
import pytest

from app.models.lead import Lead
from app.models.lead_unit import LeadUnit
from app.services.lead_unit_service import replace_lead_units
from app import db


@pytest.fixture
def lead(app):
    with app.app_context():
        row = Lead(property_street='1 Unit Mix St')
        db.session.add(row)
        db.session.commit()
        yield row.id


class TestReplaceLeadUnitsValidation:
    def test_rejects_duplicate_labels(self, app, lead):
        with app.app_context():
            with pytest.raises(ValueError, match='Duplicate unit label'):
                replace_lead_units(lead, [
                    {'unit_label': 'Unit 1', 'unit_type': 'residential'},
                    {'unit_label': 'unit 1', 'unit_type': 'storefront'},
                ])
            assert LeadUnit.query.filter_by(lead_id=lead).count() == 0

    def test_rejects_fractional_beds(self, app, lead):
        with app.app_context():
            with pytest.raises(ValueError, match='beds/sqft must be integers'):
                replace_lead_units(lead, [
                    {'unit_label': 'A', 'beds': 1.5},
                ])

    def test_rejects_exponent_integer_text(self, app, lead):
        with app.app_context():
            with pytest.raises(ValueError, match='beds/sqft must be integers'):
                replace_lead_units(lead, [
                    {'unit_label': 'A', 'sqft': '1e100000'},
                ])

    def test_rejects_nan_baths(self, app, lead):
        with app.app_context():
            with pytest.raises(ValueError, match='baths must be a number'):
                replace_lead_units(lead, [
                    {'unit_label': 'A', 'baths': 'NaN'},
                ])

    def test_rejects_validation_error_preserves_existing_inventory(self, app, lead):
        with app.app_context():
            replace_lead_units(lead, [
                {'unit_label': 'Existing', 'unit_type': 'residential'},
            ])
            db.session.commit()

            with pytest.raises(ValueError, match='beds/sqft must be integers'):
                replace_lead_units(lead, [
                    {'unit_label': 'Bad', 'beds': 1.5},
                ])

            remaining = LeadUnit.query.filter_by(lead_id=lead).all()
            assert len(remaining) == 1
            assert remaining[0].unit_label == 'Existing'

    def test_accepts_valid_rows(self, app, lead):
        with app.app_context():
            created = replace_lead_units(lead, [
                {
                    'unit_label': 'Store',
                    'unit_type': 'storefront',
                    'current_rent': 2500,
                },
                {
                    'unit_label': '2F',
                    'unit_type': 'residential',
                    'beds': 2,
                    'baths': 1.5,
                    'sqft': 900,
                },
            ])
            db.session.commit()
            assert len(created) == 2
            assert LeadUnit.query.filter_by(lead_id=lead).count() == 2
