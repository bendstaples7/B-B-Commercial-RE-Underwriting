"""HubSpotClientService — wraps all HubSpot API calls with GET-only enforcement."""
import logging
import os
from typing import Iterator

import requests

from app.exceptions import (
    ExternalServiceError,
    HubSpotAuthenticationError,
    HubSpotRateLimitError,
    HubSpotReadOnlyViolation,
)
from app.models.hubspot_config import HubSpotConfig

logger = logging.getLogger(__name__)


class HubSpotClientService:
    """Read-only HubSpot API client.

    Decrypts the Fernet-encrypted token stored in ``HubSpotConfig`` and
    provides paginated iterators for all four importable object types
    (deals, contacts, companies, engagements).  Every outbound request is
    a GET; any attempt to call a mutating method raises
    ``HubSpotReadOnlyViolation``.
    """

    BASE_URL = "https://api.hubapi.com"
    PAGE_SIZE = 100
    TIMEOUT = 30  # seconds

    # ------------------------------------------------------------------ #
    # Construction / token management                                      #
    # ------------------------------------------------------------------ #

    def __init__(self, config: HubSpotConfig):
        """Decrypt the Fernet-encrypted token from *config* and store it."""
        self._token = self._decrypt_token(config.encrypted_token)

    def _decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt *encrypted_token* using the ``HUBSPOT_ENCRYPTION_KEY`` env var.

        The key must be a valid URL-safe base64-encoded 32-byte Fernet key.
        Raises ``ExternalServiceError`` if the environment variable is missing
        or the token cannot be decrypted.
        """
        from cryptography.fernet import Fernet, InvalidToken

        raw_key = os.environ.get("HUBSPOT_ENCRYPTION_KEY")
        if not raw_key:
            raise ExternalServiceError(
                "HUBSPOT_ENCRYPTION_KEY environment variable is not set",
                payload={"error_type": "hubspot_config_error"},
            )
        try:
            f = Fernet(raw_key.encode())
            return f.decrypt(encrypted_token.encode()).decode()
        except (InvalidToken, Exception) as exc:
            raise ExternalServiceError(
                f"Failed to decrypt HubSpot token: {exc}",
                payload={"error_type": "hubspot_config_error"},
            ) from exc

    @staticmethod
    def encrypt_token(raw_token: str) -> str:
        """Fernet-encrypt *raw_token* using the ``HUBSPOT_ENCRYPTION_KEY`` env var.

        Returns the encrypted token as a UTF-8 string suitable for storage in
        ``HubSpotConfig.encrypted_token``.

        Raises ``ExternalServiceError`` if the environment variable is missing.
        """
        from cryptography.fernet import Fernet

        raw_key = os.environ.get("HUBSPOT_ENCRYPTION_KEY")
        if not raw_key:
            raise ExternalServiceError(
                "HUBSPOT_ENCRYPTION_KEY environment variable is not set",
                payload={"error_type": "hubspot_config_error"},
            )
        f = Fernet(raw_key.encode())
        return f.encrypt(raw_token.encode()).decode()

    @staticmethod
    def encrypt_client_secret(raw_secret: str) -> str:
        """Fernet-encrypt a HubSpot client secret for storage.

        Delegates to :meth:`encrypt_token` since both the API token and the
        client secret use the same ``HUBSPOT_ENCRYPTION_KEY``.

        Returns the encrypted secret as a UTF-8 string suitable for storage in
        ``HubSpotConfig.encrypted_client_secret``.

        Raises ``ExternalServiceError`` if the environment variable is missing.
        """
        return HubSpotClientService.encrypt_token(raw_secret)

    @staticmethod
    def decrypt_client_secret(encrypted_secret: str) -> str:
        """Fernet-decrypt a stored HubSpot client secret.

        Args:
            encrypted_secret: The Fernet-encrypted client secret string as
                stored in ``HubSpotConfig.encrypted_client_secret``.

        Returns:
            The plaintext client secret.

        Raises:
            ``ExternalServiceError`` if ``HUBSPOT_ENCRYPTION_KEY`` is not set
            or the token cannot be decrypted.
        """
        from cryptography.fernet import Fernet, InvalidToken

        raw_key = os.environ.get("HUBSPOT_ENCRYPTION_KEY")
        if not raw_key:
            raise ExternalServiceError(
                "HUBSPOT_ENCRYPTION_KEY environment variable is not set",
                payload={"error_type": "hubspot_config_error"},
            )
        try:
            f = Fernet(raw_key.encode())
            return f.decrypt(encrypted_secret.encode()).decode()
        except (InvalidToken, Exception) as exc:
            raise ExternalServiceError(
                f"Failed to decrypt HubSpot client secret: {exc}",
                payload={"error_type": "hubspot_config_error"},
            ) from exc

    # ------------------------------------------------------------------ #
    # Read-only enforcement                                                #
    # ------------------------------------------------------------------ #

    def enforce_get_only(self, method: str) -> None:
        """Raise ``HubSpotReadOnlyViolation`` if *method* is not ``GET``.

        Call this at the top of any method that accepts a configurable HTTP
        verb to provide defence-in-depth against accidental write operations.
        """
        if method.upper() != "GET":
            logger.error("Attempted non-GET HubSpot call: %s", method)
            raise HubSpotReadOnlyViolation(
                f"Non-GET HubSpot call blocked: {method}"
            )

    # ------------------------------------------------------------------ #
    # Core HTTP helper                                                     #
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict = None) -> dict:
        """Execute a GET request against the HubSpot API.

        Args:
            path: API path relative to ``BASE_URL`` (e.g. ``/crm/v3/objects/deals``).
            params: Optional query-string parameters.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            HubSpotAuthenticationError: On HTTP 401 or 403.
            HubSpotRateLimitError: On HTTP 429; ``retry_after`` is populated
                from the ``Retry-After`` response header when present.
            ExternalServiceError: On HTTP 5xx or a request timeout exceeding
                ``TIMEOUT`` seconds.
        """
        url = f"{self.BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}

        try:
            resp = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=self.TIMEOUT,
            )
        except requests.exceptions.Timeout as exc:
            raise ExternalServiceError(
                f"HubSpot API request timed out after {self.TIMEOUT}s: {path}",
                payload={"error_type": "hubspot_timeout", "path": path},
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ExternalServiceError(
                f"HubSpot API request failed: {exc}",
                payload={"error_type": "hubspot_request_error", "path": path},
            ) from exc

        if resp.status_code in (401, 403):
            raise HubSpotAuthenticationError(
                f"HubSpot authentication failed (HTTP {resp.status_code})"
            )

        if resp.status_code == 429:
            retry_after_raw = resp.headers.get("Retry-After")
            retry_after = None
            if retry_after_raw is not None:
                try:
                    retry_after = int(retry_after_raw)
                except ValueError:
                    retry_after = None
            raise HubSpotRateLimitError(
                "HubSpot API rate limit exceeded",
                retry_after=retry_after,
            )

        if resp.status_code >= 500:
            raise ExternalServiceError(
                f"HubSpot API returned server error (HTTP {resp.status_code}): {path}",
                payload={
                    "error_type": "hubspot_server_error",
                    "path": path,
                    "status_code": resp.status_code,
                },
            )

        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Paginated object iterators                                           #
    # ------------------------------------------------------------------ #

    # Explicit property lists per object type.
    # HubSpot's CRM v3 API does not support "properties=all" — it silently
    # returns only the default system properties when given an unrecognised value.
    # We must explicitly name every property we want returned.
    _DEAL_PROPERTIES = [
        "dealname", "pipeline", "dealstage", "closedate", "amount",
        "county_assessor_pin", "pin", "address", "hs_object_id",
        "createdate", "hs_lastmodifieddate",
    ]
    _CONTACT_PROPERTIES = [
        "firstname", "lastname", "email", "phone", "mobilephone",
        "hs_object_id", "createdate", "hs_lastmodifieddate",
        "associatedcompanyid", "hs_analytics_source", "lifecyclestage",
        "hs_lead_source",
        # Custom properties — additional contact data stored as multi-line strings
        "additional_phone_numbers",  # e.g. "1) (630) 430-5720\n2) (630) 202-3839 CONFIRMED"
        "additional_addresses",      # e.g. "198 Karen Cir, Bolingbrook IL 60440\n..."
        "hs_additional_emails",      # additional email addresses
        # Standard address fields
        "address", "city", "state", "zip",
    ]
    _COMPANY_PROPERTIES = [
        "name", "type", "phone", "hs_object_id",
        "createdate", "hs_lastmodifieddate",
    ]

    def _fetch_all_crm_objects(self, object_type: str) -> Iterator[dict]:
        """Generic cursor-based paginator for CRM v3 object endpoints.

        Yields one record dict at a time.  Pagination uses the ``after``
        cursor returned in ``response['paging']['next']['after']``.

        Args:
            object_type: HubSpot object type slug, e.g. ``deals``, ``contacts``.
        """
        path = f"/crm/v3/objects/{object_type}"

        # Select the explicit property list for this object type.
        # Falling back to a minimal set if the type is unrecognised.
        prop_map = {
            "deals": self._DEAL_PROPERTIES,
            "contacts": self._CONTACT_PROPERTIES,
            "companies": self._COMPANY_PROPERTIES,
        }
        properties = ",".join(prop_map.get(object_type, ["hs_object_id"]))

        params: dict = {
            "limit": self.PAGE_SIZE,
            "properties": properties,
        }

        while True:
            response = self._get(path, params=params)
            results = response.get("results", [])
            for record in results:
                yield record

            # Advance cursor or stop
            paging = response.get("paging", {})
            next_cursor = paging.get("next", {}).get("after")
            if not next_cursor:
                break
            params["after"] = next_cursor

    def fetch_all_deals(self) -> Iterator[dict]:
        """Yield every deal from HubSpot using cursor-based pagination.

        Calls ``GET /crm/v3/objects/deals`` with ``limit=100`` and
        ``properties=all``, following ``paging.next.after`` cursors until
        exhausted.
        """
        yield from self._fetch_all_crm_objects("deals")

    def fetch_all_contacts(self) -> Iterator[dict]:
        """Yield every contact from HubSpot using cursor-based pagination.

        Same pagination pattern as :meth:`fetch_all_deals` but for
        ``/crm/v3/objects/contacts``.
        """
        yield from self._fetch_all_crm_objects("contacts")

    def fetch_all_companies(self) -> Iterator[dict]:
        """Yield every company from HubSpot using cursor-based pagination.

        Same pagination pattern as :meth:`fetch_all_deals` but for
        ``/crm/v3/objects/companies``.
        """
        yield from self._fetch_all_crm_objects("companies")

    def fetch_all_engagements(self) -> Iterator[dict]:
        """Yield every engagement from HubSpot using offset-based pagination.

        Uses the legacy ``GET /engagements/v1/engagements/paged`` endpoint
        which returns ``hasMore`` and ``offset`` rather than a cursor.
        Yields one engagement dict at a time.
        """
        path = "/engagements/v1/engagements/paged"
        params: dict = {"limit": self.PAGE_SIZE}

        while True:
            response = self._get(path, params=params)
            results = response.get("results", [])
            for record in results:
                yield record

            if not response.get("hasMore", False):
                break
            params["offset"] = response.get("offset")

    # ------------------------------------------------------------------ #
    # Connection test                                                      #
    # ------------------------------------------------------------------ #

    def test_connection(self) -> dict:
        """Verify the stored token by calling ``/account-info/v3/details``.

        Returns:
            On success: ``{"success": True, "account_name": str, "portal_id": str}``
            On failure: ``{"success": False, "error": str}``
        """
        try:
            data = self._get("/account-info/v3/details")
            return {
                "success": True,
                "account_name": data.get("uiDomain") or data.get("accountName") or "",
                "portal_id": str(data.get("portalId", "")),
            }
        except (HubSpotAuthenticationError, HubSpotRateLimitError, ExternalServiceError) as exc:
            return {
                "success": False,
                "error": str(exc),
            }
