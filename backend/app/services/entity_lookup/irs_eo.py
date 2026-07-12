"""Normalize and look up IRS EO BMF organization names."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.models.irs_eo_organization import IrsEoOrganization

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_ENTITY_SUFFIXES = re.compile(
    r"\b(L\.?\s*L\.?\s*C\.?|INC\.?|INCORPORATED|CORP\.?|CORPORATION|"
    r"LTD\.?|LIMITED|CO\.?|COMPANY|NFP|N\.F\.P\.?)\b",
    re.I,
)


def normalize_eo_name(name: str) -> str:
    """Normalize an organization name for IRS EO matching."""
    cleaned = " ".join((name or "").upper().split())
    cleaned = cleaned.replace("&", " AND ")
    cleaned = cleaned.replace(",", " ")
    cleaned = _ENTITY_SUFFIXES.sub(" ", cleaned)
    cleaned = _NON_ALNUM.sub(" ", cleaned)
    return " ".join(cleaned.split())


@dataclass
class NonprofitLookupResult:
    """Result of an IRS EO nonprofit name lookup."""

    found: bool
    name: Optional[str] = None
    ein: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    ntee_cd: Optional[str] = None
    subsection: Optional[str] = None
    error: Optional[str] = None
    provider_name: str = "irs_eo_bmf"


class IrsEoNonprofitProvider:
    """Look up tax-exempt orgs from a locally loaded IRS EO BMF extract."""

    name = "irs_eo_bmf"

    def is_configured(self) -> bool:
        return IrsEoOrganization.query.limit(1).first() is not None

    def dataset_imported_at(self) -> Optional[str]:
        row = (
            IrsEoOrganization.query
            .order_by(IrsEoOrganization.imported_at.desc())
            .first()
        )
        if row and row.imported_at:
            return row.imported_at.isoformat()
        return None

    def lookup_nonprofit(
        self,
        name: str,
        *,
        state: Optional[str] = "IL",
    ) -> NonprofitLookupResult:
        cleaned = " ".join((name or "").split())
        if not cleaned:
            return NonprofitLookupResult(found=False, error="Entity name is empty")

        if not self.is_configured():
            return NonprofitLookupResult(
                found=False,
                error=(
                    "IRS EO BMF data not loaded. "
                    "Run: python scripts/import_irs_eo_bmf.py --apply"
                ),
            )

        wanted = normalize_eo_name(cleaned)
        if not wanted:
            return NonprofitLookupResult(found=False, error="Entity name is empty")

        state_code = re.sub(r"[^A-Z]", "", (state or "").upper()) or None
        query = IrsEoOrganization.query.filter(
            IrsEoOrganization.normalized_name == wanted,
        )
        if state_code:
            query = query.filter(IrsEoOrganization.state == state_code)

        # Prefer active EO rows when status is present (blank/"01" = active).
        matches = query.order_by(IrsEoOrganization.ein.asc()).limit(5).all()
        if state_code and not matches:
            return NonprofitLookupResult(
                found=False,
                error=(
                    f"No matching tax-exempt organization in IRS EO BMF "
                    f"for state {state_code}"
                ),
            )

        if not matches:
            return NonprofitLookupResult(
                found=False,
                error="No matching tax-exempt organization in IRS EO BMF",
            )
        if len(matches) > 1:
            active = [row for row in matches if _is_active_eo_status(row.status)]
            if len(active) == 1:
                matches = active
            else:
                return NonprofitLookupResult(
                    found=False,
                    error=(
                        f"Ambiguous IRS EO name match ({len(matches)} rows) — "
                        "confirm manually or refine the entity name"
                    ),
                )

        row = matches[0]
        return NonprofitLookupResult(
            found=True,
            name=row.name,
            ein=row.ein,
            city=row.city,
            state=row.state,
            ntee_cd=row.ntee_cd,
            subsection=row.subsection,
        )


def _is_active_eo_status(status: Optional[str]) -> bool:
    """IRS EO BMF: blank or ``01`` means unconditional/active exemption."""
    code = (status or "").strip()
    return code == "" or code == "01"


def upsert_eo_row(
    *,
    ein: str,
    name: str,
    city: Optional[str] = None,
    state: Optional[str] = None,
    ntee_cd: Optional[str] = None,
    subsection: Optional[str] = None,
    status: Optional[str] = None,
    imported_at: Optional[datetime] = None,
) -> IrsEoOrganization:
    """Insert or update one IRS EO row (used by import + tests)."""
    from app import db

    cleaned_ein = re.sub(r"\D", "", ein or "")
    if len(cleaned_ein) != 9:
        raise ValueError(f"Invalid EIN: {ein!r}")

    row = db.session.get(IrsEoOrganization, cleaned_ein)
    if row is None:
        row = IrsEoOrganization(ein=cleaned_ein)
        db.session.add(row)

    row.name = " ".join((name or "").split())[:200]
    row.normalized_name = normalize_eo_name(row.name)
    row.city = ((city or "").strip()[:64] or None)
    row.state = re.sub(r"[^A-Z]", "", (state or "").upper())[:2] or None
    row.ntee_cd = ((ntee_cd or "").strip()[:10] or None)
    row.subsection = ((subsection or "").strip()[:4] or None)
    row.status = ((status or "").strip()[:2] or None)
    row.imported_at = imported_at or datetime.utcnow()
    return row
