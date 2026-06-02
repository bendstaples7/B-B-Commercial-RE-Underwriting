"""Unit tests for DuPage lead database schema validation.

Covers:
  - IngestionRequestSchema — required fields, empty records, None records
  - LeadListQuerySchema — source_type and owner_user_id additions from task 3.2

Requirements: 11.3, 11.4
"""
import pytest
from marshmallow import ValidationError

from app.schemas import (
    IngestionRequestSchema,
    LeadListQuerySchema,
    VALID_SOURCE_TYPES,
)


# ---------------------------------------------------------------------------
# IngestionRequestSchema
# ---------------------------------------------------------------------------

class TestIngestionRequestSchema:
    def setup_method(self):
        self.schema = IngestionRequestSchema()

    # --- valid payloads -------------------------------------------------------

    def test_valid_payload_accepted(self):
        """A payload with a valid owner_user_id and at least one record passes."""
        result = self.schema.load({
            "owner_user_id": "user-123",
            "records": [{"a": 1}],
        })
        assert result["owner_user_id"] == "user-123"
        assert result["records"] == [{"a": 1}]

    def test_multiple_records_accepted(self):
        """Multiple records are accepted without error."""
        result = self.schema.load({
            "owner_user_id": "user-abc",
            "records": [{"x": 1}, {"x": 2}, {"x": 3}],
        })
        assert len(result["records"]) == 3

    def test_owner_user_id_at_max_length_accepted(self):
        """owner_user_id at the 36-character maximum is accepted."""
        uid = "a" * 36
        result = self.schema.load({"owner_user_id": uid, "records": [{"r": 1}]})
        assert result["owner_user_id"] == uid

    # --- missing / invalid owner_user_id ------------------------------------

    def test_missing_owner_user_id_raises(self):
        """Missing owner_user_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"records": [{"a": 1}]})
        assert "owner_user_id" in exc_info.value.messages

    def test_empty_owner_user_id_raises(self):
        """Empty string owner_user_id (min_size=1) raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"owner_user_id": "", "records": [{"a": 1}]})
        assert "owner_user_id" in exc_info.value.messages

    def test_owner_user_id_over_max_length_raises(self):
        """owner_user_id longer than 36 characters raises ValidationError."""
        uid = "b" * 37
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"owner_user_id": uid, "records": [{"a": 1}]})
        assert "owner_user_id" in exc_info.value.messages

    # --- missing / empty / None records ------------------------------------

    def test_missing_records_raises(self):
        """Missing records field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"owner_user_id": "user-123"})
        assert "records" in exc_info.value.messages

    def test_empty_records_list_raises(self):
        """Empty records list (min=1) raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"owner_user_id": "user-123", "records": []})
        assert "records" in exc_info.value.messages

    def test_records_none_raises(self):
        """records=None raises ValidationError (field is required, not allow_none)."""
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"owner_user_id": "user-123", "records": None})
        assert "records" in exc_info.value.messages


# ---------------------------------------------------------------------------
# LeadListQuerySchema — source_type and owner_user_id (task 3.2 additions)
# ---------------------------------------------------------------------------

class TestLeadListQuerySchemaSourceType:
    def setup_method(self):
        self.schema = LeadListQuerySchema()

    # --- invalid source_type ------------------------------------------------

    def test_invalid_source_type_raises(self):
        """A source_type not in VALID_SOURCE_TYPES raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"source_type": "invalid_type"})
        assert "source_type" in exc_info.value.messages

    def test_arbitrary_string_source_type_raises(self):
        """Any arbitrary string not in the allowed set is rejected."""
        with pytest.raises(ValidationError):
            self.schema.load({"source_type": "random_garbage"})

    # --- valid source_type values -------------------------------------------

    def test_foreclosure_source_type_accepted(self):
        """'foreclosure' is accepted and returned."""
        result = self.schema.load({"source_type": "foreclosure"})
        assert result["source_type"] == "foreclosure"

    def test_all_five_valid_source_types_accepted(self):
        """Every value in VALID_SOURCE_TYPES is individually accepted."""
        for st in VALID_SOURCE_TYPES:
            result = self.schema.load({"source_type": st})
            assert result["source_type"] == st, f"Expected {st} to be accepted"

    def test_source_type_defaults_to_none(self):
        """When source_type is omitted, it defaults to None (no filter)."""
        result = self.schema.load({})
        assert result["source_type"] is None

    # --- owner_user_id (DuPage addition) ------------------------------------

    def test_valid_owner_user_id_accepted(self):
        """A valid owner_user_id (≤36 chars) is accepted."""
        result = self.schema.load({"owner_user_id": "user-abc-123"})
        assert result["owner_user_id"] == "user-abc-123"

    def test_owner_user_id_at_max_length_accepted(self):
        """owner_user_id of exactly 36 characters is accepted."""
        uid = "c" * 36
        result = self.schema.load({"owner_user_id": uid})
        assert result["owner_user_id"] == uid

    def test_owner_user_id_over_36_chars_raises(self):
        """owner_user_id longer than 36 characters raises ValidationError."""
        uid = "d" * 37
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({"owner_user_id": uid})
        assert "owner_user_id" in exc_info.value.messages

    def test_owner_user_id_defaults_to_none(self):
        """When owner_user_id is omitted, it defaults to None (no filter)."""
        result = self.schema.load({})
        assert result["owner_user_id"] is None

    # --- both filters together ----------------------------------------------

    def test_valid_source_type_and_owner_user_id_together(self):
        """Valid source_type and owner_user_id can be used together."""
        result = self.schema.load({
            "source_type": "tax_distress",
            "owner_user_id": "user-xyz",
        })
        assert result["source_type"] == "tax_distress"
        assert result["owner_user_id"] == "user-xyz"

    def test_invalid_source_type_with_valid_owner_user_id_raises(self):
        """Invalid source_type is still rejected even when owner_user_id is valid."""
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({
                "source_type": "not_a_real_type",
                "owner_user_id": "user-123",
            })
        assert "source_type" in exc_info.value.messages
