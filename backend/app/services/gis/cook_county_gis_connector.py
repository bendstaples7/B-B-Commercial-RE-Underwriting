"""Cook County GIS connector implementation.

Uses the Cook County Assessor's public Socrata datasets (no API key required):

  c49d-89sn  — Parcel Addresses  (address → 14-digit PIN)
  bcnq-qi2z  — Improvement Chars (PIN → beds/baths/sqft/year_built/units)

PIN lookup strategy:
  1. Exact match on normalised address string
  2. LIKE prefix match on first 3 tokens (handles suffix variations e.g. AVE/AVENUE)

Both lookup_by_address and lookup_by_pin return a GISParcel with the PIN
and any improvement characteristics that were available.  Owner name and
mailing address are NOT available from these datasets and will be None.

Register with market key "cook_county_il" so the routing helper can
select this connector for any Cook County lead.

Override dataset URLs with:
  COOK_COUNTY_PARCEL_ADDRESSES_URL
  COOK_COUNTY_IMPROVEMENT_CHARS_URL
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from .base import GISConnector, GISConnectorRegistry, GISParcel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Socrata dataset endpoints (public, no auth required)
# ---------------------------------------------------------------------------
_DEFAULT_PARCEL_ADDRESSES_URL = (
    "https://datacatalog.cookcountyil.gov/resource/c49d-89sn.json"
)
_DEFAULT_IMPROVEMENT_CHARS_URL = (
    "https://datacatalog.cookcountyil.gov/resource/bcnq-qi2z.json"
)

# Street-type abbreviation maps (matches PropertyDataService normalisation)
_DIRECTION_MAP = {
    r'\bNORTH\b': 'N', r'\bSOUTH\b': 'S',
    r'\bEAST\b':  'E', r'\bWEST\b':  'W',
}
_SUFFIX_MAP = {
    r'\bAVENUE\b':    'AVE',   r'\bBOULEVARD\b': 'BLVD',
    r'\bCIRCLE\b':    'CIR',   r'\bCOURT\b':     'CT',
    r'\bDRIVE\b':     'DR',    r'\bLANE\b':       'LN',
    r'\bPLACE\b':     'PL',    r'\bROAD\b':       'RD',
    r'\bSTREET\b':    'ST',    r'\bTERRACE\b':    'TER',
}

TIMEOUT_SECONDS = 10


def _normalise_address(address: str) -> str:
    """Normalise address to Cook County Assessor format: '2553 N DRAKE AVE'.

    The dataset stores only the street address without unit numbers.
    This strips common unit suffixes (APT 1, UNIT 2, #3, trailing digits
    after the street name) so the lookup matches the dataset format.
    """
    street_part = address.split(',')[0].strip().upper()
    for pattern, abbr in _DIRECTION_MAP.items():
        street_part = re.sub(pattern, abbr, street_part)
    for pattern, abbr in _SUFFIX_MAP.items():
        street_part = re.sub(pattern, abbr, street_part)

    # Strip unit/apt suffixes — these are NOT in the Cook County dataset.
    # Patterns handled (case-insensitive, already uppercased):
    #   "2553 N DRAKE AVE 1"       → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE APT 1"   → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE UNIT 2"  → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE #3"      → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE 1FL"     → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE 1ST"     → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE 2ND"     → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE FRNT"    → "2553 N DRAKE AVE"
    #   "2553 N DRAKE AVE 1-3"     → "2553 N DRAKE AVE"
    street_part = re.sub(
        r'\s+(APT|UNIT|STE|SUITE|#|FL|FLOOR|FRNT|FRONT|REAR|BSMT|BS)\s*\S*$',
        '', street_part
    )
    # Strip bare trailing token that is a unit number:
    #   digits alone, digits+letters (1A, 2B, 1FL, 55), ordinals (1ST, 2ND, 3RD),
    #   or digit ranges (1-3)
    street_part = re.sub(
        r'\s+(\d+[A-Z\-]*|\d+(ST|ND|RD|TH))$',
        '', street_part
    )
    return street_part.strip()


def _socrata_get(url: str) -> list:
    """Fetch a Socrata JSON endpoint. Returns [] on any error."""
    app_token = os.getenv('COOK_COUNTY_APP_TOKEN', '')
    headers = {}
    if app_token:
        headers['X-App-Token'] = app_token

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8')[:200]
        except Exception:
            pass
        logger.error("CookCountyGIS HTTP %s for %r: %s", exc.code, url, body)
    except urllib.error.URLError as exc:
        logger.error("CookCountyGIS URL error for %r: %s", url, exc.reason)
    except Exception as exc:
        logger.error("CookCountyGIS error for %r: %s", url, exc)
    return []


def _lookup_pin_from_address(address: str, parcel_addresses_url: str) -> Optional[str]:
    """Address → 14-digit PIN via Cook County parcel addresses dataset.

    Handles both plain addresses ('2553 N DRAKE AVE') and range-format addresses
    ('5401-5409 W LEMOYNE ST') by trying the normalised address first, then
    falling back to just the first street number when a range is detected.
    """
    normalised = _normalise_address(address)
    if not normalised:
        return None

    # Try the normalised address first (exact, then LIKE prefix)
    pin = _try_lookup(normalised, parcel_addresses_url)
    if pin:
        return pin

    # Fallback: strip address range notation (e.g. '5401-5409 W LEMOYNE ST'
    # → '5401 W LEMOYNE ST') and retry.  Range addresses are common for
    # multi-unit buildings; Cook County Socrata indexes each unit individually.
    import re as _re
    range_match = _re.match(r'^(\d+)-\d+\s+(.+)$', normalised)
    if range_match:
        first_number = range_match.group(1)
        rest = range_match.group(2)
        stripped = f"{first_number} {rest}"
        pin = _try_lookup(stripped, parcel_addresses_url)

    return pin


def _try_lookup(normalised: str, parcel_addresses_url: str) -> Optional[str]:
    """Attempt exact then LIKE-prefix lookup for a single normalised address string."""
    from app.services.plugins.socrata_client import escape_soql_literal, socrata_get

    safe = escape_soql_literal(normalised)
    results = socrata_get(
        'c49d-89sn',
        params={'$where': f"property_address='{safe}'", '$limit': 5},
        portal='cook_county',
    )

    if not results:
        tokens = normalised.split()
        if len(tokens) >= 2:
            prefix = ' '.join(tokens[:3]) if len(tokens) >= 3 else ' '.join(tokens[:2])
            safe_prefix = escape_soql_literal(prefix)
            results = socrata_get(
                'c49d-89sn',
                params={'$where': f"property_address like '{safe_prefix}%'", '$limit': 10},
                portal='cook_county',
            )

    if not results:
        logger.debug("CookCountyGIS: no PIN found for %r", normalised)
        return None

    chicago = [r for r in results if r.get('property_city', '').upper() == 'CHICAGO']
    row = chicago[0] if chicago else results[0]
    pin = row.get('pin')
    if pin:
        logger.debug("CookCountyGIS: PIN=%s for %r", pin, normalised)
    return pin


def _lookup_all_pins_from_address(address: str, parcel_addresses_url: str, limit: int = 25) -> list[dict]:
    """Return all parcel address rows matching an address (deduped by PIN)."""
    from app.services.plugins.socrata_client import escape_soql_literal, socrata_get

    normalised = _normalise_address(address)
    if not normalised:
        return []

    addresses_to_try = [normalised]
    import re as _re
    range_match = _re.match(r'^(\d+)-\d+\s+(.+)$', normalised)
    if range_match:
        addresses_to_try.append(f"{range_match.group(1)} {range_match.group(2)}")

    seen_pins: set[str] = set()
    rows_out: list[dict] = []

    for addr in addresses_to_try:
        safe = escape_soql_literal(addr)
        results = socrata_get(
            'c49d-89sn',
            params={'$where': f"property_address='{safe}'", '$limit': limit},
            portal='cook_county',
        )
        if not results:
            tokens = addr.split()
            if len(tokens) >= 2:
                prefix = ' '.join(tokens[:3]) if len(tokens) >= 3 else ' '.join(tokens[:2])
                safe_prefix = escape_soql_literal(prefix)
                results = socrata_get(
                    'c49d-89sn',
                    params={'$where': f"property_address like '{safe_prefix}%'", '$limit': limit},
                    portal='cook_county',
                )
        for row in results or []:
            pin = (row.get('pin') or '').strip()
            if not pin or pin in seen_pins:
                continue
            seen_pins.add(pin)
            street = (row.get('property_address') or '').strip()
            if not street:
                continue
            rows_out.append({
                'pin': pin,
                'property_street': street,
                'property_city': (row.get('property_city') or '').strip() or None,
                'property_state': (row.get('property_state') or 'IL').strip(),
                'property_zip': (row.get('property_zip') or '').strip() or None,
            })
    return rows_out


def lookup_all_pins_at_address(address: str, parcel_addresses_url: str | None = None) -> list[dict]:
    """Public helper: all PINs at a normalized Cook County address."""
    url = parcel_addresses_url or os.environ.get(
        'COOK_COUNTY_PARCEL_ADDRESSES_URL', _DEFAULT_PARCEL_ADDRESSES_URL
    )
    return _lookup_all_pins_from_address(address, url)


def _parcel_address_row_from_results(results: list) -> Optional[dict]:
    if not results:
        return None
    chicago = [r for r in results if (r.get('property_city') or '').upper() == 'CHICAGO']
    row = chicago[0] if chicago else results[0]
    street = (row.get('property_address') or '').strip()
    if not street:
        return None
    return {
        'property_street': street,
        'property_city': (row.get('property_city') or '').strip() or None,
        'property_state': (row.get('property_state') or 'IL').strip(),
        'property_zip': (row.get('property_zip') or '').strip() or None,
    }


def _lookup_address_from_pin(pin: str, parcel_addresses_url: str) -> Optional[dict]:
    """PIN → street address via Cook County parcel addresses dataset (c49d-89sn)."""
    if not pin or not str(pin).strip():
        return None
    from app.services.plugins.pin_utils import format_pin_for_storage, normalize_pin_for_socrata
    from app.services.plugins.socrata_client import escape_soql_literal, socrata_get

    pin_text = str(pin).strip()
    variants: list[str] = []
    for candidate in (normalize_pin_for_socrata(pin_text), format_pin_for_storage(pin_text), pin_text):
        if candidate and candidate not in variants:
            variants.append(candidate)

    for variant in variants:
        where = f"pin='{escape_soql_literal(variant)}'"
        results = socrata_get(
            'c49d-89sn',
            params={'$where': where, '$limit': 10},
            portal='cook_county',
        )
        resolved = _parcel_address_row_from_results(results)
        if resolved:
            return resolved

    logger.warning('CookCountyGIS: no parcel address found for PIN=%r (tried %s)', pin, variants)
    return None


def _fetch_improvement_chars(pin: str, improvement_chars_url: str) -> dict:
    """PIN → building characteristics dict (sqft, beds, baths, year_built, units, property_type)."""
    where = f"pin='{pin.replace(chr(39), chr(39)*2)}'"
    url = improvement_chars_url + "?$where=" + urllib.parse.quote(where) + "&$limit=1"
    results = _socrata_get(url)
    if not results:
        return {}

    row = results[0]
    out: dict = {}

    # Square footage
    bldg_sf = row.get('bldg_sf')
    if bldg_sf is not None:
        try:
            out['square_footage'] = int(float(bldg_sf))
        except (ValueError, TypeError):
            pass

    # Bedrooms
    beds = row.get('beds')
    if beds is not None:
        try:
            out['bedrooms'] = int(float(beds))
        except (ValueError, TypeError):
            pass

    # Bathrooms: full + 0.5 × half
    fbath, hbath = row.get('fbath'), row.get('hbath')
    try:
        full = float(fbath) if fbath is not None else 0.0
        half = float(hbath) if hbath is not None else 0.0
        if fbath is not None or hbath is not None:
            out['bathrooms'] = full + 0.5 * half
    except (ValueError, TypeError):
        pass

    # Year built from 'age' field
    age = row.get('age')
    if age is not None:
        try:
            out['year_built'] = datetime.now().year - int(float(age))
        except (ValueError, TypeError):
            pass

    # Unit count
    apts = row.get('apts')
    if apts is not None:
        try:
            apt_count = int(float(apts))
            if apt_count > 0:
                out['units'] = apt_count
        except (ValueError, TypeError):
            pass

    # Property type from modeling_group (most reliable field)
    modeling_group = (row.get('modeling_group') or '').upper()
    if modeling_group == 'MF':
        out['property_type'] = 'multi_family'
    elif modeling_group == 'SF':
        out['property_type'] = 'single_family'

    return out


def _build_parcel(pin: str, chars: dict) -> GISParcel:
    """Build a GISParcel from a PIN + improvement characteristics dict."""
    return GISParcel(
        county_assessor_pin=pin,
        property_type=chars.get('property_type'),
        year_built=chars.get('year_built'),
        square_footage=chars.get('square_footage'),
        bedrooms=chars.get('bedrooms'),
        bathrooms=chars.get('bathrooms'),
        lot_size=None,          # not in Cook County dataset
        owner_first_name=None,  # not in Cook County dataset
        owner_last_name=None,   # not in Cook County dataset
        mailing_address=None,   # not in Cook County dataset
        mailing_city=None,
        mailing_state=None,
        mailing_zip=None,
    )


class CookCountyGISConnector(GISConnector):
    """GIS connector for Cook County, IL (Chicago area).

    Uses Cook County Assessor's public Socrata datasets.  No API key
    required; set COOK_COUNTY_APP_TOKEN env var to raise rate limits.

    Owner name and mailing address are not available from these datasets —
    those fields will be None in the returned GISParcel.  PIN and building
    characteristics (bedrooms, bathrooms, sqft, year_built, units,
    property_type) are populated where available.
    """

    def __init__(self) -> None:
        self._parcel_addresses_url = os.environ.get(
            'COOK_COUNTY_PARCEL_ADDRESSES_URL', _DEFAULT_PARCEL_ADDRESSES_URL
        )
        self._improvement_chars_url = os.environ.get(
            'COOK_COUNTY_IMPROVEMENT_CHARS_URL', _DEFAULT_IMPROVEMENT_CHARS_URL
        )

    @property
    def connector_name(self) -> str:
        return 'cook_county_gis'

    @property
    def market(self) -> str:
        return 'cook_county_il'

    def lookup_by_address(self, address: str) -> Optional[GISParcel]:
        """Look up a parcel by street address.

        1. Normalises address to Cook County Assessor format.
        2. Queries parcel addresses dataset for the 14-digit PIN.
        3. Fetches improvement characteristics for the PIN.
        Returns None if no PIN match found.
        """
        pin = _lookup_pin_from_address(address, self._parcel_addresses_url)
        if not pin:
            return None
        chars = _fetch_improvement_chars(pin, self._improvement_chars_url)
        return _build_parcel(pin, chars)

    def lookup_address_by_pin(self, pin: str) -> Optional[dict]:
        """Return street/city/state/zip for a Cook County PIN, or None if not found."""
        return _lookup_address_from_pin(pin, self._parcel_addresses_url)

    def lookup_by_pin(self, pin: str) -> Optional[GISParcel]:
        """Look up a parcel by 14-digit Cook County PIN.

        Fetches improvement characteristics directly. Returns None when the PIN
        is missing/empty OR when no characteristics are found for it — an empty
        PIN or empty result must report *no match* rather than a truthy
        (false-positive) match.
        """
        if not pin or not str(pin).strip():
            return None
        # Use the normalized (whitespace-stripped) PIN for the actual lookup —
        # validating with .strip() but querying with the raw padded value would
        # make a padded-but-valid PIN miss.
        normalized_pin = str(pin).strip()
        chars = _fetch_improvement_chars(normalized_pin, self._improvement_chars_url)
        if not chars:
            return None
        return _build_parcel(normalized_pin, chars)


# ---------------------------------------------------------------------------
# Registry registration — runs at import time
# ---------------------------------------------------------------------------
GISConnectorRegistry['cook_county_il'] = CookCountyGISConnector()
