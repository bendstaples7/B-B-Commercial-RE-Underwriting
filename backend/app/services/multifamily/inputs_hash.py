"""
Canonical serialization and SHA-256 hashing for pro forma input snapshots.

Provides deterministic hashing of DealInputs so that the pro forma cache
can detect when inputs have changed and a recomputation is needed.

Key design decisions:
- Lists are sorted by stable natural keys (unit_id, unit_type, source_type)
  so that row-order changes in the database do not invalidate the cache.
- Decimal values are serialized via `str()` to preserve precision.
- Timestamps and soft-deleted rows are excluded (they don't affect computation).
- The hash is SHA-256 of canonical JSON with `sort_keys=True, separators=(",", ":")`.

Requirements: 15.1, 15.2, 15.3
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from decimal import Decimal
from typing import Any

from app.services.multifamily.pro_forma_inputs import DealInputs


# ---------------------------------------------------------------------------
# Canonical serialization
# ---------------------------------------------------------------------------


def _serialize_value(value: Any) -> Any:
    """Serialize a single value for canonical JSON output.

    - Decimal → str (preserves precision, deterministic)
    - None → None
    - bool → bool (must check before int since bool is subclass of int)
    - int → int
    - str → str
    - tuple/list → list of serialized values
    - dict → dict with sorted string keys and serialized values
    - Frozen dataclass → dict of its fields (recursive)
    - CapExAllocationStrategy → class name string (not data-bearing)
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in sorted(value.items())}
    # Frozen dataclass — serialize its fields
    if hasattr(value, "__dataclass_fields__"):
        result: dict[str, Any] = {}
        for f in fields(value):
            result[f.name] = _serialize_value(getattr(value, f.name))
        return dict(sorted(result.items()))
    # CapExAllocationStrategy or other protocol objects — use class name
    return type(value).__name__


def _sort_by_key(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Sort a list of dicts by a natural key for stable ordering."""
    return sorted(items, key=lambda d: d.get(key, ""))


def canonical_inputs(deal_inputs: DealInputs) -> dict:
    """Produce a canonical dict representation of DealInputs.

    The output is suitable for deterministic JSON serialization. Lists are
    sorted by stable natural keys so that database row-order does not affect
    the hash. Timestamps and soft-deleted rows are excluded (they are not
    part of DealInputs by design).

    Sorting keys:
    - units: sorted by unit_id
    - rent_roll: sorted by unit_id
    - rehab_plan: sorted by unit_id
    - market_rents: sorted by unit_type
    - funding_sources: sorted by source_type

    Args:
        deal_inputs: Frozen DealInputs snapshot.

    Returns:
        A dict ready for `json.dumps(sort_keys=True, separators=(",", ":"))`.
    """
    # Serialize the deal snapshot
    deal_dict = _serialize_value(deal_inputs.deal)

    # Serialize and sort units by unit_id
    units_list = [_serialize_value(u) for u in deal_inputs.units]
    units_sorted = _sort_by_key(units_list, "unit_id")

    # Serialize and sort rent_roll by unit_id
    rent_roll_list = [_serialize_value(rr) for rr in deal_inputs.rent_roll]
    rent_roll_sorted = _sort_by_key(rent_roll_list, "unit_id")

    # Serialize and sort rehab_plan by unit_id
    rehab_plan_list = [_serialize_value(rp) for rp in deal_inputs.rehab_plan]
    rehab_plan_sorted = _sort_by_key(rehab_plan_list, "unit_id")

    # Serialize and sort market_rents by unit_type
    market_rents_list = [_serialize_value(mr) for mr in deal_inputs.market_rents]
    market_rents_sorted = _sort_by_key(market_rents_list, "unit_type")

    # Serialize OpEx and reserves (single objects, no sorting needed)
    opex_dict = _serialize_value(deal_inputs.opex)
    reserves_dict = _serialize_value(deal_inputs.reserves)

    # Serialize lender snapshots (None if not attached)
    lender_a_dict = _serialize_value(deal_inputs.lender_scenario_a)
    lender_b_dict = _serialize_value(deal_inputs.lender_scenario_b)

    # Serialize and sort funding_sources by source_type
    funding_list = [_serialize_value(fs) for fs in deal_inputs.funding_sources]
    funding_sorted = _sort_by_key(funding_list, "source_type")

    # CapEx allocation strategy — just the class name (not data-bearing)
    capex_strategy = type(deal_inputs.capex_allocation).__name__

    return {
        "deal": deal_dict,
        "units": units_sorted,
        "rent_roll": rent_roll_sorted,
        "rehab_plan": rehab_plan_sorted,
        "market_rents": market_rents_sorted,
        "opex": opex_dict,
        "reserves": reserves_dict,
        "lender_scenario_a": lender_a_dict,
        "lender_scenario_b": lender_b_dict,
        "funding_sources": funding_sorted,
        "capex_allocation": capex_strategy,
    }


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------


def compute_inputs_hash(deal_inputs: DealInputs) -> str:
    """Compute a SHA-256 hash of the canonical DealInputs representation.

    The hash is deterministic: identical inputs always produce the same hash,
    regardless of the order in which units, rent_roll entries, etc. were
    inserted into the database.

    Args:
        deal_inputs: Frozen DealInputs snapshot.

    Returns:
        64-character lowercase hex string (SHA-256 digest).
    """
    canonical = canonical_inputs(deal_inputs)
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
