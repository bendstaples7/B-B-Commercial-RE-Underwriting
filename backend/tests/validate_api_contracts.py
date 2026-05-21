"""
Option 3: Frontend-backend contract validator.

Calls every endpoint the frontend uses, then compares the response keys
against the TypeScript interface definitions parsed from types/index.ts.

Reports any key present in the TypeScript type but missing from the actual
backend response — the exact class of bug that caused the Market Rents 400.

Usage:
    python backend/tests/validate_api_contracts.py [deal_id] [base_url] [user_id]

Exit code 0 = no contract violations. Exit code 1 = violations found.
"""
import sys
import re
import json
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEAL_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
BASE_URL = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://localhost:5000"
USER_ID = sys.argv[3] if len(sys.argv) > 3 else "default"

HEADERS = {"X-User-Id": USER_ID}

TYPES_FILE = Path(__file__).parent.parent.parent / "frontend" / "src" / "types" / "index.ts"

# ---------------------------------------------------------------------------
# TypeScript interface parser
# ---------------------------------------------------------------------------

def parse_ts_interface(ts_source: str, interface_name: str) -> set[str]:
    """Extract field names from a TypeScript interface definition.

    Handles simple `fieldName: type` and `fieldName?: type` patterns.
    Does not handle nested interfaces or generics — just top-level keys.
    """
    # Find the interface block
    pattern = rf"export interface {re.escape(interface_name)}\s*\{{([^}}]+)\}}"
    match = re.search(pattern, ts_source, re.DOTALL)
    if not match:
        return set()

    block = match.group(1)
    # Extract field names (lines like `  fieldName: type` or `  fieldName?: type`)
    fields = set()
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("/*"):
            continue
        field_match = re.match(r"^(\w+)\??:", line)
        if field_match:
            fields.add(field_match.group(1))
    return fields


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def get(path: str) -> tuple[int, object]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = str(e)
        return e.code, body
    except Exception as e:
        return 0, str(e)


# ---------------------------------------------------------------------------
# Contract checks
# ---------------------------------------------------------------------------

def check_contract(
    description: str,
    actual: dict | list,
    ts_interface: str,
    ts_source: str,
    item_from_list: bool = False,
) -> list[str]:
    """Compare actual response keys against a TypeScript interface.

    Returns a list of violation strings (empty = no violations).
    """
    expected_keys = parse_ts_interface(ts_source, ts_interface)
    if not expected_keys:
        return [f"  WARN: Could not parse TypeScript interface '{ts_interface}'"]

    if item_from_list:
        if not isinstance(actual, list) or len(actual) == 0:
            return []  # Empty list is valid — can't check shape
        actual = actual[0]

    if not isinstance(actual, dict):
        return [f"  ERROR: Expected dict, got {type(actual).__name__}"]

    actual_keys = set(actual.keys())
    missing = expected_keys - actual_keys

    violations = []
    if missing:
        for key in sorted(missing):
            violations.append(
                f"  MISSING key '{key}' in {description} "
                f"(expected by TypeScript interface '{ts_interface}')"
            )
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not TYPES_FILE.exists():
        print(f"ERROR: types/index.ts not found at {TYPES_FILE}")
        sys.exit(1)

    ts_source = TYPES_FILE.read_text(encoding="utf-8")

    print(f"\nContract validation: Deal {DEAL_ID} @ {BASE_URL}")
    print(f"TypeScript types: {TYPES_FILE}")
    print("=" * 60)

    all_violations = []

    # --- Deal response ---
    print("\nChecking Deal response shape...")
    status, body = get(f"/api/multifamily/deals/{DEAL_ID}")
    if status != 200:
        all_violations.append(f"  ERROR: GET /deals/{DEAL_ID} returned {status}: {body}")
    else:
        # Deal interface (top-level fields only — nested arrays checked separately)
        violations = check_contract(
            f"GET /deals/{DEAL_ID}", body, "Deal", ts_source
        )
        all_violations.extend(violations)
        if not violations:
            print("  ✓ Deal response shape matches TypeScript interface")

    # --- RentRollSummary ---
    print("\nChecking RentRollSummary response shape...")
    status, body = get(f"/api/multifamily/deals/{DEAL_ID}/rent-roll/summary")
    if status != 200:
        all_violations.append(f"  ERROR: GET /rent-roll/summary returned {status}: {body}")
    else:
        violations = check_contract(
            "GET /rent-roll/summary", body, "RentRollSummary", ts_source
        )
        all_violations.extend(violations)
        if not violations:
            print("  ✓ RentRollSummary response shape matches TypeScript interface")

    # --- RentCompRollup (no unit_type — the bug) ---
    print("\nChecking RentCompRollup response shape (no unit_type param)...")
    status, body = get(f"/api/multifamily/deals/{DEAL_ID}/rent-comps/rollup")
    if status != 200:
        all_violations.append(
            f"  ERROR: GET /rent-comps/rollup (no unit_type) returned {status}: {body}\n"
            f"  The frontend never sends unit_type — this must return 200."
        )
    else:
        violations = check_contract(
            "GET /rent-comps/rollup[0]", body, "RentCompRollup", ts_source,
            item_from_list=True
        )
        all_violations.extend(violations)
        if not violations:
            print("  ✓ RentCompRollup response shape matches TypeScript interface")

    # --- SaleCompRollup ---
    print("\nChecking SaleCompRollup response shape...")
    status, body = get(f"/api/multifamily/deals/{DEAL_ID}/sale-comps/rollup")
    if status != 200:
        all_violations.append(f"  ERROR: GET /sale-comps/rollup returned {status}: {body}")
    else:
        violations = check_contract(
            "GET /sale-comps/rollup", body, "SaleCompRollup", ts_source
        )
        all_violations.extend(violations)
        if not violations:
            print("  ✓ SaleCompRollup response shape matches TypeScript interface")

    # --- RehabMonthlyRollup ---
    print("\nChecking RehabMonthlyRollup response shape...")
    status, body = get(f"/api/multifamily/deals/{DEAL_ID}/rehab/rollup")
    if status != 200:
        all_violations.append(f"  ERROR: GET /rehab/rollup returned {status}: {body}")
    else:
        violations = check_contract(
            "GET /rehab/rollup[0]", body, "RehabMonthlyRollup", ts_source,
            item_from_list=True
        )
        all_violations.extend(violations)
        if not violations:
            print("  ✓ RehabMonthlyRollup response shape matches TypeScript interface")

    # --- LenderProfile list ---
    print("\nChecking LenderProfile list response shape...")
    status, body = get("/api/multifamily/lender-profiles")
    if status != 200:
        all_violations.append(f"  ERROR: GET /lender-profiles returned {status}: {body}")
    else:
        if "profiles" not in body:
            all_violations.append("  MISSING key 'profiles' in GET /lender-profiles response")
        else:
            print("  ✓ Lender profiles response has 'profiles' key")

    # --- ProFormaResult ---
    print("\nChecking ProFormaResult response shape...")
    status, body = get(f"/api/multifamily/deals/{DEAL_ID}/pro-forma")
    if status != 200:
        all_violations.append(f"  ERROR: GET /pro-forma returned {status}: {body}")
    else:
        violations = check_contract(
            "GET /pro-forma", body, "ProFormaResult", ts_source
        )
        all_violations.extend(violations)
        if not violations:
            print("  ✓ ProFormaResult response shape matches TypeScript interface")

    # --- Dashboard ---
    print("\nChecking Dashboard response shape...")
    status, body = get(f"/api/multifamily/deals/{DEAL_ID}/dashboard")
    if status != 200:
        all_violations.append(f"  ERROR: GET /dashboard returned {status}: {body}")
    else:
        violations = check_contract(
            "GET /dashboard", body, "Dashboard", ts_source
        )
        all_violations.extend(violations)
        if not violations:
            print("  ✓ Dashboard response shape matches TypeScript interface")

    # --- Summary ---
    print("\n" + "=" * 60)
    if all_violations:
        print(f"\nFound {len(all_violations)} contract violation(s):\n")
        for v in all_violations:
            print(v)
        print()
        sys.exit(1)
    else:
        print("\nAll contracts valid — backend responses match TypeScript interfaces.")
        sys.exit(0)


if __name__ == "__main__":
    main()
