"""Entity lookup provider contracts and result types.

Adapters implement ``EntityLookupProvider``. Default v1 provider is free
Illinois SOS Transparency Act bulk data (``ilsos_bulk``). Do not scrape the
interactive Illinois SOS business-entity search.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


SUPPORTED_JURISDICTION = "us_il"


@dataclass
class EntityPartyResult:
    """One manager / member / officer / registered agent from a filing."""

    full_name: str
    party_type: str  # manager | member | officer | registered_agent
    is_company: bool = False
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    external_id: Optional[str] = None


@dataclass
class EntityLookupResult:
    """Normalized entity lookup payload returned by a provider."""

    found: bool
    jurisdiction: str = SUPPORTED_JURISDICTION
    name: Optional[str] = None
    file_number: Optional[str] = None
    status: Optional[str] = None  # active / inactive / unknown
    registered_agent_name: Optional[str] = None
    registered_office_address: Optional[str] = None
    parties: list[EntityPartyResult] = field(default_factory=list)
    unsupported_jurisdiction: bool = False
    error: Optional[str] = None
    raw: Optional[dict] = None
    provider_name: str = ""


class EntityLookupProviderNotConfiguredError(RuntimeError):
    """Raised when the provider is not ready (empty bulk tables or missing API key)."""


@runtime_checkable
class EntityLookupProvider(Protocol):
    """Interface for Illinois (and future) entity registry lookups."""

    name: str

    def is_configured(self) -> bool:
        """Return True when credentials / config allow live lookups."""
        ...

    def lookup_llc(
        self,
        name: str,
        *,
        jurisdiction: str = SUPPORTED_JURISDICTION,
    ) -> EntityLookupResult:
        """Look up an LLC / corporation by legal name."""
        ...


def split_person_name(full_name: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort first/last split for natural-person party names."""
    cleaned = " ".join((full_name or "").split())
    if not cleaned:
        return None, None
    if "," in cleaned:
        last, _, first = cleaned.partition(",")
        last = last.strip() or None
        first = first.strip() or None
        return first, last
    parts = cleaned.split()
    if len(parts) == 1:
        return None, parts[0]
    return " ".join(parts[:-1]), parts[-1]


def party_looks_like_company(name: str) -> bool:
    """Heuristic: registered agents are often corporate service companies."""
    from app.services.plugins.owner_name_utils import is_entity_name
    return is_entity_name(name or "")
