"""Kane County GIS connector implementation.

Uses the Kane County ArcGIS MapServer (KanePINList) — publicly accessible,
no authentication required:

  https://gistech.countyofkane.org/arcgis/rest/services/KanePINList/MapServer/0

Field mapping (API response → GISParcel):
  PIN               → county_assessor_pin
  SiteAddress       → property address (used for LIKE address lookup)
  SiteCity          → property city
  SiteZip           → property zip
  MailingAddress    → mailing_address (owner name stored here as first line)
  MailingCity       → mailing_city
  MailingState      → mailing_state
  MailingZip        → mailing_zip
  UseCodeDescription → property_type (mapped from "Commercial", "Farmland", etc.)

Note: Building characteristics (beds/baths/sqft/year_built) are not available
from this dataset — those fields will be None in the returned GISParcel.

Override base URL with KANE_COUNTY_GIS_URL environment variable.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import requests

from .base import GISConnector, GISConnectorRegistry, GISParcel
from .utils import escape_like as _escape_like

logger = logging.getLogger(__name__)

_DEFAULT_GIS_URL = (
    "https://gistech.countyofkane.org/arcgis/rest/services/KanePINList/MapServer/0"
)

TIMEOUT_SECONDS = 10

# Street-type abbreviation maps (same as Cook County connector)
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

# Kane County property-type mapping
_USE_CODE_MAP = {
    'single family':  'single_family',
    'single-family':  'single_family',
    'residential':    'single_family',
    'multi family':   'multi_family',
    'multi-family':   'multi_family',
    'multifamily':    'multi_family',
    'two family':     'multi_family',
    'commercial':     'commercial',
    'industrial':     'commercial',
    'farmland':       'land',
    'farm':           'land',
    'vacant':         'land',
    'condominium':    'condo',
    'townhouse':      'single_family',
}


def _normalise_address(address: str) -> str:
    """Normalise address string for Kane County ArcGIS LIKE lookup."""
    street_part = address.split(',')[0].strip().upper()
    for pattern, abbr in _DIRECTION_MAP.items():
        street_part = re.sub(pattern, abbr, street_part)
    for pattern, abbr in _SUFFIX_MAP.items():
        street_part = re.sub(pattern, abbr, street_part)
    # Strip unit suffixes — Kane stores addresses without unit numbers
    street_part = re.sub(
        r'\s+(APT|UNIT|STE|SUITE|#|FL|FLOOR|FRNT|FRONT|REAR|BSMT|BS)\s*\S*$',
        '', street_part
    )
    street_part = re.sub(r'\s+(\d+[A-Z\-]*|\d+(ST|ND|RD|TH))$', '', street_part)
    return street_part.strip()


def _map_use_code(use_code_description: Optional[str]) -> Optional[str]:
    """Map Kane County UseCodeDescription to internal property_type."""
    if not use_code_description:
        return None
    lower = use_code_description.strip().lower()
    for key, val in _USE_CODE_MAP.items():
        if key in lower:
            return val
    return None


def _map_attributes(attrs: dict) -> GISParcel:
    """Map Kane County ArcGIS attributes to GISParcel."""
    return GISParcel(
        county_assessor_pin=attrs.get('PIN') or None,
        property_type=_map_use_code(attrs.get('UseCodeDescription')),
        year_built=None,       # not in this dataset
        square_footage=None,   # not in this dataset
        bedrooms=None,         # not in this dataset
        bathrooms=None,        # not in this dataset
        lot_size=None,         # not in this dataset
        owner_first_name=None, # mailing name is org/full name, not split
        owner_last_name=None,
        mailing_address=attrs.get('MailingAddress') or None,
        mailing_city=attrs.get('MailingCity') or None,
        mailing_state=attrs.get('MailingState') or None,
        mailing_zip=attrs.get('MailingZip') or None,
    )


class KaneCountyGISConnector(GISConnector):
    """GIS connector for Kane County, IL (Aurora, Elgin, Geneva, St. Charles, etc.).

    Uses the publicly accessible KanePINList ArcGIS MapServer.
    No API key required.
    """

    def __init__(self) -> None:
        self._base_url = os.environ.get(
            'KANE_COUNTY_GIS_URL', _DEFAULT_GIS_URL
        ).rstrip('/')

    @property
    def connector_name(self) -> str:
        return 'kane_county_gis'

    @property
    def market(self) -> str:
        return 'kane_county_il'

    def _query(self, where_clause: str) -> Optional[GISParcel]:
        """Execute a query against the Kane County MapServer."""
        params = {
            'where': where_clause,
            'outFields': 'PIN,SiteAddress,SiteCity,SiteZip,MailingAddress,MailingCity,MailingState,MailingZip,UseCodeDescription',
            'returnGeometry': 'false',
            'f': 'json',
            'resultRecordCount': 1,
        }
        url = f"{self._base_url}/query"
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                logger.error("KaneCountyGIS API error: %s", data['error'])
                return None
            features = data.get('features', [])
            if not features:
                return None
            parcel = _map_attributes(features[0].get('attributes', {}))
            logger.debug("KaneCountyGIS: PIN=%s", parcel.county_assessor_pin)
            return parcel
        except Exception as exc:
            logger.error("KaneCountyGIS query error: %s", exc)
            return None

    def lookup_by_address(self, address: str) -> Optional[GISParcel]:
        """Look up a parcel by street address using a LIKE query on SiteAddress."""
        normalised = _normalise_address(address)
        if not normalised:
            return None
        # Exact match first
        safe = normalised.replace("'", "''")
        result = self._query(f"UPPER(SiteAddress) = '{safe}'")
        if result:
            return result
        # Fallback: LIKE on first 3 tokens
        tokens = normalised.split()
        if len(tokens) >= 2:
            prefix = ' '.join(tokens[:3]) if len(tokens) >= 3 else ' '.join(tokens[:2])
            # Escape LIKE wildcards (and the escape char) in the user value,
            # then double single quotes; the trailing % is our intended wildcard.
            safe_prefix = _escape_like(prefix).replace("'", "''")
            result = self._query(
                f"UPPER(SiteAddress) LIKE '{safe_prefix}%' ESCAPE '\\'"
            )
        return result

    def lookup_by_pin(self, pin: str) -> Optional[GISParcel]:
        """Look up a parcel by PIN."""
        safe_pin = pin.replace("'", "''")
        return self._query(f"PIN = '{safe_pin}'")


# ---------------------------------------------------------------------------
# Registry registration — runs at import time
# ---------------------------------------------------------------------------
GISConnectorRegistry['kane_county_il'] = KaneCountyGISConnector()
