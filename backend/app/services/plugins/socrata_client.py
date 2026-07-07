"""Shared Socrata HTTP helpers for Cook County and Chicago data plugins."""
from __future__ import annotations

import logging
import os
import time
from typing import Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

_COOK_COUNTY_BASE = "https://datacatalog.cookcountyil.gov/resource"
_CHICAGO_BASE = "https://data.cityofchicago.org/resource"


def _app_token(portal: str) -> str:
    if portal == "chicago":
        return (
            os.getenv("CHICAGO_DATA_API_KEY", "")
            or os.getenv("SOCRATA_APP_TOKEN", "")
        )
    return (
        os.getenv("COOK_COUNTY_APP_TOKEN", "")
        or os.getenv("SOCRATA_APP_TOKEN", "")
    )


def escape_soql_literal(value: str) -> str:
    """Escape a string for use inside a SoQL single-quoted literal."""
    return (value or "").replace("'", "''")


def socrata_get(
    dataset_id: str,
    *,
    params: Optional[dict] = None,
    portal: str = "cook_county",
    max_retries: int = 2,
    timeout: int = 30,
) -> list[dict]:
    """Fetch rows from a Socrata dataset with optional app-token auth."""
    base = _CHICAGO_BASE if portal == "chicago" else _COOK_COUNTY_BASE
    url = f"{base}/{dataset_id}.json"
    if params:
        url = f"{url}?{urlencode(params)}"

    token = _app_token(portal)
    header_variants: list[dict[str, str]] = []
    if token:
        header_variants.append({"X-App-Token": token})
    header_variants.append({})

    last_exc: Optional[Exception] = None
    for headers in header_variants:
        using_token = bool(headers.get("X-App-Token"))
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, headers=headers, timeout=timeout)
                if response.ok:
                    data = response.json()
                    return data if isinstance(data, list) else []
                if (
                    using_token
                    and response.status_code == 403
                    and "Invalid app_token" in response.text
                ):
                    logger.warning(
                        "Socrata %s rejected app token; retrying without authentication",
                        dataset_id,
                    )
                    break
                last_exc = requests.HTTPError(
                    f"HTTP {response.status_code} for {dataset_id}",
                    response=response,
                )
                logger.warning(
                    "Socrata %s attempt %d/%d failed: HTTP %s",
                    dataset_id,
                    attempt,
                    max_retries,
                    response.status_code,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "Socrata %s attempt %d/%d error: %s",
                    dataset_id,
                    attempt,
                    max_retries,
                    exc,
                )
            if attempt < max_retries:
                time.sleep(2)

    logger.warning("Socrata fetch exhausted retries for %s: %s", dataset_id, last_exc)
    return []
