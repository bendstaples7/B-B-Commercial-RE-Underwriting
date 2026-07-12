"""Tests for owner name entity / institutional classification."""
from app.services.plugins.owner_name_utils import (
    apply_owner_name_fields,
    is_definite_institutional_name,
    is_entity_name,
    is_institutional_name,
)


class TestInstitutionalName:
    def test_definite_church(self):
        assert is_definite_institutional_name("First Baptist Church")
        assert is_institutional_name("First Baptist Church")
        assert is_entity_name("First Baptist Church")

    def test_soft_foundation_not_definite(self):
        assert is_institutional_name("Acme Community Foundation")
        assert not is_definite_institutional_name("Acme Community Foundation")
        assert is_entity_name("Acme Community Foundation")

    def test_soft_school_not_definite(self):
        assert is_institutional_name("Old School Properties LLC")
        assert not is_definite_institutional_name("Old School Properties LLC")

    def test_not_for_profit_phrase(self):
        assert is_definite_institutional_name("Helping Hands Not For Profit")
        assert is_definite_institutional_name("Helping Hands Non-Profit Inc")

    def test_housing_authority(self):
        assert is_definite_institutional_name("Chicago Housing Authority")

    def test_investor_llc_not_institutional(self):
        assert not is_institutional_name("123 Main Street LLC")
        assert is_entity_name("123 Main Street LLC")

    def test_ambiguous_inc_not_institutional(self):
        assert not is_institutional_name("North Lockwood Jazz Inc")
        assert is_entity_name("North Lockwood Jazz Inc")

    def test_voice_of_people_not_institutional_by_name(self):
        # Relies on IRS EO research — name markers alone are not enough.
        assert not is_institutional_name("Voice of the People in Uptown Inc")
        assert is_entity_name("Voice of the People in Uptown Inc")


class TestApplyOwnerNameFields:
    def test_entity_sets_ownership_type(self):
        fields = {}
        apply_owner_name_fields(fields, "ACME HOLDINGS, INC.")
        assert fields["ownership_type"] == "entity"
        assert fields["owner_last_name"] == "ACME HOLDINGS, INC."
        assert fields["owner_first_name"] is None
