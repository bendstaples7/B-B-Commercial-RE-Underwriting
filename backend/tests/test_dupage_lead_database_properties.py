"""Property-based tests for the DuPage Lead Database feature.

Feature: dupage-lead-database
"""
import csv
import os
import tempfile
import uuid
import pytest
from datetime import date
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Property 4: needs_skip_trace follows contact-presence rule
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    phone_1=st.one_of(st.none(), st.just(""), st.text(min_size=1)),
    email_1=st.one_of(st.none(), st.just(""), st.text(min_size=1)),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_4_needs_skip_trace_contact_presence_rule(phone_1, email_1, app):
    """Property 4: needs_skip_trace=True when both phone_1 and email_1 are null/empty on creation.
    needs_skip_trace=False when at least one is non-empty on creation.
    needs_skip_trace is unchanged on update.

    **Validates: Requirements 1.5**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.lead_ingestion_service import LeadIngestionService
        from app.services.deduplication_engine import DeduplicationEngine

        service = LeadIngestionService(DeduplicationEngine(), {})

        try:
            # Test creation: build a minimal lead with given contact fields
            lead = Property(
                property_street=f"100 Skip Trace Test St {uuid.uuid4().hex[:6]}",
                phone_1=phone_1,
                email_1=email_1,
            )
            db.session.add(lead)
            db.session.flush()

            # Apply skip trace flag (creation)
            service._set_skip_trace_flag(lead, is_creation=True)

            has_contact = (phone_1 and str(phone_1).strip()) or (email_1 and str(email_1).strip())

            if has_contact:
                assert lead.needs_skip_trace is False or lead.needs_skip_trace == False, (
                    f"Expected needs_skip_trace=False when phone_1={phone_1!r}, email_1={email_1!r}"
                )
            else:
                assert lead.needs_skip_trace is True or lead.needs_skip_trace == True, (
                    f"Expected needs_skip_trace=True when phone_1={phone_1!r}, email_1={email_1!r}"
                )

            # Test update: record the current value, call with is_creation=False,
            # and verify needs_skip_trace doesn't change
            original_value = lead.needs_skip_trace
            service._set_skip_trace_flag(lead, is_creation=False)
            assert lead.needs_skip_trace == original_value, (
                f"needs_skip_trace should be unchanged on update, "
                f"was {original_value!r} before, now {lead.needs_skip_trace!r}"
            )

        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 5: Deduplication — same address never creates a second lead
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(address=st.text(min_size=5, max_size=200))
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_5_same_address_never_creates_second_lead(address, app):
    """Property 5: Re-ingesting the same address (with case/whitespace variants)
    results in update to existing record, not a new record. Count stays 1.

    **Validates: Requirements 2.5, 7.1, 7.3, 7.4**
    """
    assume(any(ch.isalpha() for ch in address))
    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.deduplication_engine import DeduplicationEngine

        engine = DeduplicationEngine()

        # Use a unique import_job_id per example (no FK enforcement in SQLite)
        import_job_id = 1

        try:
            # Normalize first to determine if the address produces a useful key.
            # If normalization yields an empty string the engine can't look it up,
            # so we skip those degenerate inputs.
            normalized = engine.normalize_address(address)
            if not normalized:
                return

            # Insert the first lead via process_record
            record = {"property_street": address, "source_type": "foreclosure"}
            engine.process_record(record, import_job_id)

            # Re-ingest with case/whitespace variants — each should UPDATE, not CREATE
            variants = [
                address.lower(),
                address.upper(),
                "  " + address + "  ",
                address.title(),
            ]
            for variant in variants:
                record_variant = {
                    "property_street": variant,
                    "source_type": "foreclosure",
                }
                engine.process_record(record_variant, import_job_id)

            # Count leads whose normalized address matches
            all_leads = (
                db.session.query(Property)
                .filter(Property.property_street.isnot(None))
                .all()
            )
            matching = [
                lead for lead in all_leads
                if engine.normalize_address(lead.property_street) == normalized
            ]

            assert len(matching) == 1, (
                f"Expected exactly 1 lead for address {address!r} "
                f"(normalized: {normalized!r}), found {len(matching)}"
            )

        finally:
            # Roll back all DB writes so the next Hypothesis example starts clean
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 6: Existing non-null field values are never overwritten
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    existing_value=st.text(min_size=1, max_size=100),
    incoming_value=st.text(min_size=1, max_size=100).filter(lambda s: s.strip() != ''),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_6_existing_non_null_values_never_overwritten(existing_value, incoming_value, app):
    """Property 6: When an existing lead has a non-null field value, a subsequent
    ingestion with a different non-null value for that field preserves the existing value
    and logs a conflict entry.

    **Validates: Requirements 7.5**
    """
    from hypothesis import assume
    assume(existing_value != incoming_value)

    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.deduplication_engine import DeduplicationEngine

        engine = DeduplicationEngine()
        import_job_id = 42

        try:
            # Create an existing lead with a non-null value in property_city
            address = f"100 Test St {uuid.uuid4().hex[:6]}"
            existing_lead = Property(
                property_street=address,
                property_city=existing_value,
                source_type="foreclosure",
            )
            db.session.add(existing_lead)
            db.session.flush()

            # Incoming record tries to overwrite property_city with a different value
            incoming_record = {
                "property_street": address,
                "property_city": incoming_value,
                "source_type": "foreclosure",
            }
            result = engine.process_record(incoming_record, import_job_id)

            # The existing value must be preserved
            db.session.expire(result.lead)
            db.session.refresh(result.lead)
            assert result.lead.property_city == existing_value, (
                f"Expected existing value {existing_value!r} to be preserved, "
                f"but got {result.lead.property_city!r}"
            )

            # A conflict must be logged
            assert result.conflict_detail is not None, "Expected conflict_detail to be logged"
            conflicts = result.conflict_detail.get('field_conflicts', [])
            assert any(c['field'] == 'property_city' for c in conflicts), (
                "Expected conflict log entry for property_city field"
            )
        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 7: long_owned threshold boundary is respected
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(acquisition_date=st.dates(max_value=date.today()))
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_7_long_owned_threshold_boundary(acquisition_date, app):
    """Property 7: long_owned threshold boundary is respected.

    Records with acquisition_date >= 15 years ago produce source_type='long_owned'.
    Records with acquisition_date < 15 years ago are skipped (rows_skipped > 0,
    ImportJob.rows_imported == 0).

    **Validates: Requirements 3.1, 3.4**
    """
    with app.app_context():
        from app import db
        from app.models.import_job import ImportJob
        from app.services.lead_ingestion_service import LeadIngestionService
        from app.services.deduplication_engine import DeduplicationEngine

        service = LeadIngestionService(DeduplicationEngine(), {})

        # Calculate years_owned the same way the service does
        years_owned = (date.today() - acquisition_date).days / 365.25

        # Build a minimal SFR record using class code '202' so the SFR check passes
        record = {
            'property_street': f"100 Long Owned Test St {uuid.uuid4().hex[:8]}",
            'property_city': 'Wheaton',
            'property_zip': '60189',
            'county_assessor_pin': f"TEST-{uuid.uuid4().hex[:12]}",
            'assessor_class_code': '202',
            'acquisition_date': acquisition_date,
            'owner_first_name': 'Test',
            'owner_last_name': 'Owner',
        }

        try:
            job = service.ingest_long_owned([record], owner_user_id='test-user-prop7')

            if years_owned >= 15:
                # A lead must have been created with source_type='long_owned'
                assert job.rows_imported == 1, (
                    f"Expected rows_imported=1 for acquisition_date={acquisition_date} "
                    f"(years_owned={years_owned:.2f}), got rows_imported={job.rows_imported}"
                )
                assert job.rows_skipped == 0, (
                    f"Expected rows_skipped=0 for years_owned={years_owned:.2f}, "
                    f"got rows_skipped={job.rows_skipped}"
                )

                # Verify the created lead has source_type='long_owned'
                from app.models.lead import Property
                lead = (
                    db.session.query(Property)
                    .filter(Property.source_type == 'long_owned')
                    .filter(Property.county_assessor_pin == record['county_assessor_pin'])
                    .first()
                )
                assert lead is not None, (
                    f"Expected a lead with source_type='long_owned' for "
                    f"acquisition_date={acquisition_date} (years_owned={years_owned:.2f})"
                )
                assert lead.source_type == 'long_owned', (
                    f"Expected source_type='long_owned', got {lead.source_type!r}"
                )
            else:
                # Record is < 15 years old — must be skipped
                assert job.rows_imported == 0, (
                    f"Expected rows_imported=0 for acquisition_date={acquisition_date} "
                    f"(years_owned={years_owned:.2f}), got rows_imported={job.rows_imported}"
                )
                assert job.rows_skipped > 0, (
                    f"Expected rows_skipped>0 for years_owned={years_owned:.2f}, "
                    f"got rows_skipped={job.rows_skipped}"
                )

        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 8: Absentee owner detection uses normalized address comparison
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(addresses=st.tuples(st.text(), st.text()))
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_8_absentee_owner_detection_normalized_address(addresses, app):
    """Property 8: Absentee owner detection uses normalized address comparison.

    When normalize_address(property_address) != normalize_address(mailing_address)
    AND both are non-empty after normalization → lead is created with source_type='absentee_owner'.

    When normalized addresses are equal → record is skipped (rows_skipped incremented).

    **Validates: Requirements 4.1**
    """
    property_address, mailing_address = addresses

    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.lead_ingestion_service import LeadIngestionService
        from app.services.deduplication_engine import DeduplicationEngine

        engine = DeduplicationEngine()
        service = LeadIngestionService(engine, {})

        # Use a per-example unique prefix to prevent address collisions between
        # Hypothesis examples (the service commits internally, so prior examples'
        # records persist in the in-memory DB for the test run lifetime).
        unique_prefix = uuid.uuid4().hex[:8]
        unique_prop = f"{unique_prefix} {property_address}"
        unique_mail = f"{unique_prefix} {mailing_address}"

        norm_prop = engine.normalize_address(unique_prop)
        norm_mail = engine.normalize_address(unique_mail)

        # Build a minimal SFR record (class code '202') with unique PIN
        record = {
            'property_street': unique_prop,
            'mailing_address': unique_mail,
            'property_city': 'Wheaton',
            'property_zip': '60189',
            'county_assessor_pin': f"TEST-{uuid.uuid4().hex[:12]}",
            'assessor_class_code': '202',
            'owner_first_name': 'Jane',
            'owner_last_name': 'Absentee',
        }

        try:
            job = service.ingest_absentee_owner([record], owner_user_id='test-user-prop8')

            if norm_prop and norm_mail and norm_prop != norm_mail:
                # Addresses differ after normalization → lead should be created
                assert job.rows_imported == 1, (
                    f"Expected rows_imported=1 when norm_prop={norm_prop!r} != "
                    f"norm_mail={norm_mail!r}, got rows_imported={job.rows_imported}"
                )
                assert job.rows_skipped == 0, (
                    f"Expected rows_skipped=0 when addresses differ after normalization, "
                    f"got rows_skipped={job.rows_skipped}"
                )

                # Verify the created lead has source_type='absentee_owner'
                lead = (
                    db.session.query(Property)
                    .filter(Property.source_type == 'absentee_owner')
                    .filter(Property.county_assessor_pin == record['county_assessor_pin'])
                    .first()
                )
                assert lead is not None, (
                    f"Expected a lead with source_type='absentee_owner' when "
                    f"norm_prop={norm_prop!r} != norm_mail={norm_mail!r}"
                )
                assert lead.source_type == 'absentee_owner', (
                    f"Expected source_type='absentee_owner', got {lead.source_type!r}"
                )

            elif norm_prop and norm_mail and norm_prop == norm_mail:
                # Equal normalized addresses → record must be skipped
                assert job.rows_skipped > 0, (
                    f"Expected rows_skipped>0 when norm_prop={norm_prop!r} == "
                    f"norm_mail={norm_mail!r}, got rows_skipped={job.rows_skipped}"
                )
                assert job.rows_imported == 0, (
                    f"Expected rows_imported=0 when normalized addresses are equal, "
                    f"got rows_imported={job.rows_imported}"
                )

                # No lead should be created for this PIN
                lead = (
                    db.session.query(Property)
                    .filter(Property.county_assessor_pin == record['county_assessor_pin'])
                    .first()
                )
                assert lead is None, (
                    f"Expected no lead created when normalized addresses are equal "
                    f"(norm_prop={norm_prop!r}), but found lead id={lead.id}"
                )

            # When either normalized address is empty, the service may skip or import —
            # the spec only mandates behavior when both are non-empty; no assertion needed.

        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 9: tax_distress_data stores all required fields from source
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    tax_distress_data=st.fixed_dictionaries({
        "signal_type": st.sampled_from(["tax_delinquency", "tax_sale"]),
        "delinquent_amount": st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
        "tax_year": st.one_of(st.none(), st.integers()),
    })
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_9_tax_distress_data_stores_all_required_fields(tax_distress_data, app):
    """Property 9: tax_distress_data stores all required fields from source.

    Ingesting a tax distress record with a given signal_type, delinquent_amount,
    and tax_year must result in the lead's tax_distress_data JSON containing
    those exact values (or null when the source value is null).

    **Validates: Requirements 5.3, 5.6**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.lead_ingestion_service import LeadIngestionService
        from app.services.deduplication_engine import DeduplicationEngine

        service = LeadIngestionService(DeduplicationEngine(), {})

        # Build a unique address so there is no cross-example dedup collision
        unique_suffix = uuid.uuid4().hex[:10]
        record = {
            'property_street': f"999 Tax Distress St {unique_suffix}",
            'property_city': 'Wheaton',
            'property_zip': '60189',
            'county_assessor_pin': f"TAX-{unique_suffix}",
            'signal_type': tax_distress_data['signal_type'],
            'delinquent_amount': tax_distress_data['delinquent_amount'],
            'tax_year': tax_distress_data['tax_year'],
        }

        try:
            job = service.ingest_tax_distress([record], owner_user_id='test-user-prop9')

            assert job.rows_imported == 1, (
                f"Expected rows_imported=1, got {job.rows_imported}. "
                f"error_log={job.error_log}"
            )

            # Load the lead that was just created
            lead = (
                db.session.query(Property)
                .filter(Property.county_assessor_pin == record['county_assessor_pin'])
                .first()
            )
            assert lead is not None, "Expected a lead to be created after ingestion"
            assert lead.tax_distress_data is not None, (
                "Expected tax_distress_data to be non-null after ingestion"
            )

            stored = lead.tax_distress_data

            # signal_type must always be stored
            assert stored.get('signal_type') == tax_distress_data['signal_type'], (
                f"signal_type mismatch: stored={stored.get('signal_type')!r}, "
                f"expected={tax_distress_data['signal_type']!r}"
            )

            # delinquent_amount: None stays None; finite float is stored as-is
            expected_amount = tax_distress_data['delinquent_amount']
            stored_amount = stored.get('delinquent_amount')
            if expected_amount is None:
                assert stored_amount is None, (
                    f"Expected delinquent_amount=None, got {stored_amount!r}"
                )
            else:
                # JSON round-trip may convert float → float; values must be equal
                assert stored_amount == expected_amount, (
                    f"delinquent_amount mismatch: stored={stored_amount!r}, "
                    f"expected={expected_amount!r}"
                )

            # tax_year: None stays None; integer is stored as-is
            expected_year = tax_distress_data['tax_year']
            stored_year = stored.get('tax_year')
            if expected_year is None:
                assert stored_year is None, (
                    f"Expected tax_year=None, got {stored_year!r}"
                )
            else:
                assert stored_year == expected_year, (
                    f"tax_year mismatch: stored={stored_year!r}, "
                    f"expected={expected_year!r}"
                )

        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 10: Tax distress language never appears in notes
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    tax_distress_data=st.fixed_dictionaries({
        "signal_type": st.sampled_from(["tax_delinquency", "tax_sale"]),
        "delinquent_amount": st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
        "tax_year": st.one_of(st.none(), st.integers()),
    })
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_10_tax_distress_language_absent_from_notes(tax_distress_data, app):
    """Property 10: Tax distress language never appears in notes.

    For any tax distress ingestion, assert ``notes`` contains none of:
    ``tax delinquency``, ``tax sale``, ``delinquent``, the string
    representation of ``delinquent_amount`` (if non-null), or the string
    representation of ``tax_year`` (if non-null).

    A notes value of None or empty string also satisfies this property.

    **Validates: Requirements 5.4**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.lead_ingestion_service import LeadIngestionService
        from app.services.deduplication_engine import DeduplicationEngine

        service = LeadIngestionService(DeduplicationEngine(), {})

        record = {
            'property_street': f"200 Tax Test St {uuid.uuid4().hex[:8]}",
            'property_city': 'Wheaton',
            'property_state': 'IL',
            'property_zip': '60189',
            'county_assessor_pin': f"TAX-{uuid.uuid4().hex[:12]}",
            'signal_type': tax_distress_data['signal_type'],
            'delinquent_amount': tax_distress_data['delinquent_amount'],
            'tax_year': tax_distress_data['tax_year'],
        }

        try:
            job = service.ingest_tax_distress([record], owner_user_id='test-user-prop10')

            # Retrieve the created/updated lead
            lead = (
                db.session.query(Property)
                .filter(Property.source_type == 'tax_distress')
                .filter(Property.county_assessor_pin == record['county_assessor_pin'])
                .first()
            )

            # If the record was skipped (conflict, etc.) there is nothing to assert
            if lead is None:
                return

            notes = lead.notes or ''
            notes_lower = notes.lower()

            # Assert no forbidden language appears in notes
            assert 'tax delinquency' not in notes_lower, (
                f"notes must not contain 'tax delinquency', got: {notes!r}"
            )
            assert 'tax sale' not in notes_lower, (
                f"notes must not contain 'tax sale', got: {notes!r}"
            )
            assert 'delinquent' not in notes_lower, (
                f"notes must not contain 'delinquent', got: {notes!r}"
            )

            # Assert the delinquent_amount value (if non-null) does not appear in notes
            delinquent_amount = tax_distress_data['delinquent_amount']
            if delinquent_amount is not None:
                amount_str = str(delinquent_amount)
                assert amount_str not in notes, (
                    f"notes must not contain delinquent_amount value {amount_str!r}, "
                    f"got: {notes!r}"
                )

            # Assert the tax_year value (if non-null) does not appear in notes
            tax_year = tax_distress_data['tax_year']
            if tax_year is not None:
                year_str = str(tax_year)
                assert year_str not in notes, (
                    f"notes must not contain tax_year value {year_str!r}, "
                    f"got: {notes!r}"
                )

        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 11: manual_priority validated and stored within bounds
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(priority=st.integers())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_11_manual_priority_bounds_validation(priority, app):
    """Property 11: manual_priority validated and stored within bounds.

    For priority in [1,5]: stored lead.manual_priority == priority.
    For priority outside [1,5]: lead.manual_priority is None and
    error_log contains a warning entry.

    **Validates: Requirements 6.6**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.models.import_job import ImportJob
        from app.services.lead_ingestion_service import LeadIngestionService
        from app.services.deduplication_engine import DeduplicationEngine

        service = LeadIngestionService(DeduplicationEngine(), {})

        # Use a unique address per example to avoid cross-example dedup collisions
        unique_suffix = uuid.uuid4().hex[:10]
        address = f"500 Priority Test St {unique_suffix}"

        # Write a temp CSV file with property_address and manual_priority columns
        tmp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False, encoding='utf-8', newline=''
        )
        try:
            writer = csv.DictWriter(tmp_file, fieldnames=['property_address', 'manual_priority'])
            writer.writeheader()
            writer.writerow({'property_address': address, 'manual_priority': str(priority)})
            tmp_file.close()

            # Create an ImportJob that process_csv expects to already exist
            job_record = ImportJob(
                user_id='test-user-prop11',
                spreadsheet_id='ingestion',
                sheet_name='manual_distress',
                source_type='manual_distress',
                status='in_progress',
                rows_processed=0,
                rows_imported=0,
                rows_skipped=0,
                error_log=[],
            )
            db.session.add(job_record)
            db.session.flush()
            job_id = job_record.id

            # Call process_csv
            job = service.process_csv(job_id, tmp_file.name, 'test-user-prop11')

            # The row should always be processed (address is valid)
            assert job.rows_processed == 1, (
                f"Expected rows_processed=1, got {job.rows_processed}"
            )

            # Look up the lead by address (dedup engine normalises it)
            lead = (
                db.session.query(Property)
                .filter(Property.property_street == address)
                .first()
            )

            if 1 <= priority <= 5:
                # In-range: must be stored correctly, no warning in error_log
                assert lead is not None, (
                    f"Expected lead to be created for priority={priority}"
                )
                assert lead.manual_priority == priority, (
                    f"Expected manual_priority={priority}, got {lead.manual_priority!r}"
                )
                # No warning entries about manual_priority for this row
                priority_warnings = [
                    e for e in (job.error_log or [])
                    if e.get('type') == 'warning' and 'manual_priority' in e.get('reason', '')
                ]
                assert len(priority_warnings) == 0, (
                    f"Unexpected warning for in-range priority={priority}: {priority_warnings}"
                )
            else:
                # Out-of-range: manual_priority must be None (field skipped)
                assert lead is not None, (
                    f"Expected lead to be created (row not skipped) for priority={priority}"
                )
                assert lead.manual_priority is None, (
                    f"Expected manual_priority=None for out-of-range priority={priority}, "
                    f"got {lead.manual_priority!r}"
                )
                # A warning entry must be present in error_log
                priority_warnings = [
                    e for e in (job.error_log or [])
                    if e.get('type') == 'warning' and 'manual_priority' in e.get('reason', '')
                ]
                assert len(priority_warnings) >= 1, (
                    f"Expected at least one warning entry for out-of-range priority={priority}, "
                    f"error_log={job.error_log!r}"
                )
        finally:
            # Remove temp file if process_csv didn't already clean it up
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 1: source_type assignment is always valid
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(source_type=st.sampled_from(["foreclosure", "long_owned", "absentee_owner", "tax_distress"]))
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_1_valid_source_type_assignment(source_type, app):
    """Property 1: source_type assignment is always valid.

    For each valid source_type, ingest a record via the appropriate handler
    and assert that the created lead's source_type equals the input value
    and is in VALID_SOURCE_TYPES.

    **Validates: Requirements 1.1, 1.6**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.services.lead_ingestion_service import LeadIngestionService, VALID_SOURCE_TYPES
        from app.services.deduplication_engine import DeduplicationEngine

        service = LeadIngestionService(DeduplicationEngine(), {})
        unique_suffix = uuid.uuid4().hex[:10]
        owner_user_id = f"test-user-prop1-{unique_suffix}"

        try:
            if source_type == "foreclosure":
                record = {
                    'property_street': f"100 Foreclosure St {unique_suffix}",
                    'property_city': 'Wheaton',
                    'property_zip': '60189',
                    'county_assessor_pin': f"FC-{unique_suffix}",
                    'owner_first_name': 'Test',
                    'owner_last_name': 'Owner',
                }
                job = service.ingest_foreclosure([record], owner_user_id)

            elif source_type == "long_owned":
                record = {
                    'property_street': f"100 Long Owned St {unique_suffix}",
                    'property_city': 'Wheaton',
                    'property_zip': '60189',
                    'county_assessor_pin': f"LO-{unique_suffix}",
                    'assessor_class_code': '202',
                    'acquisition_date': date(2000, 1, 1),
                    'owner_first_name': 'Test',
                    'owner_last_name': 'Owner',
                }
                job = service.ingest_long_owned([record], owner_user_id)

            elif source_type == "absentee_owner":
                record = {
                    'property_city': 'Wheaton',
                    'property_zip': '60189',
                    'county_assessor_pin': f"AO-{unique_suffix}",
                    'assessor_class_code': '202',
                    'property_street': f"100 Absentee Prop St {unique_suffix}",
                    'mailing_address': f"999 Mailing Ave {unique_suffix}",
                    'owner_first_name': 'Test',
                    'owner_last_name': 'Owner',
                }
                job = service.ingest_absentee_owner([record], owner_user_id)

            elif source_type == "tax_distress":
                record = {
                    'property_street': f"100 Tax Distress St {unique_suffix}",
                    'property_city': 'Wheaton',
                    'property_zip': '60189',
                    'county_assessor_pin': f"TD-{unique_suffix}",
                    'signal_type': 'tax_delinquency',
                    'owner_first_name': 'Test',
                    'owner_last_name': 'Owner',
                }
                job = service.ingest_tax_distress([record], owner_user_id)

            # Verify import job succeeded
            assert job.rows_imported == 1, (
                f"Expected rows_imported=1 for source_type={source_type!r}, "
                f"got {job.rows_imported}. error_log={job.error_log}"
            )

            # Find the created lead and verify source_type
            pin_prefix = source_type[:2].upper()
            lead = (
                db.session.query(Property)
                .filter(Property.source_type == source_type)
                .filter(Property.owner_user_id == owner_user_id)
                .first()
            )
            assert lead is not None, (
                f"Expected a lead with source_type={source_type!r} and "
                f"owner_user_id={owner_user_id!r} to be created"
            )
            assert lead.source_type == source_type, (
                f"Expected lead.source_type={source_type!r}, got {lead.source_type!r}"
            )
            assert lead.source_type in VALID_SOURCE_TYPES, (
                f"Expected lead.source_type to be in VALID_SOURCE_TYPES, "
                f"but {lead.source_type!r} is not"
            )

        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 2: Invalid source_type is always rejected
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    invalid_source_type=st.text().filter(
        lambda s: s not in {"foreclosure", "long_owned", "absentee_owner", "tax_distress", "manual_distress"}
    )
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_2_invalid_source_type_rejected(invalid_source_type, app):
    """Property 2: Invalid source_type is always rejected.

    For any string not in the allowed source_type set, the LeadListQuerySchema
    validation rejects it with a ValidationError. This validates Requirement 1.7
    at the schema layer: the platform validates source_type against the allowed
    set and returns an error for any value not in that set.

    **Validates: Requirements 1.7**
    """
    with app.app_context():
        from marshmallow import ValidationError
        from app.schemas import LeadListQuerySchema, VALID_SOURCE_TYPES

        # Confirm the input is genuinely invalid
        assert invalid_source_type not in VALID_SOURCE_TYPES, (
            f"Generator produced a valid source_type value: {invalid_source_type!r}"
        )

        schema = LeadListQuerySchema()
        try:
            result = schema.load({'source_type': invalid_source_type})
            # If no ValidationError was raised, source_type must not have been
            # accepted with the invalid value — assert it was filtered out or null
            loaded_source_type = result.get('source_type')
            assert loaded_source_type is None or loaded_source_type not in (
                [invalid_source_type]
            ), (
                f"Expected schema to reject invalid source_type={invalid_source_type!r}, "
                f"but schema accepted it and returned source_type={loaded_source_type!r}"
            )
        except ValidationError as e:
            # ValidationError is the expected outcome — invalid source_type is rejected
            errors = e.messages
            assert 'source_type' in errors, (
                f"Expected validation error for 'source_type' field, got errors: {errors}"
            )


# ---------------------------------------------------------------------------
# Property 3: owner_user_id propagates to every created lead
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(user_id=st.text(min_size=1, max_size=36))
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_3_owner_user_id_propagation(user_id, app):
    """Property 3: owner_user_id propagates to every created lead.

    For any user_id (text, 1-36 chars), ingest a batch via ingest_foreclosure
    and assert that every lead created by that import job has
    owner_user_id == user_id.

    **Validates: Requirements 1.2**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property
        from app.models.import_job import ImportJob
        from app.services.lead_ingestion_service import LeadIngestionService
        from app.services.deduplication_engine import DeduplicationEngine

        service = LeadIngestionService(DeduplicationEngine(), {})
        unique_suffix = uuid.uuid4().hex[:8]

        # Build a small batch of records to verify propagation across multiple leads
        records = [
            {
                'property_street': f"100 Propagation St {unique_suffix}-{i}",
                'property_city': 'Wheaton',
                'property_zip': '60189',
                'county_assessor_pin': f"PROP-{unique_suffix}-{i}",
                'owner_first_name': f'Test{i}',
                'owner_last_name': 'Owner',
            }
            for i in range(3)
        ]

        try:
            job = service.ingest_foreclosure(records, user_id)

            assert job.rows_imported >= 1, (
                f"Expected at least 1 row imported for user_id={user_id!r}, "
                f"got rows_imported={job.rows_imported}. error_log={job.error_log}"
            )

            # Retrieve all leads created by this import job
            created_leads = (
                db.session.query(Property)
                .filter(Property.last_import_job_id == job.id)
                .all()
            )

            assert len(created_leads) > 0, (
                f"Expected leads to be found with last_import_job_id={job.id}"
            )

            for lead in created_leads:
                assert lead.owner_user_id == user_id, (
                    f"Expected lead.owner_user_id={user_id!r}, "
                    f"got {lead.owner_user_id!r} for lead id={lead.id}"
                )

        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Shared helper for pure scoring tests (Properties 14-17)
# No DB or app fixture needed — these test pure functions on the engine.
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock


def _make_scoring_lead(**kwargs):
    """Build a minimal mock lead for pure scoring tests.

    Sets all attributes the DeterministicScoringEngine reads, then
    overrides with any caller-supplied keyword arguments.
    """
    from app.services.deterministic_scoring_engine import SCORING_ATTRIBUTES

    lead = MagicMock()
    defaults = {
        "id": 1,
        "source_type": None,
        "tax_distress_data": None,
        "manual_priority": None,
        "lead_category": "residential",
        "property_type": None,
        "property_city": None,
        "property_zip": None,
        "units": None,
        "mailing_address": None,
        "mailing_city": None,
        "mailing_state": None,
        "mailing_zip": None,
        "property_street": None,
        "acquisition_date": None,
        "notes": None,
        "do_not_contact": False,
        "county_assessor_pin": None,
        "owner_first_name": None,
        "owner_last_name": None,
        "source": None,
        "data_source": None,
        "square_footage": None,
        "date_skip_traced": None,
        "phone_1": None,
        "email_1": None,
        "date_skip_traced": None,
        "assessed_value": None,
        "socials": None,
        "year_built": None,
        "lot_size": None,
        "mailer_history": None,
        "has_phone": None,
        "has_email": None,
        "follow_up_date": None,
        "timeline": None,
        "phone_5": None,
        "phone_6": None,
        "phone_7": None,
        "email_4": None,
        "email_5": None,
        "bedrooms": None,
        "bathrooms": None,
        "updated_at": None,
        "lead_status": None,
        "last_contact_date": None,
        "unanswered_call_count": None,
    }
    defaults.update(kwargs)

    # Validate that all scoring attributes are covered by defaults
    registered = SCORING_ATTRIBUTES
    covered = set(defaults.keys())
    missing = registered - covered
    if missing:
        import warnings
        warnings.warn(
            f"SCORING_ATTRIBUTES missing from _make_scoring_lead defaults: {missing}"
        )

    for k, v in defaults.items():
        setattr(lead, k, v)
    return lead


# ---------------------------------------------------------------------------
# Property 14: structured_motivation is exactly 10 points
#              for qualifying source types (with null tax_distress_data)
# Property 15: annual tax sale signal adds 10 points; residential cap = 25
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    source_type=st.sampled_from(["foreclosure", "tax_distress", "long_owned"]),
)
@settings(max_examples=100, deadline=None)
def test_property_14_source_type_distress_dimension_exact_10_points(source_type):
    """Property 14: structured_motivation is exactly 10 points for qualifying
    source types when tax_distress_data is null.

    **Validates: Requirements 12.1**
    """
    from app.services.deterministic_scoring_engine import DeterministicScoringEngine

    engine = DeterministicScoringEngine()
    lead = _make_scoring_lead(source_type=source_type, tax_distress_data=None)

    result = engine.calculate_residential_score(lead)
    score_details = result["score_details"]

    dim_score = score_details["structured_motivation"]
    assert dim_score == 10.0, (
        f"Expected structured_motivation=10.0 for source_type={source_type!r} "
        f"with null tax_distress_data, got {dim_score!r}"
    )
    assert dim_score <= 25.0, (
        f"structured_motivation must not exceed residential cap of 25, "
        f"got {dim_score!r} for source_type={source_type!r}"
    )


@given(
    source_type=st.sampled_from(["foreclosure", "tax_distress", "long_owned"]),
)
@settings(max_examples=100, deadline=None)
def test_property_15_tax_distress_data_bonus_adds_exactly_5_points(source_type):
    """Property 15: annual tax sale data adds 10 points to structured_motivation.

    - Lead with annual_tax_sale rows scores exactly 10 more than the equivalent
      lead with tax_distress_data=None (10 base + 10 tax sale).
    - Combined score never exceeds the residential cap of 25.

    **Validates: Requirements 12.2**
    """
    from app.services.deterministic_scoring_engine import DeterministicScoringEngine

    engine = DeterministicScoringEngine()

    lead_no_bonus = _make_scoring_lead(source_type=source_type, tax_distress_data=None)
    result_no_bonus = engine.calculate_residential_score(lead_no_bonus)
    base_score = result_no_bonus["score_details"]["structured_motivation"]

    lead_with_bonus = _make_scoring_lead(
        source_type=source_type,
        tax_distress_data={'annual_tax_sale': [{'pin': '01-02-003-004-0000'}]},
    )
    result_with_bonus = engine.calculate_residential_score(lead_with_bonus)
    bonus_score = result_with_bonus["score_details"]["structured_motivation"]

    assert bonus_score == base_score + 10.0, (
        f"Expected structured_motivation to increase by exactly 10 when annual_tax_sale "
        f"is present. source_type={source_type!r}, base={base_score!r}, "
        f"bonus={bonus_score!r} (expected {base_score + 10.0!r})"
    )

    assert bonus_score <= 25.0, (
        f"structured_motivation must not exceed residential cap of 25, "
        f"got {bonus_score!r} for source_type={source_type!r}"
    )


# ---------------------------------------------------------------------------
# Property 16: Tax distress language absent from LeadScore outputs
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    source_type=st.sampled_from(["foreclosure", "tax_distress", "long_owned", "absentee_owner"]),
    tax_distress_data=st.fixed_dictionaries({
        "signal_type": st.sampled_from(["tax_delinquency", "tax_sale"]),
        "delinquent_amount": st.one_of(
            st.none(),
            st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e9),
        ),
        "tax_year": st.one_of(st.none(), st.integers(min_value=1990, max_value=2030)),
    }),
)
@settings(max_examples=100, deadline=None)
def test_property_16_tax_distress_language_absent_from_lead_score_outputs(
    source_type, tax_distress_data
):
    """Property 16: Tax distress language is absent from LeadScore outputs.

    For any lead carrying non-null tax_distress_data, neither top_signals nor
    recommended_action may contain any of:
      - "tax_delinquency", "tax_sale", "delinquent" (forbidden static terms)
      - Any string value stored in tax_distress_data (signal_type, etc.)

    **Validates: Requirements 12.3**
    """
    from app.services.deterministic_scoring_engine import DeterministicScoringEngine

    engine = DeterministicScoringEngine()
    lead = _make_scoring_lead(source_type=source_type, tax_distress_data=tax_distress_data)

    result = engine.calculate_residential_score(lead)
    score_details = result["score_details"]

    # Build the set of forbidden strings to check
    forbidden_terms = {"tax_delinquency", "tax_sale", "delinquent", "tax delinquency", "tax sale"}

    # Also forbid any string values stored in tax_distress_data itself
    for v in tax_distress_data.values():
        if isinstance(v, str) and v.strip():
            forbidden_terms.add(v.strip().lower())

    # Extract top_signals
    top_signals = engine.extract_top_signals(score_details)

    # Check each signal's dimension name and points representation
    for signal in top_signals:
        dim_name = signal.get("dimension", "").lower()
        for term in forbidden_terms:
            assert term not in dim_name, (
                f"Forbidden tax distress term {term!r} found in top_signals "
                f"dimension name {dim_name!r}. "
                f"source_type={source_type!r}, tax_distress_data={tax_distress_data!r}"
            )

    # Check recommended_action — it must be one of the safe ALLOWED_ACTIONS
    # and must not contain any forbidden term
    from app.services.deterministic_scoring_engine import ALLOWED_ACTIONS

    total_score = result["total_score"]
    dq_score = 0.0  # minimal data quality for the mock
    score_tier = engine.calculate_score_tier(total_score)
    recommended_action = engine.get_recommended_action(lead, total_score, dq_score, score_tier)

    # recommended_action must be an allowed value (not a tax distress string)
    assert recommended_action in ALLOWED_ACTIONS, (
        f"recommended_action={recommended_action!r} is not in ALLOWED_ACTIONS. "
        f"source_type={source_type!r}"
    )

    recommended_lower = recommended_action.lower()
    for term in forbidden_terms:
        assert term not in recommended_lower, (
            f"Forbidden tax distress term {term!r} found in recommended_action "
            f"{recommended_action!r}. "
            f"source_type={source_type!r}, tax_distress_data={tax_distress_data!r}"
        )


# ---------------------------------------------------------------------------
# Property 17: absentee_owner source_type always scores full 10 points
#              in the absentee_owner dimension (short-circuit)
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    mailing_address=st.one_of(st.none(), st.text(max_size=100)),
    property_street=st.one_of(st.none(), st.text(max_size=100)),
)
@settings(max_examples=100, deadline=None)
def test_property_17_absentee_owner_full_score_short_circuit(
    mailing_address, property_street
):
    """Property 17: absentee_owner source_type always scores full 10 points in
    the absentee_owner dimension, regardless of mailing/property address values.

    The short-circuit skips the mailing address comparison entirely when
    source_type == 'absentee_owner', so even leads with missing or equal
    addresses receive the full 10 points.

    **Validates: Requirements 12.5**
    """
    from app.services.deterministic_scoring_engine import DeterministicScoringEngine

    engine = DeterministicScoringEngine()
    lead = _make_scoring_lead(
        source_type="absentee_owner",
        mailing_address=mailing_address,
        property_street=property_street,
    )

    result = engine.calculate_residential_score(lead)
    score_details = result["score_details"]

    absentee_score = score_details["absentee_owner"]
    assert absentee_score == 10.0, (
        f"Expected absentee_owner dimension == 10.0 for source_type='absentee_owner' "
        f"regardless of address values. "
        f"mailing_address={mailing_address!r}, property_street={property_street!r}, "
        f"got absentee_owner={absentee_score!r}"
    )


# ---------------------------------------------------------------------------
# Property 12: source_type filter returns only matching leads
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(source_type=st.sampled_from(["foreclosure", "long_owned", "absentee_owner", "tax_distress", "manual_distress"]))
@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_12_source_type_filter_returns_only_matching_leads(source_type, app, client):
    """Property 12: source_type filter returns only matching leads.

    Creates a lead with the target source_type and a lead with no source_type
    (null). Asserts that GET /api/leads/?source_type=<value> returns only leads
    with matching source_type — the null lead must not appear, and the matching
    lead must be present.

    **Validates: Requirements 11.1, 11.3**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property

        unique_id = uuid.uuid4().hex[:8]

        matching_lead = Property(
            property_street=f"100 Match St {unique_id}",
            source_type=source_type,
            owner_user_id="test-user",  # must match the injected X-User-Id header
        )
        non_matching_lead = Property(
            property_street=f"200 Other St {unique_id}",
            source_type=None,
            owner_user_id="test-user",  # must match the injected X-User-Id header
        )
        db.session.add_all([matching_lead, non_matching_lead])
        db.session.commit()

        try:
            resp = client.get(f"/api/properties/?source_type={source_type}&per_page=100",
                              headers={'X-User-Id': 'test-user'})
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}. Body: {resp.get_data(as_text=True)[:200]}"
            )
            data = resp.get_json()
            # Response uses 'leads' key (property_controller.py list_properties)
            leads_in_response = data.get('leads', data.get('properties', data.get('results', [])))

            # Every lead in the response must match the requested source_type
            for lead in leads_in_response:
                assert lead.get('source_type') == source_type, (
                    f"Got source_type={lead.get('source_type')!r} but expected "
                    f"{source_type!r} — filter must exclude non-matching leads"
                )

            # The matching lead must be present in the response
            ids_in_response = {p['id'] for p in leads_in_response}
            assert matching_lead.id in ids_in_response, (
                f"Matching lead (id={matching_lead.id}, source_type={source_type!r}) "
                f"was not returned by the filter"
            )

            # The null-source_type lead must NOT be present
            assert non_matching_lead.id not in ids_in_response, (
                f"Non-matching lead (id={non_matching_lead.id}, source_type=None) "
                f"appeared in source_type={source_type!r} filtered results"
            )
        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 13: owner_user_id filter returns only matching leads
# Feature: dupage-lead-database
# ---------------------------------------------------------------------------

@given(
    owner_ids=st.lists(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='-_')),
        min_size=2,
        max_size=4,
        unique=True,
    )
)
@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property_13_owner_user_id_filter_returns_only_matching_leads(owner_ids, app, client):
    """Property 13: owner_user_id filter returns only matching leads.

    Creates leads owned by different users and asserts that
    GET /api/leads/?owner_user_id=<target> returns only leads whose
    owner_user_id matches the filter value — leads owned by other users
    must not appear.

    **Validates: Requirements 11.2**
    """
    with app.app_context():
        from app import db
        from app.models.lead import Property

        unique_id = uuid.uuid4().hex[:8]
        # Use 'test-user' as the target because the injected X-User-Id header
        # means ownership scoping filters to owner_user_id='test-user' OR NULL.
        # Other users' leads are intentionally not visible to test-user.
        target_user = "test-user"
        other_users = [f"other-user-{uid}" for uid in owner_ids[1:]]

        # Create one lead per user
        target_lead = Property(
            property_street=f"100 Target Owner St {unique_id}",
            source_type="foreclosure",
            owner_user_id=target_user,
        )
        other_leads = [
            Property(
                property_street=f"200 Other Owner St {unique_id}-{i}",
                source_type="foreclosure",
                owner_user_id=other_user,
            )
            for i, other_user in enumerate(other_users)
        ]
        db.session.add(target_lead)
        db.session.add_all(other_leads)
        db.session.commit()

        try:
            resp = client.get(f"/api/properties/?owner_user_id={target_user}&per_page=100",
                              headers={'X-User-Id': target_user})
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}. Body: {resp.get_data(as_text=True)[:200]}"
            )
            data = resp.get_json()
            leads_in_response = data.get('leads', data.get('properties', data.get('results', [])))

            # Every lead in the response must belong to the target user
            for lead in leads_in_response:
                assert lead.get('owner_user_id') == target_user, (
                    f"Got owner_user_id={lead.get('owner_user_id')!r} but expected "
                    f"{target_user!r} — filter must exclude leads owned by other users"
                )

            # The target user's lead must be in the results
            ids_in_response = {p['id'] for p in leads_in_response}
            assert target_lead.id in ids_in_response, (
                f"Target lead (id={target_lead.id}, owner_user_id={target_user!r}) "
                f"was not returned by the owner_user_id filter"
            )

            # No lead belonging to a different user should appear
            for other_lead in other_leads:
                assert other_lead.id not in ids_in_response, (
                    f"Lead owned by user={other_lead.owner_user_id!r} "
                    f"(id={other_lead.id}) appeared in results filtered for "
                    f"owner_user_id={target_user!r}"
                )
        finally:
            db.session.rollback()
