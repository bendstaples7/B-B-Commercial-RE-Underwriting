"""OpenCorporates Illinois entity lookup adapter.

Uses the licensed OpenCorporates API (not the Illinois SOS web portal).
Requires ``OPENCORPORATES_API_TOKEN`` (or ``ENTITY_LOOKUP_API_KEY``).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import quote

import requests

from app.services.entity_lookup import (
    SUPPORTED_JURISDICTION,
    EntityLookupProviderNotConfiguredError,
    EntityLookupResult,
    EntityPartyResult,
    party_looks_like_company,
    split_person_name,
)

logger = logging.getLogger(__name__)

_OC_BASE = "https://api.opencorporates.com/v0.4"
_IL_JURISDICTION = "us_il"


def _normalize_jurisdiction(code: str | None) -> str:
    if not code:
        return ""
    return code.strip().lower().replace("-", "_")


class IllinoisOpenCorporatesProvider:
    """Look up Illinois LLCs via OpenCorporates companies + officers APIs."""

    name = "opencorporates"

    def __init__(
        self,
        api_token: Optional[str] = None,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_token = (
            api_token
            or os.environ.get("OPENCORPORATES_API_TOKEN")
            or os.environ.get("ENTITY_LOOKUP_API_KEY")
            or ""
        ).strip()
        self._session = session or requests.Session()
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self._api_token)

    def lookup_llc(
        self,
        name: str,
        *,
        jurisdiction: str = SUPPORTED_JURISDICTION,
    ) -> EntityLookupResult:
        cleaned = " ".join((name or "").split())
        if not cleaned:
            return EntityLookupResult(
                found=False,
                error="Entity name is empty",
                provider_name=self.name,
            )

        wanted = _normalize_jurisdiction(jurisdiction) or _IL_JURISDICTION
        if wanted != _IL_JURISDICTION:
            return EntityLookupResult(
                found=False,
                jurisdiction=wanted,
                unsupported_jurisdiction=True,
                error=(
                    f"Jurisdiction {wanted!r} is not supported yet "
                    "(Illinois only in v1)."
                ),
                provider_name=self.name,
            )

        if not self.is_configured():
            raise EntityLookupProviderNotConfiguredError(
                "OpenCorporates API token not configured. "
                "Set OPENCORPORATES_API_TOKEN or ENTITY_LOOKUP_API_KEY."
            )

        try:
            company = self._search_company(cleaned, wanted)
        except requests.RequestException as exc:
            logger.warning("OpenCorporates search failed for %r: %s", cleaned, exc)
            return EntityLookupResult(
                found=False,
                jurisdiction=wanted,
                error=f"Provider request failed: {exc}",
                provider_name=self.name,
            )

        if company is None:
            return EntityLookupResult(
                found=False,
                jurisdiction=wanted,
                error="No matching Illinois entity found",
                provider_name=self.name,
            )

        company_jurisdiction = _normalize_jurisdiction(
            company.get("jurisdiction_code") or wanted
        )
        if company_jurisdiction and company_jurisdiction != _IL_JURISDICTION:
            return EntityLookupResult(
                found=False,
                jurisdiction=company_jurisdiction,
                name=company.get("name"),
                file_number=str(company.get("company_number") or "") or None,
                unsupported_jurisdiction=True,
                error=(
                    f"Entity jurisdiction {company_jurisdiction!r} is not "
                    "supported yet (Illinois only)."
                ),
                raw=company,
                provider_name=self.name,
            )

        parties = self._parties_from_company(company)
        agent_name = None
        agent_address = None
        for party in parties:
            if party.party_type == "registered_agent":
                agent_name = party.full_name
                agent_address = party.address
                break

        oc_status = (company.get("current_status") or "").strip().lower()
        if oc_status in ("active", "good standing", "live"):
            status = "active"
        elif oc_status in ("dissolved", "inactive", "cancelled", "revoked"):
            status = "inactive"
        else:
            status = "unknown"

        return EntityLookupResult(
            found=True,
            jurisdiction=_IL_JURISDICTION,
            name=company.get("name") or cleaned,
            file_number=str(company.get("company_number") or "") or None,
            status=status,
            registered_agent_name=agent_name,
            registered_office_address=agent_address or company.get("registered_address_in_full"),
            parties=parties,
            raw=company,
            provider_name=self.name,
        )

    def _auth_params(self) -> dict[str, str]:
        return {"api_token": self._api_token}

    def _search_company(self, name: str, jurisdiction: str) -> Optional[dict[str, Any]]:
        params = {
            **self._auth_params(),
            "q": name,
            "jurisdiction_code": jurisdiction,
            "per_page": 5,
            "order": "score",
        }
        url = f"{_OC_BASE}/companies/search"
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        payload = resp.json() or {}
        results = (
            (payload.get("results") or {}).get("companies")
            or []
        )
        if not results:
            return None

        # Only accept exact (case-insensitive) company-name matches. The search
        # endpoint is fuzzy, and promoting officers from the top fuzzy hit can
        # resolve the wrong LLC when the requested legal name is absent.
        target = " ".join(name.split()).casefold()
        best = None
        for row in results:
            company = row.get("company") or row
            cname = " ".join((company.get("name") or "").split()).casefold()
            if cname == target:
                best = company
                break

        if best is None:
            return None

        # Fetch full company record (includes officers / agents when available).
        jcode = best.get("jurisdiction_code") or jurisdiction
        cnum = best.get("company_number")
        if not cnum:
            return best
        detail_url = f"{_OC_BASE}/companies/{quote(str(jcode))}/{quote(str(cnum))}"
        detail_resp = self._session.get(
            detail_url, params=self._auth_params(), timeout=self._timeout,
        )
        detail_resp.raise_for_status()
        detail_payload = detail_resp.json() or {}
        return (detail_payload.get("results") or {}).get("company") or best

    def _parties_from_company(self, company: dict[str, Any]) -> list[EntityPartyResult]:
        parties: list[EntityPartyResult] = []
        officers = company.get("officers") or []
        for row in officers:
            officer = row.get("officer") if isinstance(row, dict) and "officer" in row else row
            if not isinstance(officer, dict):
                continue
            full_name = (officer.get("name") or "").strip()
            if not full_name:
                continue
            position = (officer.get("position") or officer.get("role") or "").lower()
            party_type = self._map_position(position)
            is_company = party_looks_like_company(full_name)
            # Agent-type flag from OpenCorporates when present
            agent_type = (officer.get("agent_type") or "").lower()
            if agent_type in ("company", "entity", "corporation"):
                is_company = True
            first, last = (None, full_name) if is_company else split_person_name(full_name)
            parties.append(EntityPartyResult(
                full_name=full_name,
                party_type=party_type,
                is_company=is_company,
                first_name=first,
                last_name=last,
                address=officer.get("address") or None,
                external_id=str(officer.get("id") or "") or None,
            ))

        # Some OC payloads nest agents separately
        for key, party_type in (
            ("agents", "registered_agent"),
            ("registered_agents", "registered_agent"),
        ):
            for row in company.get(key) or []:
                agent = row.get("agent") if isinstance(row, dict) and "agent" in row else row
                if not isinstance(agent, dict):
                    continue
                full_name = (agent.get("name") or "").strip()
                if not full_name:
                    continue
                is_company = party_looks_like_company(full_name)
                first, last = (None, full_name) if is_company else split_person_name(full_name)
                parties.append(EntityPartyResult(
                    full_name=full_name,
                    party_type=party_type,
                    is_company=is_company,
                    first_name=first,
                    last_name=last,
                    address=agent.get("address") or None,
                    external_id=str(agent.get("id") or "") or None,
                ))

        return parties

    @staticmethod
    def _map_position(position: str) -> str:
        if "agent" in position:
            return "registered_agent"
        if "manager" in position:
            return "manager"
        if "member" in position:
            return "member"
        if position in ("president", "secretary", "treasurer", "director", "ceo", "cfo"):
            return "officer"
        if "officer" in position or "director" in position:
            return "officer"
        # Default Illinois LLC parties without a clear title to manager
        return "manager"
