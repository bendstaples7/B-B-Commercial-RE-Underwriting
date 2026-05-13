"""
RentCastService — fetches market rent estimates from the RentCast API
with a 90-day database cache to avoid redundant API calls.

If a cached result exists for the same address + unit characteristics
and was fetched within 90 days, the cached value is returned without
calling the API.

API docs: https://developers.rentcast.io/reference/rent-estimate-long-term
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import requests

logger = logging.getLogger(__name__)

_RENTCAST_BASE_URL = "https://api.rentcast.io/v1"
_TIMEOUT = (10, 30)  # (connect, read) seconds
_CACHE_TTL_DAYS = 90


def _normalize_address(address: str) -> str:
    """Normalize an address string for use as a cache key."""
    return re.sub(r'\s+', ' ', address.lower().strip())


def _build_cache_key(
    address_key: str,
    unit_type_label: str,
    bedrooms: int | None,
    bathrooms: float | None,
    square_footage: int | None,
) -> str:
    """Build a deterministic cache key string from all key fields.

    NULLs are replaced with empty string so the key is stable and unique
    even when optional fields are absent. This avoids the SQL NULL != NULL
    problem that would allow duplicate rows through a multi-column unique
    constraint on nullable columns.
    """
    parts = [
        address_key,
        unit_type_label,
        str(bedrooms) if bedrooms is not None else '',
        str(bathrooms) if bathrooms is not None else '',
        str(square_footage) if square_footage is not None else '',
    ]
    return '|'.join(parts)


class RentCastService:
    """Fetches rent estimates from the RentCast API with DB caching.

    Requires a Flask app context to be active (for DB access).
    """

    def __init__(self) -> None:
        api_key = os.environ.get("RENTCAST_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "RENTCAST_API_KEY is not set. "
                "Add it to your .env file to enable market rent research."
            )
        self._api_key = api_key
        self._headers = {
            "X-Api-Key": self._api_key,
            "Accept": "application/json",
        }

    def get_rent_estimate(
        self,
        address: str,
        property_type: str = "Multi-Family",
        bedrooms: int | None = None,
        bathrooms: float | None = None,
        square_footage: int | None = None,
        unit_type_label: str = "",
    ) -> dict[str, Any]:
        """Fetch a long-term rent estimate, using the DB cache when available.

        Parameters
        ----------
        address:
            Full property address (e.g. "7616 N Rogers Ave, Chicago, IL 60626").
        property_type:
            RentCast property type. Use "Multi-Family" for apartment buildings.
        bedrooms:
            Number of bedrooms for the unit type.
        bathrooms:
            Number of bathrooms for the unit type.
        square_footage:
            Square footage of the unit type.
        unit_type_label:
            Unit type label (e.g. "2BR/1BA") — used as part of the cache key.

        Returns
        -------
        dict with keys:
            - ``market_rent_estimate``: Point estimate (float or None)
            - ``market_rent_low``: Low end of range (float or None)
            - ``market_rent_high``: High end of range (float or None)
            - ``comparables_count``: Number of comparable listings used
            - ``from_cache``: True if the result came from the DB cache
        """
        address_key = _normalize_address(address)

        # --- Check cache first ---
        cached = self._get_cached(address_key, unit_type_label, bedrooms, bathrooms, square_footage)
        if cached is not None:
            logger.info(
                "RentCastService: cache hit for address=%r unit=%r (fetched %s)",
                address_key, unit_type_label, cached.fetched_at.date(),
            )
            return {
                "market_rent_estimate": float(cached.rent_estimate) if cached.rent_estimate is not None else None,
                "market_rent_low": float(cached.rent_range_low) if cached.rent_range_low is not None else None,
                "market_rent_high": float(cached.rent_range_high) if cached.rent_range_high is not None else None,
                "comparables_count": cached.comparables_count,
                "from_cache": True,
            }

        # --- Cache miss — call the API ---
        result = self._fetch_from_api(address, property_type, bedrooms, bathrooms, square_footage)
        result["from_cache"] = False

        # --- Store in cache ---
        self._store_cache(
            address_key=address_key,
            unit_type_label=unit_type_label,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            square_footage=square_footage,
            rent_estimate=result.get("market_rent_estimate"),
            rent_range_low=result.get("market_rent_low"),
            rent_range_high=result.get("market_rent_high"),
            comparables_count=result.get("comparables_count", 0),
        )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_cached(
        self,
        address_key: str,
        unit_type_label: str,
        bedrooms: int | None,
        bathrooms: float | None,
        square_footage: int | None,
    ):
        """Return a fresh RentCastCache row or None."""
        try:
            from app.models.rentcast_cache import RentCastCache
            cutoff = datetime.utcnow() - timedelta(days=_CACHE_TTL_DAYS)
            cache_key = _build_cache_key(address_key, unit_type_label, bedrooms, bathrooms, square_footage)
            return (
                RentCastCache.query
                .filter_by(cache_key=cache_key)
                .filter(RentCastCache.fetched_at >= cutoff)
                .order_by(RentCastCache.fetched_at.desc())
                .first()
            )
        except Exception as exc:
            logger.warning("RentCastService: cache lookup failed: %s", exc)
            return None

    def _store_cache(
        self,
        address_key: str,
        unit_type_label: str,
        bedrooms: int | None,
        bathrooms: float | None,
        square_footage: int | None,
        rent_estimate: float | None,
        rent_range_low: float | None,
        rent_range_high: float | None,
        comparables_count: int,
    ) -> None:
        """Upsert a RentCastCache row."""
        try:
            from app import db
            from app.models.rentcast_cache import RentCastCache

            cache_key = _build_cache_key(address_key, unit_type_label, bedrooms, bathrooms, square_footage)

            # Delete any existing entry for this key (upsert via delete+insert)
            RentCastCache.query.filter_by(cache_key=cache_key).delete()

            entry = RentCastCache(
                address_key=address_key,
                unit_type_label=unit_type_label,
                bedrooms=bedrooms,
                bathrooms=Decimal(str(bathrooms)) if bathrooms is not None else None,
                square_footage=square_footage,
                cache_key=cache_key,
                rent_estimate=Decimal(str(rent_estimate)) if rent_estimate is not None else None,
                rent_range_low=Decimal(str(rent_range_low)) if rent_range_low is not None else None,
                rent_range_high=Decimal(str(rent_range_high)) if rent_range_high is not None else None,
                comparables_count=comparables_count,
                fetched_at=datetime.utcnow(),
            )
            db.session.add(entry)
            db.session.commit()
            logger.info(
                "RentCastService: cached result for address=%r unit=%r estimate=%s",
                address_key, unit_type_label, rent_estimate,
            )
        except Exception as exc:
            logger.warning("RentCastService: cache write failed: %s", exc)
            try:
                from app import db
                db.session.rollback()
            except Exception:
                pass

    def _fetch_from_api(
        self,
        address: str,
        property_type: str,
        bedrooms: int | None,
        bathrooms: float | None,
        square_footage: int | None,
    ) -> dict[str, Any]:
        """Call the RentCast API and return the result dict."""
        params: dict[str, Any] = {
            "address": address,
            "propertyType": property_type,
            "compCount": 10,
        }
        if bedrooms is not None:
            params["bedrooms"] = bedrooms
        if bathrooms is not None:
            params["bathrooms"] = bathrooms
        if square_footage is not None:
            params["squareFootage"] = square_footage

        try:
            response = requests.get(
                f"{_RENTCAST_BASE_URL}/avm/rent/long-term",
                headers=self._headers,
                params=params,
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.warning("RentCastService: request timed out for address=%r", address)
            return {"market_rent_estimate": None, "market_rent_low": None,
                    "market_rent_high": None, "comparables_count": 0}
        except requests.exceptions.HTTPError as exc:
            logger.warning(
                "RentCastService: HTTP %s for address=%r: %s",
                exc.response.status_code, address, exc.response.text[:200],
            )
            return {"market_rent_estimate": None, "market_rent_low": None,
                    "market_rent_high": None, "comparables_count": 0}

        data = response.json()
        rent = data.get("rent")
        low = data.get("rentRangeLow")
        high = data.get("rentRangeHigh")
        comparables = data.get("comparables", [])

        logger.info(
            "RentCastService: API result address=%r estimate=%s low=%s high=%s comps=%d",
            address, rent, low, high, len(comparables),
        )

        return {
            "market_rent_estimate": float(rent) if rent is not None else None,
            "market_rent_low": float(low) if low is not None else None,
            "market_rent_high": float(high) if high is not None else None,
            "comparables_count": len(comparables),
        }
