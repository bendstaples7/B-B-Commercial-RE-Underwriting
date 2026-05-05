"""Property-based test for CSV export completeness.

Property 8: CSV Export Completeness
Generate AddressGroupAnalysis records with linked leads, export CSV, verify
all required columns present and multi-valued fields contain all values
from linked leads.

Validates: Requirements 12.1, 12.3
"""
import csv
import io
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.lead import Lead
from app.models.address_group_analysis import AddressGroupAnalysis
from app.services.condo_filter_service import CondoFilterService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating a non-empty alphanumeric string (for PINs, names, etc.)
_alpha_str = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters=' '),
    min_size=1,
    max_size=30,
).map(str.strip).filter(lambda s: len(s) > 0)

# Strategy for generating a street address
_street_address = st.builds(
    lambda num, name: f'{num} {name} St',
    st.integers(min_value=1, max_value=9999),
    _alpha_str,
)

# Strategy for generating a single lead-like dict
_lead_strategy = st.fixed_dictionaries({
    'property_street': _street_address,
    'county_assessor_pin': st.one_of(st.none(), _alpha_str),
    'owner_first_name': st.one_of(st.none(), _alpha_str),
    'owner_last_name': st.one_of(st.none(), _alpha_str),
    'owner_2_first_name': st.one_of(st.none(), _alpha_str),
    'owner_2_last_name': st.one_of(st.none(), _alpha_str),
    'mailing_address': st.one_of(st.none(), _street_address),
})

# Strategy for generating a group of leads (1-5 leads per group)
_leads_group = st.lists(_lead_strategy, min_size=1, max_size=5)


# Required CSV columns per the design
REQUIRED_COLUMNS = [
    'normalized_address',
    'representative_property_address',
    'pin_count',
    'owner_count',
    'condo_risk_status',
    'building_sale_possible',
    'owner_names',
    'mailing_addresses',
    'property_ids',
    'pins',
    'reason',
    'confidence',
]


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------

# Feature: commercial-condo-filter, Property 8: CSV Export Completeness

class TestCsvExportCompleteness:
    """Property 8: CSV Export Completeness.

    **Validates: Requirements 12.1, 12.3**
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(leads_data=_leads_group)
    def test_csv_contains_all_required_columns_and_linked_data(self, app, leads_data):
        """For any set of AddressGroupAnalysis records with linked leads,
        the CSV export produces rows with all required columns and multi-valued
        fields contain all values from linked leads.

        **Validates: Requirements 12.1, 12.3**
        """
        with app.app_context():
            # Clean up from previous iteration
            db.session.rollback()
            Lead.query.delete()
            AddressGroupAnalysis.query.delete()
            db.session.commit()

            # Create an analysis record
            analysis = AddressGroupAnalysis(
                normalized_address='test property address',
                source_type='commercial',
                property_count=len(leads_data),
                pin_count=len(set(
                    ld['county_assessor_pin'] for ld in leads_data
                    if ld['county_assessor_pin']
                )),
                owner_count=1,
                has_unit_number=False,
                has_condo_language=False,
                missing_pin_count=0,
                missing_owner_count=0,
                condo_risk_status='likely_not_condo',
                building_sale_possible='yes',
                analysis_details={
                    'triggered_rules': ['rule_4_single_pin_owner'],
                    'reason': 'Test reason',
                    'confidence': 'high',
                },
            )
            db.session.add(analysis)
            db.session.flush()

            # Create linked leads
            created_leads = []
            for i, ld in enumerate(leads_data):
                lead = Lead(
                    property_street=f"{ld['property_street']} {i}",
                    property_type='commercial',
                    lead_category='commercial',
                    county_assessor_pin=ld['county_assessor_pin'],
                    owner_first_name=ld['owner_first_name'],
                    owner_last_name=ld['owner_last_name'],
                    owner_2_first_name=ld['owner_2_first_name'],
                    owner_2_last_name=ld['owner_2_last_name'],
                    mailing_address=ld['mailing_address'],
                    mailing_city='Chicago',
                    mailing_state='IL',
                    mailing_zip='60601',
                    condo_analysis_id=analysis.id,
                )
                db.session.add(lead)
                created_leads.append(lead)

            db.session.commit()

            # Export CSV
            service = CondoFilterService()
            csv_content = service.export_csv(filters={})

            # Parse CSV
            reader = csv.DictReader(io.StringIO(csv_content))
            rows = list(reader)

            # Property: All required columns are present
            assert reader.fieldnames is not None
            for col in REQUIRED_COLUMNS:
                assert col in reader.fieldnames, f"Missing required column: {col}"

            # Property: At least one data row exists
            assert len(rows) >= 1

            row = rows[0]

            # Property: Multi-valued fields contain all values from linked leads
            # Check PINs
            expected_pins = [
                ld['county_assessor_pin'] for ld in leads_data
                if ld['county_assessor_pin']
            ]
            if expected_pins:
                csv_pins = row['pins']
                for pin in expected_pins:
                    assert pin in csv_pins, f"PIN '{pin}' not found in CSV pins field"

            # Check mailing addresses
            expected_mailing = [
                ld['mailing_address'] for ld in leads_data
                if ld['mailing_address']
            ]
            if expected_mailing:
                csv_mailing = row['mailing_addresses']
                for addr in expected_mailing:
                    assert addr in csv_mailing, (
                        f"Mailing address '{addr}' not found in CSV mailing_addresses field"
                    )

            # Check property_ids - all lead IDs should be present
            csv_ids = row['property_ids']
            for lead in created_leads:
                assert str(lead.id) in csv_ids, (
                    f"Lead ID {lead.id} not found in CSV property_ids field"
                )

            # Clean up
            db.session.rollback()
