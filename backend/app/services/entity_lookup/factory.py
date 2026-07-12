"""Factory for entity-lookup providers."""
from __future__ import annotations

import logging
import os
from typing import Optional, Union

from app.services.entity_lookup.ilsos_bulk import IllinoisSosBulkProvider
from app.services.entity_lookup.opencorporates import IllinoisOpenCorporatesProvider

logger = logging.getLogger(__name__)

EntityLookupProviderImpl = Union[IllinoisSosBulkProvider, IllinoisOpenCorporatesProvider]


def get_entity_lookup_provider(
    provider_name: Optional[str] = None,
) -> EntityLookupProviderImpl:
    """Return the configured entity-lookup provider.

    Default is free ``ilsos_bulk``. Set ``ENTITY_LOOKUP_PROVIDER=opencorporates``
    (plus API token) only when intentionally using the paid adapter.
    """
    chosen = (
        provider_name
        or os.environ.get("ENTITY_LOOKUP_PROVIDER")
        or "ilsos_bulk"
    ).strip().lower()

    if chosen in ("ilsos_bulk", "ilsos", "illinois_sos", "sos_bulk"):
        return IllinoisSosBulkProvider()
    if chosen in ("opencorporates", "oc", "illinois_opencorporates"):
        return IllinoisOpenCorporatesProvider()

    logger.warning(
        "Unknown ENTITY_LOOKUP_PROVIDER=%r; defaulting to ilsos_bulk", chosen,
    )
    return IllinoisSosBulkProvider()
