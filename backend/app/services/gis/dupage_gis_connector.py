"""DuPage County GIS connector implementation.

Uses the publicly accessible ParcelsWithRealEstateCC FeatureServer:
  https://gis.dupageco.org/arcgis/rest/services/DuPage_County_IL/
      ParcelsWithRealEstateCC/FeatureServer/0

Override with the DUPAGE_GIS_URL environment variable when needed.

Field mapping (live API response → GISParcel):
  PIN          → county_assessor_pin
  PROPNAME     → owner (split into first/last on comma)
  PROPADDRL1   → property address street
  BILLADDRL1   → mailing_address
  BILLADDRL2   → parsed into mailing_city / mailing_state / mailing_zip
  REA017_PROP_CLASS → property_type

Note: The parcel dataset does NOT include year_built, square_footage,
bedrooms, bathrooms, or lot_size — those fields will remain null.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import requests

from .base import GISConnector, GISConnectorRegistry, GISParcel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Correct DuPage County GIS FeatureServer URL
# ---------------------------------------------------------------------------
_DEFAULT_GIS_URL = (
    "https://gis.dupageco.org/arcgis/rest/services/"
    "DuPage_County_IL/ParcelsWithRealEstateCC/FeatureServer/0"
)

# Fields to request from the API
_OUT_FIELDS = ",".join([
    "PIN", "PROPNAME",
    "PROPADDRL1", "PROPADDRL2",
    "BILLADDRL1", "BILLADDRL2",
    "REA017_PROP_CLASS",
])

# "JOHN SMITH      " or "SMITH, JOHN A   "
_NAME_SPLIT_RE = re.compile(r',\s*')


def _safe_str(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _parse_owner_name(propname: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split PROPNAME into (first_name, last_name).

    The field typically has one of two formats:
      "SMITH, JOHN A    "  →  last="SMITH", first="JOHN A"
      "JOHN SMITH       "  →  last="SMITH", first="JOHN"
    Returns (first, last).
    """
    if not propname:
        return None, None
    name = propname.strip()
    if not name:
        return None, None

    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        last = parts[0] if parts[0] else None
        first = parts[1] if len(parts) > 1 and parts[1] else None
        return first, last
    else:
        # "JOHN SMITH" or "SMITH JOHN" — take last word as last name
        parts = name.split()
        if len(parts) == 1:
            return None, parts[0]
        return ' '.join(parts[:-1]), parts[-1]


def _parse_city_state_zip(addr_line2: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse 'ROSELLE IL 60172' into (city, state, zip).

    The BILLADDRL2 / PROPADDRL2 field is formatted as 'CITY ST ZIPCODE'.
    """
    if not addr_line2:
        return None, None, None
    parts = addr_line2.strip().split()
    if len(parts) >= 3:
        # Last token is zip, second-to-last is state, rest is city
        zip_code = parts[-1]
        state = parts[-2]
        city = ' '.join(parts[:-2])
        return city or None, state or None, zip_code or None
    elif len(parts) == 2:
        return parts[0], parts[1], None
    else:
        return addr_line2.strip() or None, None, None


def _map_attributes(attrs: dict) -> GISParcel:
    """Map ParcelsWithRealEstateCC attributes to GISParcel."""
    first_name, last_name = _parse_owner_name(attrs.get("PROPNAME"))
    mailing_city, mailing_state, mailing_zip = _parse_city_state_zip(attrs.get("BILLADDRL2"))

    return GISParcel(
        county_assessor_pin=_safe_str(attrs.get("PIN")),
        property_type=_safe_str(attrs.get("REA017_PROP_CLASS")),
        year_built=None,        # not in this dataset
        square_footage=None,    # not in this dataset
        bedrooms=None,          # not in this dataset
        bathrooms=None,         # not in this dataset
        lot_size=None,          # not in this dataset
        owner_first_name=first_name,
        owner_last_name=last_name,
        mailing_address=_safe_str(attrs.get("BILLADDRL1")),
        mailing_city=mailing_city,
        mailing_state=mailing_state,
        mailing_zip=mailing_zip,
    )


class DuPageGISConnector(GISConnector):
    """Concrete GIS connector for DuPage County, IL parcel dataset.

    Uses the ParcelsWithRealEstateCC FeatureServer which is the only
    publicly queryable bulk-capable service on gis.dupageco.org.
    """

    TIMEOUT_SECONDS: int = 10

    def __init__(self) -> None:
        self._base_url: str = os.environ.get("DUPAGE_GIS_URL", _DEFAULT_GIS_URL).rstrip("/")

    @property
    def connector_name(self) -> str:
        return "dupage_gis"

    @property
    def market(self) -> str:
        return "dupage_il"

    def _query_endpoint(self, where_clause: str) -> Optional[GISParcel]:
        params = {
            "where": where_clause,
            "outFields": _OUT_FIELDS,
            "returnGeometry": "false",
            "f": "json",
        }
        url = f"{self._base_url}/query"
        logger.debug("DuPageGISConnector: querying %s where=%r", url, where_clause)

        response = requests.get(url, params=params, timeout=self.TIMEOUT_SECONDS)
        response.raise_for_status()

        data = response.json()
        if "error" in data:
            logger.error("DuPageGISConnector: API error %s", data["error"])
            return None

        features = data.get("features", [])
        if not features:
            return None

        parcel = _map_attributes(features[0].get("attributes", {}))
        logger.debug("DuPageGISConnector: PIN=%s", parcel.county_assessor_pin)
        return parcel

    def lookup_by_address(self, address: str) -> Optional[GISParcel]:
        """Look up a parcel by property address (PROPADDRL1 LIKE match).

        Strips unit-number suffixes before querying — DuPage stores addresses
        without unit numbers (e.g. '107 MAIN ST' not '107 MAIN ST APT 2').
        """
        import re
        # Normalise to uppercase and strip explicit unit suffixes (APT/UNIT/...).
        street_part = address.split(',')[0].strip().upper()
        street_part = re.sub(
            r'\s+(APT|UNIT|STE|SUITE|#|FL|FLOOR|FRNT|FRONT|REAR|BSMT|BS)\s*\S*$',
            '', street_part
        )
        # Strip a *bare* trailing unit number ONLY when it directly follows a
        # recognised street-type suffix (e.g. "107 MAIN ST 2" -> "107 MAIN ST").
        # The previous "strip any trailing number" rule was too broad: it also
        # removed legitimate content such as route/highway numbers
        # ("200 ROUTE 59") and numbered streets ("300 5TH"). Requiring a
        # preceding suffix keeps those intact while still dropping true unit
        # numbers that DuPage's dataset does not store.
        street_part = re.sub(
            r'\b(ST|STREET|AVE|AVENUE|BLVD|BOULEVARD|CIR|CIRCLE|CT|COURT|'
            r'DR|DRIVE|LN|LANE|PL|PLACE|RD|ROAD|TER|TERRACE|WAY|PKWY|PARKWAY|'
            r'CRES|CRESCENT|SQ|SQUARE|TRL|TRAIL)\s+\d+[A-Z]?$',
            r'\1',
            street_part,
        )
        street_part = street_part.strip()
        # Guard against an empty normalised address: an empty LIKE pattern
        # ('%%') would match every parcel. Report no match instead of querying.
        if not street_part:
            return None
        safe = street_part.replace("'", "''").replace("%", r"\%").replace("_", r"\_")
        where_clause = f"UPPER(PROPADDRL1) LIKE '%{safe}%' ESCAPE '\\'"
        return self._query_endpoint(where_clause)

    def lookup_by_pin(self, pin: str) -> Optional[GISParcel]:
        """Look up a parcel by county assessor PIN."""
        safe_pin = pin.replace("'", "''")
        where_clause = f"PIN = '{safe_pin}'"
        return self._query_endpoint(where_clause)


# ---------------------------------------------------------------------------
# Registry registration
# ---------------------------------------------------------------------------
GISConnectorRegistry["dupage_il"] = DuPageGISConnector()
