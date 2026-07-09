"""Cook County assessor property class code helpers for condo detection."""

# Known condo / commercial-condo class codes (Cook County Parcel Universe `class`)
CONDO_CLASS_CODES = frozenset({
    '299', '290', '291', '292', '293', '294', '295', '296', '297', '298',
    '2-99', '2-90', '2-91',
})

COMMERCIAL_CLASS_PREFIXES = ('3', '5', '6')


def is_condo_assessor_class(assessor_class: str | None) -> bool:
    if not assessor_class:
        return False
    code = str(assessor_class).strip()
    if code in CONDO_CLASS_CODES:
        return True
    return 'condo' in code.lower()


def assessor_class_to_condo_language(assessor_class: str | None) -> bool:
    """Return True if assessor class indicates condo ownership structure."""
    return is_condo_assessor_class(assessor_class)


def map_assessor_class_to_property_type(assessor_class: str | None) -> str | None:
    """Map residential assessor codes to property_type; leave commercial as-is."""
    if not assessor_class:
        return None
    code = str(assessor_class).strip()
    residential_map = {
        '202': 'single_family',
        '203': 'multi_family', '204': 'multi_family', '205': 'multi_family',
        '206': 'multi_family', '207': 'multi_family', '208': 'multi_family',
        '211': 'multi_family', '212': 'multi_family',
    }
    if code in residential_map:
        return residential_map[code]
    if is_condo_assessor_class(code):
        return 'commercial condo'
    if code.startswith(COMMERCIAL_CLASS_PREFIXES):
        return 'commercial'
    return None
