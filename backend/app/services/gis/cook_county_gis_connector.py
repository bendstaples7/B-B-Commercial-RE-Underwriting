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
    # 1. Exact match
    where = f"property_address='{normalised.replace(chr(39), chr(39)*2)}'"
    url = parcel_addresses_url + "?$where=" + urllib.parse.quote(where) + "&$limit=5"
    results = _socrata_get(url)

    if not results:
        # 2. LIKE prefix on first 3 tokens (handles suffix variant: AVE vs AVENUE)
        tokens = normalised.split()
        if len(tokens) >= 2:
            prefix = ' '.join(tokens[:3]) if len(tokens) >= 3 else ' '.join(tokens[:2])
            safe_prefix = prefix.replace("'", "''")
            where2 = f"property_address like '{safe_prefix}%'"
            url2 = parcel_addresses_url + "?$where=" + urllib.parse.quote(where2) + "&$limit=10"
            results = _socrata_get(url2)

    if not results:
        logger.debug("CookCountyGIS: no PIN found for %r", normalised)
        return None

    # Prefer Chicago records when multiple results; fall back to first
    chicago = [r for r in results if r.get('property_city', '').upper() == 'CHICAGO']
    row = chicago[0] if chicago else results[0]
    pin = row.get('pin')
    if pin:
        logger.debug("CookCountyGIS: PIN=%s for %r", pin, normalised)
    return pin


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

    def lookup_by_pin(self, pin: str) -> Optional[GISParcel]:
        """Look up a parcel by 14-digit Cook County PIN.

        Fetches improvement characteristics directly.
        Returns None if no data found for that PIN.
        """
        chars = _fetch_improvement_chars(pin, self._improvement_chars_url)
        if not chars and not pin:
            return None
        # Even if chars is empty we return a parcel with just the PIN —
        # that's enough to set has_property_match = True.
        return _build_parcel(pin, chars)


# ---------------------------------------------------------------------------
# Registry registration — runs at import time
# ---------------------------------------------------------------------------
GISConnectorRegistry['cook_county_il'] = CookCountyGISConnector()
