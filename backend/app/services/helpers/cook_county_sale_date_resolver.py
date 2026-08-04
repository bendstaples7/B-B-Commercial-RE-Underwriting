"""Single Cook County sale-date resolve order.

Order (fill-if-null into ``acquisition_date`` for related/MyDec):
  1. Assessor Parcel Sales primary PIN (``wvhk-k5uv``)
  2. Assessor related / AKA / building-ownership candidate PINs
  3. Illinois MyDec PTAX-203 for Cook (~2013+)

Provenance tokens: ``assessor`` | ``assessor_related_pin`` | ``mydec``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.services.helpers.illinois_mydec import fetch_most_recent_transfer_for_pin
from app.services.plugins.pin_utils import normalize_pin_for_socrata

logger = logging.getLogger(__name__)

PROVENANCE_ASSESSOR = "assessor"
PROVENANCE_RELATED = "assessor_related_pin"
PROVENANCE_MYDEC = "mydec"

SALE_DATE_PROVENANCE_TOKENS = frozenset({
    PROVENANCE_ASSESSOR,
    PROVENANCE_RELATED,
    PROVENANCE_MYDEC,
})

# Audit changed_by values → machine provenance for sale_date_meta.source
CHANGED_BY_TO_PROVENANCE = {
    "enrichment:cook_county_assessor": PROVENANCE_ASSESSOR,
    "enrichment:cook_county_assessor_related_pin": PROVENANCE_RELATED,
    "enrichment:illinois_mydec": PROVENANCE_MYDEC,
}

PROVENANCE_TO_CHANGED_BY = {
    PROVENANCE_ASSESSOR: "enrichment:cook_county_assessor",
    PROVENANCE_RELATED: "enrichment:cook_county_assessor_related_pin",
    PROVENANCE_MYDEC: "enrichment:illinois_mydec",
}

PROVENANCE_DISPLAY = {
    PROVENANCE_ASSESSOR: "Assessor",
    PROVENANCE_RELATED: "Assessor related PIN",
    PROVENANCE_MYDEC: "MyDec",
}


@dataclass(frozen=True)
class SaleDateResolution:
    """Result of the Cook County sale-date ladder."""

    acquisition_date: date
    provenance: str
    source_pin: str | None = None
    sale_price: float | None = None
    doc_no: str | None = None
    sale_type: str | None = None

    def to_enrichment_fields(self, *, fill_if_null: bool) -> dict:
        """Fields for EnrichmentData (enrichable + provenance metadata)."""
        fields: dict = {
            "sale_date_provenance": self.provenance,
        }
        if self.source_pin:
            fields["sale_source_pin"] = self.source_pin
        if self.doc_no:
            fields["sale_doc_no"] = self.doc_no
        if self.sale_type:
            fields["sale_type"] = self.sale_type
        # acquisition_date / price always included here; apply layer enforces
        # fill-if-null for related/mydec.
        fields["acquisition_date"] = self.acquisition_date
        fields["_sale_fill_if_null"] = fill_if_null
        if self.sale_price is not None:
            fields["most_recent_sale_price"] = self.sale_price
        return fields


def related_pin_candidates_for_lead(lead) -> list[str]:
    """PIN ladder from building-ownership / AKA collectors, excluding primary."""
    primary = normalize_pin_for_socrata(
        str(getattr(lead, "county_assessor_pin", None) or ""),
    )
    try:
        from app.services.building_ownership_service import BuildingOwnershipService

        rows = BuildingOwnershipService()._collect_assessor_pins(lead)
    except Exception as exc:
        logger.warning(
            "related_pin_candidates_for_lead failed for lead %s: %s",
            getattr(lead, "id", None),
            exc,
        )
        return []

    out: list[str] = []
    seen: set[str] = set()
    if primary:
        seen.add(primary)
    for row in rows or []:
        raw = row.get("pin") if isinstance(row, dict) else row
        normalized = normalize_pin_for_socrata(str(raw or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def resolve_cook_county_sale_date(
    lead,
    *,
    fetch_assessor_sale,
    fetch_mydec: bool = True,
) -> Optional[SaleDateResolution]:
    """Run primary → related → MyDec. *fetch_assessor_sale(pin) -> dict|None*.

    Assessor dict keys match plugin sale fields: ``acquisition_date``,
    ``most_recent_sale_price``, optional ``sale_doc_no`` / ``sale_type``.
    """
    primary = str(getattr(lead, "county_assessor_pin", None) or "").strip()
    if primary:
        primary_hit = _assessor_hit(fetch_assessor_sale, primary, PROVENANCE_ASSESSOR)
        if primary_hit is not None:
            return primary_hit

    for pin in related_pin_candidates_for_lead(lead):
        related_hit = _assessor_hit(fetch_assessor_sale, pin, PROVENANCE_RELATED)
        if related_hit is not None:
            return related_hit

    if not fetch_mydec:
        return None
    # Prefer primary PIN for MyDec even when Assessor sale was empty.
    pin_for_mydec = primary
    if not pin_for_mydec:
        related = related_pin_candidates_for_lead(lead)
        pin_for_mydec = related[0] if related else ""
    if not pin_for_mydec:
        return None
    transfer = fetch_most_recent_transfer_for_pin(pin_for_mydec, county="Cook")
    if not transfer or not transfer.get("acquisition_date"):
        return None
    return SaleDateResolution(
        acquisition_date=transfer["acquisition_date"],
        provenance=PROVENANCE_MYDEC,
        source_pin=normalize_pin_for_socrata(
            str(transfer.get("pin") or pin_for_mydec),
        ) or pin_for_mydec,
    )


def _assessor_hit(fetch_assessor_sale, pin: str, provenance: str) -> Optional[SaleDateResolution]:
    try:
        sale = fetch_assessor_sale(pin) or {}
    except Exception as exc:
        logger.warning("Assessor sale fetch failed for PIN=%r: %s", pin, exc)
        return None
    if not sale:
        return None
    acq = sale.get("acquisition_date")
    if acq is None:
        return None
    if isinstance(acq, str):
        try:
            acq = date.fromisoformat(acq[:10])
        except ValueError:
            return None
    if not isinstance(acq, date):
        return None
    price = sale.get("most_recent_sale_price")
    try:
        sale_price = float(price) if price is not None else None
    except (TypeError, ValueError):
        sale_price = None
    doc_no = sale.get("sale_doc_no") or sale.get("doc_no")
    return SaleDateResolution(
        acquisition_date=acq,
        provenance=provenance,
        source_pin=normalize_pin_for_socrata(pin) or pin,
        sale_price=sale_price,
        doc_no=str(doc_no) if doc_no else None,
        sale_type=sale.get("sale_type"),
    )


def should_write_acquisition_date(lead, resolution: SaleDateResolution) -> bool:
    """Primary Assessor may update; related/MyDec are fill-if-null only."""
    existing = getattr(lead, "acquisition_date", None)
    if existing is None:
        return True
    return resolution.provenance == PROVENANCE_ASSESSOR


def provenance_token_from_changed_by(changed_by: str | None) -> str | None:
    if not changed_by:
        return None
    if changed_by in CHANGED_BY_TO_PROVENANCE:
        return CHANGED_BY_TO_PROVENANCE[changed_by]
    if changed_by.startswith("enrichment:cook_county_assessor"):
        return PROVENANCE_ASSESSOR
    if "mydec" in changed_by.lower():
        return PROVENANCE_MYDEC
    return None
