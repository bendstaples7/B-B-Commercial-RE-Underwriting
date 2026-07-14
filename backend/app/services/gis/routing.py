"""GIS connector routing — picks the right connector for a lead's county/state.

Usage:
    from app.services.gis.routing import connector_for_lead

    connector = connector_for_lead(lead)
    if connector:
        outcome = ingestion_svc._enrich_with_gis(lead, connector, job_id)

Routing rules (evaluated in order):
  1. DuPage County, IL  → dupage_il  (DuPageGISConnector)
  2. Cook County, IL    → cook_county_il  (CookCountyGISConnector)
     Triggered by: property_state='IL' AND property_city in the Cook County
     city list, OR property_city='Chicago', OR property_city='CHICAGO'

Adding a new county:
  - Create a connector file in app/services/gis/ that registers itself in
    GISConnectorRegistry at import time.
  - Add a rule in _resolve_market() below.
  - Import the connector module in _ensure_connectors_loaded().
"""

from __future__ import annotations

import logging
import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.gis.base import GISConnector

logger = logging.getLogger(__name__)

# Matches "IL", "Illinois", "IL 60647", "IL 60647-1234"
_STATE_ZIP_RE = re.compile(
    r'^(?P<state>IL|ILLINOIS)\b(?:\s+(?P<zip>\d{5}(?:-\d{4})?))?$',
    re.IGNORECASE,
)
_COUNTRY_TOKENS = frozenset({'USA', 'US', 'UNITED STATES'})

# ---------------------------------------------------------------------------
# Cities/townships that are in Cook County, IL (non-exhaustive; covers the
# common cases.  DuPage cities are handled by the dupage_il rule first.)
# ---------------------------------------------------------------------------
_COOK_COUNTY_CITIES = frozenset({
    'CHICAGO', 'EVANSTON', 'SKOKIE', 'OAK PARK', 'CICERO', 'BERWYN',
    'CALUMET CITY', 'HARVEY', 'DOLTON', 'EVERGREEN PARK', 'BLUE ISLAND',
    'TINLEY PARK', 'OAK LAWN', 'ORLAND PARK', 'PALOS HILLS', 'BRIDGEVIEW',
    'ALSIP', 'WORTH', 'CHICAGO RIDGE', 'MIDLOTHIAN', 'COUNTRY CLUB HILLS',
    'HOMEWOOD', 'FLOSSMOOR', 'MATTESON', 'PARK FOREST', 'OLYMPIA FIELDS',
    'SOUTH HOLLAND', 'LANSING', 'GLENWOOD', 'SAUK VILLAGE', 'STEGER',
    'RICHTON PARK', 'UNIVERSITY PARK', 'CHICAGO HEIGHTS', 'FORD HEIGHTS',
    'HAZEL CREST', 'MARKHAM', 'OAK FOREST', 'ROBBINS', 'POSEN',
    'RIVERDALE', 'BURNHAM', 'DIXMOOR', 'PHOENIX', 'SOUTH CHICAGO HEIGHTS',
    'THORNTON', 'LYNWOOD', 'EAST HAZEL CREST', 'GLENWOOD',
    'NILES', 'PARK RIDGE', 'DES PLAINES', 'ROSEMONT', 'SCHILLER PARK',
    'FRANKLIN PARK', 'NORTHLAKE', 'MELROSE PARK', 'BELLWOOD', 'BROADVIEW',
    'HILLSIDE', 'WESTCHESTER', 'MAYWOOD', 'FOREST PARK', 'RIVER FOREST',
    'RIVER GROVE', 'ELMWOOD PARK', 'NORRIDGE', 'HARWOOD HEIGHTS',
    'ELMHURST',  # straddles DuPage/Cook — Cook side registered here
    'ADDISON',   # straddles; DuPage connector will match first if county='DuPage'
    'VILLA PARK', 'BENSENVILLE', 'WOOD DALE', 'ELK GROVE VILLAGE',
    'MOUNT PROSPECT', 'PROSPECT HEIGHTS', 'WHEELING', 'BUFFALO GROVE',
    'PALATINE', 'ROLLING MEADOWS', 'ARLINGTON HEIGHTS', 'HOFFMAN ESTATES',
    'HANOVER PARK', 'STREAMWOOD', 'BARTLETT',
    'BARRINGTON',
    'NORTHBROOK', 'GLENVIEW', 'MORTON GROVE', 'LINCOLNWOOD', 'CHICAGO',
    'WILMETTE', 'KENILWORTH', 'WINNETKA', 'GLENCOE', 'HIGHLAND PARK',
    'DEERFIELD', 'LAKE FOREST',
})

# DuPage County city list (key ones — connector is authoritative for these)
_DUPAGE_COUNTY_CITIES = frozenset({
    'WHEATON', 'NAPERVILLE', 'AURORA', 'BOLINGBROOK', 'DOWNERS GROVE',
    'GLEN ELLYN', 'LOMBARD', 'CAROL STREAM', 'LISLE', 'WOODRIDGE',
    'WARRENVILLE', 'WEST CHICAGO', 'WINFIELD', 'GLENDALE HEIGHTS', 'GLENDALE HTS',
    'DARIEN', 'WESTMONT', 'CLARENDON HILLS', 'HINSDALE', 'BURR RIDGE',
    'WILLOWBROOK', 'VILLA PARK', 'OAKBROOK TERRACE', 'OAK BROOK',
    'ROSELLE', 'BLOOMINGDALE', 'ITASCA', 'MEDINAH', 'ADDISON',
    'WOOD DALE', 'BENSENVILLE', 'ELK GROVE VILLAGE',
})

# Kane County city list
_KANE_COUNTY_CITIES = frozenset({
    'ALGONQUIN', 'AURORA', 'BATAVIA', 'BIG ROCK', 'BURLINGTON',
    'CAMPTON HILLS', 'CARPENTERSVILLE', 'EAST DUNDEE', 'ELBURN', 'ELGIN',
    'GENEVA', 'GILBERTS', 'HAMPSHIRE', 'KANEVILLE', 'LILY LAKE',
    'MAPLE PARK', 'MONTGOMERY', 'NORTH AURORA', 'PINGREE GROVE',
    'PLATO CENTER', 'SLEEPY HOLLOW', 'SOUTH ELGIN', 'ST CHARLES',
    'SAINT CHARLES', 'SUGAR GROVE', 'WEST DUNDEE',
})

# Lake County city list
_LAKE_COUNTY_CITIES = frozenset({
    'ANTIOCH', 'BARRINGTON', 'BEACH PARK', 'BUFFALO GROVE',
    'DEERFIELD', 'FOX LAKE', 'GRAYSLAKE', 'GURNEE',
    'HIGHLAND PARK', 'HIGHWOOD', 'ISLAND LAKE', 'LAKE BLUFF',
    'LAKE FOREST', 'LAKE VILLA', 'LAKE ZURICH', 'LIBERTYVILLE',
    'LINCOLNSHIRE', 'LINDENHURST', 'MUNDELEIN', 'NORTH CHICAGO',
    'NORTH BARRINGTON', 'ROUND LAKE', 'ROUND LAKE BEACH',
    'ROUND LAKE HEIGHTS', 'ROUND LAKE PARK', 'THIRD LAKE',
    'TOWER LAKES', 'VERNON HILLS', 'WADSWORTH', 'WAUKEGAN',
    'WINTHROP HARBOR', 'ZION', 'LAKE COUNTY',
})


def _ensure_connectors_loaded() -> None:
    """Import connector modules so they self-register into GISConnectorRegistry."""
    # Each import is a no-op if the module is already loaded.
    import app.services.gis.dupage_gis_connector       # noqa: F401
    import app.services.gis.cook_county_gis_connector  # noqa: F401
    import app.services.gis.kane_county_gis_connector  # noqa: F401
    import app.services.gis.lake_county_gis_connector  # noqa: F401


def parse_city_state_zip_from_address(
    address: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Infer city, IL state, and optional ZIP from a comma-separated address.

    Accepts common Google Places shapes, e.g.:
      - ``123 Main St, Chicago, IL``
      - ``123 Main St, Chicago, IL 60647``
      - ``123 Main St, Chicago, IL 60647, USA``
    """
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) < 2:
        return None, None, None

    if parts[-1].upper() in _COUNTRY_TOKENS:
        parts = parts[:-1]
    if len(parts) < 2:
        return None, None, None

    match = _STATE_ZIP_RE.match(parts[-1].strip())
    if not match:
        return None, None, None

    city = parts[-2]
    return city, "IL", match.group("zip")


def parse_city_state_from_address(address: str) -> tuple[Optional[str], Optional[str]]:
    """Infer city and IL state from a comma-separated address string."""
    city, state, _zip_code = parse_city_state_zip_from_address(address)
    return city, state


def _resolve_market(lead) -> Optional[str]:
    """Return the GISConnectorRegistry market key for this lead, or None."""
    city  = (getattr(lead, 'property_city',  None) or '').strip().upper()
    state = (getattr(lead, 'property_state', None) or '').strip().upper()

    if state not in ('IL', 'ILLINOIS', ''):
        # Only IL connectors exist today; other states have no GIS connector.
        return None

    # DuPage first (more specific — avoids Cook catch-all for border cities)
    if city in _DUPAGE_COUNTY_CITIES:
        return 'dupage_il'

    # Kane County
    if city in _KANE_COUNTY_CITIES:
        return 'kane_county_il'

    # Lake County
    if city in _LAKE_COUNTY_CITIES:
        return 'lake_county_il'

    # Cook County — Chicago and suburbs
    if city in _COOK_COUNTY_CITIES or city == 'CHICAGO':
        return 'cook_county_il'

    # No explicit county/city signal — do NOT default-route to any connector.
    # Previously a blank/unknown city on an IL lead fell back to DuPage, which
    # mis-attributed out-of-area and unknown-location leads to DuPage and could
    # fire address lookups against the wrong county. Routing now requires a
    # recognised city (an explicit signal); blank/empty or unrecognised inputs
    # return None (no connector) per the existing ambiguous-route pattern.
    return None


def connector_for_lead(lead) -> Optional['GISConnector']:
    """Return the appropriate GISConnector for a lead, or None if unsupported.

    Args:
        lead: A Lead / Property ORM instance with property_city and
              property_state attributes.

    Returns:
        A GISConnector instance, or None when no connector covers the lead's
        location (e.g. out-of-state, unsupported county).
    """
    from app.services.gis.base import GISConnectorRegistry

    _ensure_connectors_loaded()

    market = _resolve_market(lead)
    if not market:
        logger.debug(
            "connector_for_lead: no GIS connector for city=%r state=%r",
            getattr(lead, 'property_city', None),
            getattr(lead, 'property_state', None),
        )
        return None

    connector = GISConnectorRegistry.get(market)
    if not connector:
        logger.warning(
            "connector_for_lead: market %r mapped but connector not in registry",
            market,
        )
    return connector
