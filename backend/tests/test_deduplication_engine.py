"""Unit tests for DeduplicationEngine — Task 5.5.

Covers:
- Address normalization with concrete examples
- find_existing_lead: None when empty DB, address match, PIN match, no match
- merge_lead: null incoming → no change, non-null over null → update,
  non-null over non-null (different) → preserve + conflict logged,
  last_import_job_id always updated, outcome 'updated' vs 'conflict'
- process_record: new address → 'created', existing address → 'updated'/'conflict',
  PIN mismatch → 'conflict' with conflict_detail['type'] == 'pin_mismatch'

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
"""
import pytest
from app.services.deduplication_engine import DeduplicationEngine
from app import db
from app.models.lead import Property


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(property_street, pin=None, owner_first_name=None,
               owner_last_name=None, notes=None, import_job_id=None):
    """Insert and flush a minimal Property record; return the instance."""
    lead = Property(
        property_street=property_street,
        county_assessor_pin=pin,
        owner_first_name=owner_first_name,
        owner_last_name=owner_last_name,
        notes=notes,
        last_import_job_id=import_job_id,
        lead_category="residential",
    )
    db.session.add(lead)
    db.session.flush()
    return lead


# ---------------------------------------------------------------------------
# Address normalization — no DB needed
# ---------------------------------------------------------------------------

class TestNormalizeAddress:
    """DeduplicationEngine.normalize_address — concrete transformation examples."""

    def setup_method(self):
        self.engine = DeduplicationEngine()

    def test_trailing_period_stripped(self):
        assert self.engine.normalize_address("123 Main St.") == "123 MAIN ST"

    def test_extra_leading_trailing_spaces_collapsed(self):
        assert self.engine.normalize_address("  123  main  st  ") == "123 MAIN ST"

    def test_already_normalized_is_idempotent(self):
        assert self.engine.normalize_address("123 MAIN ST") == "123 MAIN ST"

    def test_apostrophe_stripped(self):
        """o'brien → OBRIEN (apostrophe is punctuation, gets stripped)."""
        assert self.engine.normalize_address("o'brien ave") == "OBRIEN AVE"

    def test_comma_and_hash_stripped(self):
        """unit #4, 123 Main → UNIT 4 123 MAIN (comma and # stripped)."""
        assert self.engine.normalize_address("unit #4, 123 Main") == "UNIT 4 123 MAIN"

    def test_mixed_case_to_uppercase(self):
        assert self.engine.normalize_address("123 main st") == "123 MAIN ST"
        assert self.engine.normalize_address("123 MAIN ST") == "123 MAIN ST"
        assert self.engine.normalize_address("123 Main St") == "123 MAIN ST"

    def test_multiple_internal_spaces_collapsed(self):
        assert self.engine.normalize_address("123   Main    St") == "123 MAIN ST"

    def test_all_punctuation_stripped(self):
        """Verify a string with many punctuation types is cleaned."""
        result = self.engine.normalize_address("123 Main-St., Apt. #4 (IL)")
        # All punctuation chars stripped, spaces collapsed
        assert "-" not in result
        assert "." not in result
        assert "#" not in result
        assert "(" not in result
        assert ")" not in result
        assert "," not in result

    def test_normalization_is_case_insensitive(self):
        """Lower, upper, and title case all produce the same output."""
        lower = self.engine.normalize_address("456 oak avenue")
        upper = self.engine.normalize_address("456 OAK AVENUE")
        title = self.engine.normalize_address("456 Oak Avenue")
        assert lower == upper == title

    def test_empty_string_returns_empty(self):
        assert self.engine.normalize_address("") == ""

    def test_whitespace_only_returns_empty(self):
        assert self.engine.normalize_address("   ") == ""


# ---------------------------------------------------------------------------
# find_existing_lead — requires DB via app fixture
# ---------------------------------------------------------------------------

class TestFindExistingLead:
    """DeduplicationEngine.find_existing_lead — DB lookup behaviour."""

    def test_returns_none_when_no_leads_in_db(self, app):
        with app.app_context():
            engine = DeduplicationEngine()
            result = engine.find_existing_lead("123 Main St", pin="0001")
            assert result is None

    def test_returns_existing_lead_by_normalized_address_match(self, app):
        with app.app_context():
            existing = _make_lead("123 Main St")
            engine = DeduplicationEngine()
            # Look up with a case/punctuation variant of the same address
            result = engine.find_existing_lead("123 main st.")
            assert result is not None
            assert result.id == existing.id
            db.session.rollback()

    def test_address_match_is_case_insensitive(self, app):
        with app.app_context():
            existing = _make_lead("456 Oak Avenue")
            engine = DeduplicationEngine()
            result = engine.find_existing_lead("456 OAK AVENUE")
            assert result is not None
            assert result.id == existing.id
            db.session.rollback()

    def test_address_match_ignores_extra_spaces(self, app):
        with app.app_context():
            existing = _make_lead("  789  Elm  Street  ")
            engine = DeduplicationEngine()
            result = engine.find_existing_lead("789 Elm Street")
            assert result is not None
            assert result.id == existing.id
            db.session.rollback()

    def test_returns_existing_lead_by_pin_when_address_doesnt_match(self, app):
        with app.app_context():
            existing = _make_lead("100 Different St", pin="PIN-001")
            engine = DeduplicationEngine()
            # No address match, but PIN matches
            result = engine.find_existing_lead("999 Unrelated Ave", pin="PIN-001")
            assert result is not None
            assert result.id == existing.id
            db.session.rollback()

    def test_returns_none_when_neither_address_nor_pin_match(self, app):
        with app.app_context():
            _make_lead("100 Different St", pin="PIN-999")
            engine = DeduplicationEngine()
            result = engine.find_existing_lead("200 Another Rd", pin="PIN-000")
            assert result is None
            db.session.rollback()

    def test_address_takes_priority_over_pin(self, app):
        """When address matches, that lead is returned regardless of PIN."""
        with app.app_context():
            lead_by_addr = _make_lead("500 Priority Blvd", pin="PIN-A")
            _make_lead("600 Other St", pin="PIN-B")
            engine = DeduplicationEngine()
            # Address matches lead_by_addr; PIN matches nothing useful
            result = engine.find_existing_lead("500 Priority Blvd", pin="PIN-B")
            assert result is not None
            assert result.id == lead_by_addr.id
            db.session.rollback()

    def test_returns_none_when_no_pin_and_no_address_match(self, app):
        with app.app_context():
            _make_lead("100 Some St")
            engine = DeduplicationEngine()
            result = engine.find_existing_lead("200 Entirely Different Ave")
            assert result is None
            db.session.rollback()


# ---------------------------------------------------------------------------
# merge_lead — field merge behaviour
# ---------------------------------------------------------------------------

class TestMergeLead:
    """DeduplicationEngine.merge_lead — field merge rules."""

    def test_null_incoming_field_leaves_existing_unchanged(self, app):
        """If incoming value is None, existing non-null value is preserved."""
        with app.app_context():
            existing = _make_lead(
                "100 Merge St",
                owner_first_name="Alice",
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_first_name": None},
                import_job_id=1,
            )
            assert existing.owner_first_name == "Alice"
            assert result.outcome == "updated"
            db.session.rollback()

    def test_empty_string_incoming_leaves_existing_unchanged(self, app):
        """If incoming value is empty string, existing non-null value is preserved."""
        with app.app_context():
            existing = _make_lead(
                "101 Merge St",
                owner_first_name="Bob",
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_first_name": ""},
                import_job_id=1,
            )
            assert existing.owner_first_name == "Bob"
            assert result.outcome == "updated"
            db.session.rollback()

    def test_non_null_incoming_over_null_existing_updates_field(self, app):
        """Non-null incoming value populates a null existing field."""
        with app.app_context():
            existing = _make_lead(
                "102 Merge St",
                owner_first_name=None,
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_first_name": "Carol"},
                import_job_id=1,
            )
            assert existing.owner_first_name == "Carol"
            assert result.outcome == "updated"
            assert result.conflict_detail is None
            db.session.rollback()

    def test_non_null_incoming_over_non_null_existing_preserves_existing(self, app):
        """When both existing and incoming are non-null and differ, existing wins."""
        with app.app_context():
            existing = _make_lead(
                "103 Merge St",
                owner_first_name="Dave",
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_first_name": "DAVE_NEW"},
                import_job_id=1,
            )
            # Existing value preserved
            assert existing.owner_first_name == "Dave"
            db.session.rollback()

    def test_conflict_logged_when_non_null_fields_differ(self, app):
        """A conflict entry is created when existing and incoming are both non-null and different."""
        with app.app_context():
            existing = _make_lead(
                "104 Merge St",
                owner_first_name="Eve",
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_first_name": "EVE_DIFFERENT"},
                import_job_id=1,
            )
            assert result.outcome == "conflict"
            assert result.conflict_detail is not None
            field_conflicts = result.conflict_detail["field_conflicts"]
            assert len(field_conflicts) == 1
            conflict = field_conflicts[0]
            assert conflict["field"] == "owner_first_name"
            assert conflict["existing_value"] == "Eve"
            assert conflict["rejected_incoming_value"] == "EVE_DIFFERENT"
            db.session.rollback()

    def test_conflict_detail_includes_import_job_id(self, app):
        """Conflict entries record the import_job_id for traceability."""
        with app.app_context():
            existing = _make_lead(
                "105 Merge St",
                owner_last_name="Smith",
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_last_name": "JONES"},
                import_job_id=42,
            )
            field_conflicts = result.conflict_detail["field_conflicts"]
            assert field_conflicts[0]["import_job_id"] == 42
            db.session.rollback()

    def test_last_import_job_id_always_updated(self, app):
        """last_import_job_id is always set to the current import job, even when no other fields change."""
        with app.app_context():
            existing = _make_lead(
                "106 Merge St",
                import_job_id=10,
            )
            engine = DeduplicationEngine()
            engine.merge_lead(
                existing=existing,
                incoming={},
                import_job_id=99,
            )
            assert existing.last_import_job_id == 99
            db.session.rollback()

    def test_outcome_is_updated_when_no_conflicts(self, app):
        """Outcome is 'updated' when all incoming fields are null or update null existing fields."""
        with app.app_context():
            existing = _make_lead(
                "107 Merge St",
                owner_first_name=None,
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_first_name": "Frank", "notes": None},
                import_job_id=1,
            )
            assert result.outcome == "updated"
            db.session.rollback()

    def test_outcome_is_conflict_when_any_field_conflicts(self, app):
        """Outcome is 'conflict' as soon as at least one field has a conflict."""
        with app.app_context():
            existing = _make_lead(
                "108 Merge St",
                owner_first_name="Grace",
                owner_last_name=None,
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={
                    "owner_first_name": "GRACE_NEW",  # conflict
                    "owner_last_name": "Williams",    # update (null → non-null)
                },
                import_job_id=1,
            )
            assert result.outcome == "conflict"
            # Only one conflict (owner_first_name)
            assert len(result.conflict_detail["field_conflicts"]) == 1
            # owner_last_name was still updated
            assert existing.owner_last_name == "Williams"
            db.session.rollback()

    def test_multiple_field_conflicts_all_logged(self, app):
        """All conflicting fields are recorded, not just the first one."""
        with app.app_context():
            existing = _make_lead(
                "109 Merge St",
                owner_first_name="Henry",
                owner_last_name="Adams",
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={
                    "owner_first_name": "HENRY_NEW",
                    "owner_last_name": "ADAMS_NEW",
                },
                import_job_id=1,
            )
            assert result.outcome == "conflict"
            assert len(result.conflict_detail["field_conflicts"]) == 2
            conflicted_fields = {c["field"] for c in result.conflict_detail["field_conflicts"]}
            assert conflicted_fields == {"owner_first_name", "owner_last_name"}
            db.session.rollback()

    def test_protected_fields_not_overwritten(self, app):
        """id and created_at are never touched by merge."""
        with app.app_context():
            existing = _make_lead("110 Merge St")
            original_id = existing.id
            engine = DeduplicationEngine()
            engine.merge_lead(
                existing=existing,
                incoming={"id": 9999, "created_at": None},
                import_job_id=1,
            )
            assert existing.id == original_id
            db.session.rollback()

    def test_merge_returns_deduplication_result(self, app):
        """merge_lead always returns a DeduplicationResult."""
        with app.app_context():
            from app.services.deduplication_engine import DeduplicationResult
            existing = _make_lead("111 Merge St")
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={},
                import_job_id=1,
            )
            assert isinstance(result, DeduplicationResult)
            assert result.lead is existing
            db.session.rollback()

    def test_same_value_incoming_does_not_create_conflict(self, app):
        """When incoming value equals existing value, no conflict is logged."""
        with app.app_context():
            existing = _make_lead(
                "112 Merge St",
                owner_first_name="Iris",
            )
            engine = DeduplicationEngine()
            result = engine.merge_lead(
                existing=existing,
                incoming={"owner_first_name": "Iris"},
                import_job_id=1,
            )
            assert result.outcome == "updated"
            assert result.conflict_detail is None
            db.session.rollback()


# ---------------------------------------------------------------------------
# process_record — full deduplication flow
# ---------------------------------------------------------------------------

class TestProcessRecord:
    """DeduplicationEngine.process_record — end-to-end deduplication flow."""

    def test_new_address_creates_new_lead(self, app):
        """A record with an address not in DB results in outcome='created'."""
        with app.app_context():
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={"property_street": "200 New Street", "source_type": "foreclosure"},
                import_job_id=1,
            )
            assert result.outcome == "created"
            assert result.lead is not None
            assert result.lead.id is not None
            assert result.conflict_detail is None
            db.session.rollback()

    def test_new_lead_is_persisted_to_db(self, app):
        """A created lead is visible in the DB (after flush)."""
        with app.app_context():
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={"property_street": "201 New Ave", "source_type": "foreclosure"},
                import_job_id=1,
            )
            lead_id = result.lead.id
            found = db.session.get(Property, lead_id)
            assert found is not None
            assert found.property_street == "201 New Ave"
            db.session.rollback()

    def test_existing_address_returns_updated_outcome(self, app):
        """Re-ingesting with same address and no conflicting fields → 'updated'."""
        with app.app_context():
            existing = _make_lead("300 Existing Rd")
            engine = DeduplicationEngine()
            # Use only null incoming fields so merge finds no conflicts.
            # property_street is intentionally omitted from 'incoming' here to
            # avoid a spurious field-value conflict from the case variant
            # ("300 existing rd" vs stored "300 Existing Rd") — address matching
            # is handled by normalize_address, not field-equality comparison.
            result = engine.process_record(
                record={
                    "property_street": "300 Existing Rd",  # exact match, no conflict
                    "owner_first_name": None,              # null incoming → no change
                },
                import_job_id=5,
            )
            assert result.outcome == "updated"
            assert result.lead.id == existing.id
            db.session.rollback()

    def test_existing_address_with_conflicting_fields_returns_conflict(self, app):
        """Re-ingesting with same address but conflicting non-null field → 'conflict'."""
        with app.app_context():
            _make_lead(
                "400 Conflict Ln",
                owner_first_name="Jack",
            )
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={
                    "property_street": "400 Conflict Ln",
                    "owner_first_name": "JACK_NEW",
                },
                import_job_id=7,
            )
            assert result.outcome == "conflict"
            db.session.rollback()

    def test_pin_mismatch_returns_conflict_outcome(self, app):
        """When address matches but PINs differ, outcome is 'conflict'."""
        with app.app_context():
            _make_lead("500 Pin Mismatch St", pin="OLD-PIN-123")
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={
                    "property_street": "500 Pin Mismatch St",
                    "county_assessor_pin": "NEW-PIN-456",
                },
                import_job_id=3,
            )
            assert result.outcome == "conflict"
            db.session.rollback()

    def test_pin_mismatch_conflict_detail_has_correct_type(self, app):
        """PIN mismatch conflict_detail has type=='pin_mismatch'."""
        with app.app_context():
            _make_lead("501 Pin Detail St", pin="PIN-ORIG")
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={
                    "property_street": "501 Pin Detail St",
                    "county_assessor_pin": "PIN-DIFF",
                },
                import_job_id=3,
            )
            assert result.conflict_detail is not None
            assert result.conflict_detail["type"] == "pin_mismatch"
            db.session.rollback()

    def test_pin_mismatch_conflict_detail_includes_pins(self, app):
        """conflict_detail for a PIN mismatch records both existing and incoming PINs."""
        with app.app_context():
            existing = _make_lead("502 Pin Info St", pin="ORIG-001")
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={
                    "property_street": "502 Pin Info St",
                    "county_assessor_pin": "DIFF-002",
                },
                import_job_id=3,
            )
            assert result.conflict_detail["existing_pin"] == "ORIG-001"
            assert result.conflict_detail["incoming_pin"] == "DIFF-002"
            assert result.conflict_detail["existing_lead_id"] == existing.id
            db.session.rollback()

    def test_pin_mismatch_leaves_existing_lead_unchanged(self, app):
        """On a PIN mismatch the existing lead is not modified."""
        with app.app_context():
            existing = _make_lead(
                "503 Pin Preserve St",
                pin="KEEP-ME",
                owner_first_name="Karen",
            )
            engine = DeduplicationEngine()
            engine.process_record(
                record={
                    "property_street": "503 Pin Preserve St",
                    "county_assessor_pin": "WRONG-PIN",
                    "owner_first_name": "KAREN_OVERRIDE",
                },
                import_job_id=3,
            )
            # Reload from DB
            db.session.expire(existing)
            assert existing.county_assessor_pin == "KEEP-ME"
            assert existing.owner_first_name == "Karen"
            db.session.rollback()

    def test_no_address_in_record_treats_as_new_lead(self, app):
        """A record with no property_street is treated as a new lead."""
        with app.app_context():
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={"source_type": "foreclosure"},
                import_job_id=1,
            )
            assert result.outcome == "created"
            db.session.rollback()

    def test_process_record_sets_last_import_job_id_on_new_lead(self, app):
        """Newly created lead has last_import_job_id set to the current import job."""
        with app.app_context():
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={"property_street": "600 New Import St"},
                import_job_id=88,
            )
            assert result.lead.last_import_job_id == 88
            db.session.rollback()

    def test_process_record_updates_last_import_job_id_on_existing_lead(self, app):
        """Existing lead has last_import_job_id updated to the current import job."""
        with app.app_context():
            _make_lead("700 Existing Import St", import_job_id=10)
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={"property_street": "700 Existing Import St"},
                import_job_id=50,
            )
            assert result.lead.last_import_job_id == 50
            db.session.rollback()

    def test_matching_pin_no_address_conflict_merges_normally(self, app):
        """When found via PIN (no address match), merge proceeds normally."""
        with app.app_context():
            existing = _make_lead("800 Pin Only St", pin="FOUND-PIN")
            engine = DeduplicationEngine()
            result = engine.process_record(
                record={
                    "property_street": "999 Different Address",
                    "county_assessor_pin": "FOUND-PIN",
                    "owner_first_name": None,  # null incoming → no change
                },
                import_job_id=20,
            )
            # Found via PIN → merge, not create
            assert result.outcome in ("updated", "conflict")
            assert result.lead.id == existing.id
            db.session.rollback()
