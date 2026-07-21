"""Tests for owner name entity / institutional classification."""
from app.services.plugins.owner_name_utils import (
    apply_owner_name_fields,
    expand_owner_name_parts,
    is_address_like_name,
    is_definite_institutional_name,
    is_entity_name,
    is_generic_owner_name,
    is_institutional_name,
    is_matchable_person_name,
    owner_names_equivalent,
)


class TestExpandOwnerNameParts:
    def test_jammed_full_name_splits_trailing_last(self):
        assert expand_owner_name_parts('GARCIA ADALBERTO', None) == ('GARCIA', 'ADALBERTO')

    def test_already_split_unchanged(self):
        assert expand_owner_name_parts('GARCIA', 'ADALBERTO') == ('GARCIA', 'ADALBERTO')

    def test_expand_strips_generational_suffix(self):
        assert expand_owner_name_parts('John Smith Jr', None) == ('John', 'Smith')
        assert expand_owner_name_parts('John Smith Jr.', None) == ('John', 'Smith')
        assert expand_owner_name_parts('Mary Jane Doe III', None) == ('Mary Jane', 'Doe')

    def test_jr_equivalent_to_split_name(self):
        assert owner_names_equivalent('John Smith Jr', None, 'John', 'Smith')

    def test_conflicting_middle_initials_not_merge_safe(self):
        from app.services.plugins.owner_name_utils import owner_names_merge_safe

        assert owner_names_equivalent('Gilbert E', 'Janson', 'Gilbert A', 'Janson')
        assert not owner_names_merge_safe('Gilbert E', 'Janson', 'Gilbert A', 'Janson')
        assert owner_names_merge_safe('Gilbert', 'Janson', 'Gilbert E', 'Janson')
        assert owner_names_merge_safe('Gilbert E', 'Janson', 'Gilbert Edward', 'Janson')

    def test_equivalent_jammed_vs_split(self):
        assert owner_names_equivalent(
            'GARCIA ADALBERTO', None, 'GARCIA', 'ADALBERTO',
        )

    def test_equivalent_jammed_assessor_last_first_vs_western(self):
        assert owner_names_equivalent(
            'GARCIA ADALBERTO', None, 'ADALBERTO', 'GARCIA',
        )

    def test_last_name_only_not_equivalent(self):
        assert not owner_names_equivalent(None, 'Smith', None, 'Smith')


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

    def test_asset_management_is_entity(self):
        from app.services.plugins.owner_name_utils import is_property_management_name

        assert is_entity_name("Svigos Asset Management")
        assert is_property_management_name("Svigos Asset Management")
        assert is_entity_name("North Side Property Management")
        assert not is_entity_name("Jane Doe")
        # Bare soft tokens must not classify person-like names as entities.
        assert not is_entity_name("Jane Management")
        assert not is_entity_name("Bob Holdings")
        assert not is_entity_name("Sue Properties")

    def test_ambiguous_inc_not_institutional(self):
        assert not is_institutional_name("North Lockwood Jazz Inc")
        assert is_entity_name("North Lockwood Jazz Inc")

    def test_voice_of_people_not_institutional_by_name(self):
        # Relies on IRS EO research — name markers alone are not enough.
        assert not is_institutional_name("Voice of the People in Uptown Inc")
        assert is_entity_name("Voice of the People in Uptown Inc")


class TestOwnerNamesEquivalent:
    def test_generic_labels_are_not_matchable_or_equivalent(self):
        assert is_generic_owner_name('For Sale By Owner +')
        assert is_generic_owner_name('N/A')
        assert is_generic_owner_name('NA')
        assert is_generic_owner_name('current resident')
        assert is_generic_owner_name('')
        assert not is_generic_owner_name('Joseph Kiferbaum')
        assert not is_generic_owner_name('Jane Na')
        assert not is_generic_owner_name('Na Zhang')
        assert not is_matchable_person_name('For Sale By', 'Owner')
        assert not is_matchable_person_name('123', 'Main St')
        assert not owner_names_equivalent('FSBO', None, 'FSBO', None)

    def test_middle_initial_matches(self):
        from app.services.plugins.owner_name_utils import owner_names_equivalent
        assert owner_names_equivalent("Joseph", "Kiferbaum", "JOSEPH A", "KIFERBAUM")

    def test_different_last_name(self):
        from app.services.plugins.owner_name_utils import owner_names_equivalent
        assert not owner_names_equivalent("Joseph", "Kiferbaum", "Joseph", "Smith")

    def test_different_first_name(self):
        from app.services.plugins.owner_name_utils import owner_names_equivalent
        assert not owner_names_equivalent("Joseph", "Kiferbaum", "Jane", "Kiferbaum")


class TestAddressLikeName:
    def test_mashed_sacramento(self):
        assert is_address_like_name("3508SACRAMENTO MAYNARD")

    def test_street_address(self):
        assert is_address_like_name("123 Main St")

    def test_person_not_address(self):
        assert not is_address_like_name("Joseph Kiferbaum")

    def test_llc_not_address_even_with_digits(self):
        assert is_entity_name("123 Main Street LLC")
        assert not is_address_like_name("123 Main Street LLC")


class TestApplyOwnerNameFields:
    def test_entity_sets_ownership_type(self):
        fields = {}
        apply_owner_name_fields(fields, "ACME HOLDINGS, INC.")
        assert fields["ownership_type"] == "entity"
        assert fields["owner_last_name"] == "ACME HOLDINGS, INC."
        assert fields["owner_first_name"] is None
