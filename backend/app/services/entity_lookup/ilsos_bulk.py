"""Illinois SOS Transparency Act bulk DB lookup provider (free, no API key)."""
from __future__ import annotations

import logging
from typing import Optional

from app.models.il_sos_llc import IlSosLlcAgent, IlSosLlcEntity, IlSosLlcManager
from app.services.entity_lookup import (
    SUPPORTED_JURISDICTION,
    EntityLookupProviderNotConfiguredError,
    EntityLookupResult,
    EntityPartyResult,
    party_looks_like_company,
    split_person_name,
)
from app.services.entity_lookup.ilsos_import_service import latest_successful_import
from app.services.entity_lookup.ilsos_parser import normalize_llc_name

logger = logging.getLogger(__name__)

_TYPE_CODE_MAP = {
    "M": "manager",
    "B": "member",
    "P": "member",
}


class IllinoisSosBulkProvider:
    """Look up Illinois LLCs from locally loaded Transparency Act dumps."""

    name = "ilsos_bulk"

    def is_configured(self) -> bool:
        return IlSosLlcEntity.query.limit(1).first() is not None

    def dataset_imported_at(self) -> Optional[str]:
        run = latest_successful_import()
        if run and run.finished_at:
            return run.finished_at.isoformat()
        entity = IlSosLlcEntity.query.order_by(IlSosLlcEntity.imported_at.desc()).first()
        if entity and entity.imported_at:
            return entity.imported_at.isoformat()
        return None

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

        wanted = (jurisdiction or SUPPORTED_JURISDICTION).strip().lower().replace("-", "_")
        if wanted != SUPPORTED_JURISDICTION:
            return EntityLookupResult(
                found=False,
                jurisdiction=wanted,
                unsupported_jurisdiction=True,
                error=(
                    f"Jurisdiction {wanted!r} is not supported yet "
                    "(Illinois SOS bulk only)."
                ),
                provider_name=self.name,
            )

        if not self.is_configured():
            raise EntityLookupProviderNotConfiguredError(
                "Illinois SOS bulk data not loaded. "
                "Run: python scripts/import_il_sos_llc_bulk.py --apply"
            )

        entity = self._find_entity(cleaned)
        if entity is None:
            ambiguous_msg = self._ambiguous_match_message(cleaned)
            return EntityLookupResult(
                found=False,
                jurisdiction=SUPPORTED_JURISDICTION,
                error=ambiguous_msg or (
                    "No matching Illinois LLC in free SOS bulk dump. "
                    "Foreign (e.g. DE) entities and stale names may not appear."
                ),
                provider_name=self.name,
            )

        parties: list[EntityPartyResult] = []
        managers = IlSosLlcManager.query.filter_by(file_number=entity.file_number).all()
        for mgr in managers:
            is_company = bool(mgr.is_company) or party_looks_like_company(mgr.mm_name)
            first, last = (None, mgr.mm_name) if is_company else split_person_name(mgr.mm_name)
            party_type = _TYPE_CODE_MAP.get((mgr.mm_type_code or "").upper(), "manager")
            parties.append(EntityPartyResult(
                full_name=mgr.mm_name,
                party_type=party_type,
                is_company=is_company,
                first_name=first,
                last_name=last,
                address=mgr.mm_street,
                city=mgr.mm_city,
                state=mgr.mm_juris,
                zip=mgr.mm_zip,
            ))

        agent = IlSosLlcAgent.query.get(entity.file_number)
        agent_name = None
        agent_address = None
        if agent is not None:
            agent_name = agent.agent_name
            agent_address = ", ".join(
                p for p in (agent.agent_street, agent.agent_city, agent.agent_zip) if p
            ) or None
            is_company = party_looks_like_company(agent.agent_name)
            first, last = (
                (None, agent.agent_name) if is_company
                else split_person_name(agent.agent_name)
            )
            parties.append(EntityPartyResult(
                full_name=agent.agent_name,
                party_type="registered_agent",
                is_company=is_company,
                first_name=first,
                last_name=last,
                address=agent.agent_street,
                city=agent.agent_city,
                zip=agent.agent_zip,
            ))

        status = self._map_status(entity.status_code)
        return EntityLookupResult(
            found=True,
            jurisdiction=SUPPORTED_JURISDICTION,
            name=entity.name,
            file_number=entity.file_number,
            status=status,
            registered_agent_name=agent_name,
            registered_office_address=agent_address,
            parties=parties,
            provider_name=self.name,
            raw={
                "file_number": entity.file_number,
                "status_code": entity.status_code,
                "management_type": entity.management_type,
                "juris_organized": entity.juris_organized,
            },
        )

    def _find_entity(self, name: str) -> Optional[IlSosLlcEntity]:
        for candidate in self._normalized_candidates(name):
            hit = self._pick_unique_entity(candidate)
            if hit is not None:
                return hit
            # Ambiguous for this candidate — do not fall through to a weaker form
            if self._match_count(candidate) > 1:
                return None
        return None

    def _ambiguous_match_message(self, name: str) -> Optional[str]:
        for candidate in self._normalized_candidates(name):
            if self._match_count(candidate) > 1:
                return (
                    f"Multiple Illinois LLC filings share the name {name!r} "
                    "in the free SOS dump; resolve manually on ilsos.gov."
                )
        return None

    @staticmethod
    def _normalized_candidates(name: str) -> list[str]:
        norm = normalize_llc_name(name)
        if not norm:
            return []
        candidates = [norm]
        stripped = normalize_llc_name(norm.replace(" LLC", ""))
        if stripped and stripped != norm:
            candidates.append(stripped)
            with_llc = normalize_llc_name(f"{stripped} LLC")
            if with_llc and with_llc not in candidates:
                candidates.append(with_llc)
        return candidates

    def _match_count(self, normalized_name: str) -> int:
        if not normalized_name:
            return 0
        return (
            IlSosLlcEntity.query
            .filter_by(normalized_name=normalized_name)
            .count()
        )

    def _pick_unique_entity(self, normalized_name: str) -> Optional[IlSosLlcEntity]:
        """Return a single entity for *normalized_name*, or None if missing/ambiguous.

        Prefers active status codes when multiple rows share a normalized name.
        If more than one distinct file_number remains after that filter, refuse
        to guess (avoids promoting the wrong managers/RA).
        """
        if not normalized_name:
            return None
        rows = (
            IlSosLlcEntity.query
            .filter_by(normalized_name=normalized_name)
            .order_by(IlSosLlcEntity.file_number.asc())
            .all()
        )
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]

        active = [r for r in rows if self._map_status(r.status_code) == "active"]
        candidates = active or rows
        by_fn = {r.file_number: r for r in candidates}
        if len(by_fn) == 1:
            return next(iter(by_fn.values()))

        logger.warning(
            "Ambiguous IL SOS normalized_name=%r matches %d file_numbers; "
            "refusing lookup",
            normalized_name,
            len(by_fn),
        )
        return None

    @staticmethod
    def _map_status(code: Optional[str]) -> str:
        c = (code or "").strip().upper()
        if c in ("00", "0", "A", "AC"):
            return "active"
        if c in ("01", "D", "DI", "I"):
            return "inactive"
        return "unknown"
