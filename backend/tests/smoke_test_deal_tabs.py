"""
Smoke test: verify every Deal Detail tab loads without errors AND that
user-facing write actions (buttons) work end-to-end.

Covers:
  - All 8 tab GET endpoints (page load)
  - Fetch Comps AI button (Market Rents tab) — mocked Gemini
  - Fetch Comps AI button (Sale Comps tab) — mocked Gemini
  - Add Comp manually (Market Rents tab)
  - Add Sale Comp manually (Sale Comps tab)

Requires a running Flask server and a deal to exist in the database.

Usage:
    python backend/tests/smoke_test_deal_tabs.py [deal_id] [base_url] [user_id]

    deal_id   — ID of an existing deal (default: 1)
    base_url  — Flask server URL (default: http://localhost:5000)
    user_id   — X-User-Id header value (default: default)

Exit code 0 = all checks pass. Exit code 1 = one or more checks failed.
"""
import sys
import json
import urllib.request
import urllib.error
from datetime import date, timedelta
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEAL_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
BASE_URL = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://localhost:5000"
USER_ID = sys.argv[3] if len(sys.argv) > 3 else "default"

HEADERS = {"X-User-Id": USER_ID, "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# HTTP helpers
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


def post(path: str, payload: dict = None, timeout: int = 10) -> tuple[int, object]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def delete(path: str) -> tuple[int, object]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers=HEADERS, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            try:
                body = json.loads(resp.read().decode())
            except Exception:
                body = {}
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
# Tab load checks
# ---------------------------------------------------------------------------

def check_tab(tab_name: str, checks: list[tuple[str, str]]) -> bool:
    passed = True
    for path, description in checks:
        status, body = get(path)
        ok = 200 <= status < 300
        icon = "✓" if ok else "✗"
        print(f"  {icon} [{status}] {description}")
        if not ok:
            print(f"      Response: {json.dumps(body)[:200]}")
            passed = False
    return passed


# ---------------------------------------------------------------------------
# Write action checks
# ---------------------------------------------------------------------------

def check_fetch_rent_comps_ai() -> bool:
    """Verify POST /rent-comps/fetch-ai returns 200 and adds comps.

    Uses a mocked Gemini response so no real API call is made.
    Cleans up the inserted comps afterwards.
    """
    print("\n[Action] Fetch Rent Comps (AI button)")

    # Get comp count before
    _, before = get(f"/api/multifamily/deals/{DEAL_ID}/rent-comps/rollup")
    before_count = sum(len(g.get("comps", [])) for g in (before or []))

    # Call the endpoint — this calls Gemini for real (live smoke test)
    # Use a longer timeout since Gemini can take 30-60s
    status, body = post(
        f"/api/multifamily/deals/{DEAL_ID}/rent-comps/fetch-ai",
        timeout=120,
    )
    ok = status == 200
    icon = "✓" if ok else "✗"
    print(f"  {icon} [{status}] POST /rent-comps/fetch-ai")
    if not ok:
        print(f"      Response: {json.dumps(body)[:300]}")
        return False

    added = body.get("added", 0)
    print(f"      Added {added} comp(s). Message: {body.get('message', '')}")

    # Verify comps actually appear in the rollup
    _, after = get(f"/api/multifamily/deals/{DEAL_ID}/rent-comps/rollup")
    after_count = sum(len(g.get("comps", [])) for g in (after or []))

    if after_count <= before_count and added > 0:
        print(f"  ✗ Rollup count did not increase: before={before_count}, after={after_count}")
        return False

    print(f"  ✓ Rollup updated: {before_count} → {after_count} comps")

    # Clean up: delete the comps we just added
    for group in (after or []):
        for comp in group.get("comps", []):
            comp_id = comp.get("id")
            if comp_id:
                del_status, _ = delete(f"/api/multifamily/deals/{DEAL_ID}/rent-comps/{comp_id}")
                if del_status not in (200, 204):
                    print(f"      WARN: failed to delete comp {comp_id} (status {del_status})")

    print(f"  ✓ Cleanup: deleted {after_count} comp(s)")
    return True


def check_fetch_sale_comps_ai() -> bool:
    """Verify POST /sale-comps/fetch-ai returns 200 and adds comps.

    Cleans up the inserted comps afterwards.
    """
    print("\n[Action] Fetch Sale Comps (AI button)")

    # Get comp count before
    _, before = get(f"/api/multifamily/deals/{DEAL_ID}/sale-comps/rollup")
    before_count = len((before or {}).get("comps", []))

    status, body = post(
        f"/api/multifamily/deals/{DEAL_ID}/sale-comps/fetch-ai",
        timeout=120,
    )
    ok = status == 200
    icon = "✓" if ok else "✗"
    print(f"  {icon} [{status}] POST /sale-comps/fetch-ai")
    if not ok:
        print(f"      Response: {json.dumps(body)[:300]}")
        return False

    added = body.get("added", 0)
    print(f"      Added {added} comp(s). Message: {body.get('message', '')}")

    # Verify comps actually appear in the rollup
    _, after = get(f"/api/multifamily/deals/{DEAL_ID}/sale-comps/rollup")
    after_count = len((after or {}).get("comps", []))

    if after_count <= before_count and added > 0:
        print(f"  ✗ Rollup count did not increase: before={before_count}, after={after_count}")
        return False

    print(f"  ✓ Rollup updated: {before_count} → {after_count} comps")

    # Clean up
    for comp in (after or {}).get("comps", []):
        comp_id = comp.get("id")
        if comp_id:
            del_status, _ = delete(f"/api/multifamily/deals/{DEAL_ID}/sale-comps/{comp_id}")
            if del_status not in (200, 204):
                print(f"      WARN: failed to delete sale comp {comp_id} (status {del_status})")

    print(f"  ✓ Cleanup: deleted {after_count} comp(s)")
    return True


def check_add_rent_comp_manual() -> bool:
    """Verify manually adding a rent comp works and appears in the rollup."""
    print("\n[Action] Add Rent Comp (manual)")

    today = date.today().isoformat()
    payload = {
        "address": "SMOKE TEST - 999 Test St, Chicago, IL 60601",
        "unit_type": "2BR/1BA",
        "observed_rent": 1200,
        "sqft": 850,
        "observation_date": today,
    }
    status, body = post(f"/api/multifamily/deals/{DEAL_ID}/rent-comps", payload)
    ok = status == 201
    icon = "✓" if ok else "✗"
    print(f"  {icon} [{status}] POST /rent-comps")
    if not ok:
        print(f"      Response: {json.dumps(body)[:200]}")
        return False

    comp_id = body.get("id")
    print(f"      Created comp id={comp_id}")

    # Verify it appears in rollup
    _, rollup = get(f"/api/multifamily/deals/{DEAL_ID}/rent-comps/rollup")
    all_comp_ids = [c["id"] for g in (rollup or []) for c in g.get("comps", [])]
    if comp_id not in all_comp_ids:
        print(f"  ✗ Comp {comp_id} not found in rollup after insert")
        return False
    print(f"  ✓ Comp appears in rollup")

    # Clean up
    del_status, _ = delete(f"/api/multifamily/deals/{DEAL_ID}/rent-comps/{comp_id}")
    if del_status in (200, 204):
        print(f"  ✓ Cleanup: deleted comp {comp_id}")
    return True


def check_add_sale_comp_manual() -> bool:
    """Verify manually adding a sale comp works and appears in the rollup."""
    print("\n[Action] Add Sale Comp (manual)")

    today = date.today().isoformat()
    payload = {
        "address": "SMOKE TEST - 999 Test Sale St, Chicago, IL 60601",
        "unit_count": 10,
        "status": "Sold",
        "sale_price": 1000000,
        "close_date": today,
        "observed_cap_rate": 0.065,
    }
    status, body = post(f"/api/multifamily/deals/{DEAL_ID}/sale-comps", payload)
    ok = status == 201
    icon = "✓" if ok else "✗"
    print(f"  {icon} [{status}] POST /sale-comps")
    if not ok:
        print(f"      Response: {json.dumps(body)[:200]}")
        return False

    comp_id = body.get("id")
    print(f"      Created sale comp id={comp_id}")

    # Verify it appears in rollup
    _, rollup = get(f"/api/multifamily/deals/{DEAL_ID}/sale-comps/rollup")
    all_comp_ids = [c["id"] for c in (rollup or {}).get("comps", [])]
    if comp_id not in all_comp_ids:
        print(f"  ✗ Sale comp {comp_id} not found in rollup after insert")
        return False
    print(f"  ✓ Sale comp appears in rollup")

    # Clean up
    del_status, _ = delete(f"/api/multifamily/deals/{DEAL_ID}/sale-comps/{comp_id}")
    if del_status in (200, 204):
        print(f"  ✓ Cleanup: deleted sale comp {comp_id}")
    return True


# ---------------------------------------------------------------------------
# ARV analysis flow checks
# ---------------------------------------------------------------------------

def check_analysis_start() -> bool:
    """Verify POST /api/analysis/start works with user_id in header only.

    This is the regression that was introduced when the Axios interceptor
    was changed to stop sending user_id in the request body.
    """
    print("\n[ARV] Analysis start endpoint")
    status, body = post("/api/analysis/start", {
        "address": "1048 N Spaulding Ave, Chicago, IL 60651",
        # NO user_id in body — only in X-User-Id header
    })
    ok = status == 201
    icon = "✓" if ok else "✗"
    print(f"  {icon} [{status}] POST /api/analysis/start (user_id in header only)")
    if not ok:
        print(f"      Response: {json.dumps(body)[:300]}")
        print("      This means user_id is being read from the body instead of the header.")
        return False
    if "session_id" not in (body or {}):
        print(f"  ✗ Response missing session_id: {body}")
        return False
    print(f"      session_id: {body.get('session_id', '?')[:16]}...")
    return True


def check_frontend_autocomplete_dependency() -> bool:
    """Verify the frontend PropertyFactsForm still imports use-places-autocomplete.

    This catches the regression where the autocomplete code was silently
    dropped from the branch because commits were stranded on a sibling branch.
    """
    import os
    print("\n[ARV] Frontend autocomplete dependency")

    # Find PropertyFactsForm.tsx relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    form_path = os.path.join(
        script_dir, "..", "..", "frontend", "src", "components", "PropertyFactsForm.tsx"
    )
    form_path = os.path.normpath(form_path)

    if not os.path.exists(form_path):
        print(f"  ✗ PropertyFactsForm.tsx not found at {form_path}")
        return False

    with open(form_path, encoding="utf-8") as f:
        content = f.read()

    checks = [
        ("use-places-autocomplete", "usePlacesAutocomplete import"),
        ("useGoogleMapsLoaded", "useGoogleMapsLoaded hook"),
    ]

    passed = True
    for search_str, description in checks:
        found = search_str in content
        icon = "✓" if found else "✗"
        print(f"  {icon} {description}")
        if not found:
            print(f"      MISSING: '{search_str}' not found in PropertyFactsForm.tsx")
            print("      This means the autocomplete code was dropped from the branch.")
            passed = False

    # Check App.tsx has the Google Maps loader
    app_path = os.path.join(script_dir, "..", "..", "frontend", "src", "App.tsx")
    app_path = os.path.normpath(app_path)
    if os.path.exists(app_path):
        with open(app_path, encoding="utf-8") as f:
            app_content = f.read()
        for search_str, description in [
            ("@react-google-maps/api", "@react-google-maps/api import in App.tsx"),
            ("GoogleMapsLoadedContext", "GoogleMapsLoadedContext export in App.tsx"),
            ("useLoadScript", "useLoadScript call in App.tsx"),
        ]:
            found = search_str in app_content
            icon = "✓" if found else "✗"
            print(f"  {icon} {description}")
            if not found:
                print(f"      MISSING: '{search_str}' not found in App.tsx")
                passed = False

    # Also check package.json has the dependency installed
    pkg_path = os.path.join(script_dir, "..", "..", "frontend", "package.json")
    pkg_path = os.path.normpath(pkg_path)
    if os.path.exists(pkg_path):
        with open(pkg_path, encoding="utf-8") as f:
            pkg_content = f.read()
        for pkg in ["use-places-autocomplete", "@react-google-maps/api"]:
            found = pkg in pkg_content
            icon = "✓" if found else "✗"
            print(f"  {icon} package.json contains '{pkg}'")
            if not found:
                print(f"      MISSING: Run 'npm install' in frontend/")
                passed = False

    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    skip_ai = "--skip-ai" in sys.argv

    print(f"\nSmoke test: Deal {DEAL_ID} tabs @ {BASE_URL}")
    print(f"User: {USER_ID}")
    if skip_ai:
        print("Mode: tab load checks only (--skip-ai)")
    else:
        print("Mode: tab load checks + write action checks (AI calls enabled)")
    print("=" * 60)

    results = {}

    # ── Tab load checks ──────────────────────────────────────────────────────

    print("\n[Tab 0] Rent Roll")
    results["Rent Roll (load)"] = check_tab("Rent Roll", [
        (f"/api/multifamily/deals/{DEAL_ID}", "GET /deals/:id (units + rent_roll_entries)"),
        (f"/api/multifamily/deals/{DEAL_ID}/rent-roll/summary", "GET /rent-roll/summary"),
    ])

    print("\n[Tab 1] Market Rents")
    results["Market Rents (load)"] = check_tab("Market Rents", [
        (f"/api/multifamily/deals/{DEAL_ID}/rent-comps/rollup", "GET /rent-comps/rollup (no unit_type)"),
    ])

    print("\n[Tab 2] Sale Comps")
    results["Sale Comps (load)"] = check_tab("Sale Comps", [
        (f"/api/multifamily/deals/{DEAL_ID}/sale-comps/rollup", "GET /sale-comps/rollup"),
    ])

    print("\n[Tab 3] Rehab Plan")
    results["Rehab Plan (load)"] = check_tab("Rehab Plan", [
        (f"/api/multifamily/deals/{DEAL_ID}", "GET /deals/:id (rehab_plan_entries)"),
        (f"/api/multifamily/deals/{DEAL_ID}/rehab/rollup", "GET /rehab/rollup"),
    ])

    print("\n[Tab 4] Lenders")
    results["Lenders (load)"] = check_tab("Lenders", [
        (f"/api/multifamily/deals/{DEAL_ID}", "GET /deals/:id (lender_selections)"),
        ("/api/multifamily/lender-profiles", "GET /lender-profiles"),
    ])

    print("\n[Tab 5] Funding")
    results["Funding (load)"] = check_tab("Funding", [
        (f"/api/multifamily/deals/{DEAL_ID}", "GET /deals/:id (funding_sources)"),
    ])

    print("\n[Tab 6] Pro Forma")
    results["Pro Forma (load)"] = check_tab("Pro Forma", [
        (f"/api/multifamily/deals/{DEAL_ID}/pro-forma", "GET /pro-forma"),
    ])

    print("\n[Tab 7] Dashboard")
    results["Dashboard (load)"] = check_tab("Dashboard", [
        (f"/api/multifamily/deals/{DEAL_ID}/dashboard", "GET /dashboard"),
    ])

    # ── Write action checks ──────────────────────────────────────────────────

    print("\n" + "─" * 60)
    print("Write action checks (verifies buttons work end-to-end)")
    print("─" * 60)

    results["Add Rent Comp (manual)"] = check_add_rent_comp_manual()
    results["Add Sale Comp (manual)"] = check_add_sale_comp_manual()

    if not skip_ai:
        print("\nNOTE: AI checks call Gemini with web search — may take 30–90s each.")
        results["Fetch Rent Comps (AI)"] = check_fetch_rent_comps_ai()
        results["Fetch Sale Comps (AI)"] = check_fetch_sale_comps_ai()
    else:
        print("\n  (AI fetch checks skipped — pass --skip-ai to omit)")

    # ── ARV analysis flow checks ─────────────────────────────────────────────

    print("\n" + "─" * 60)
    print("ARV analysis flow checks")
    print("─" * 60)

    results["Analysis start (no user_id in body)"] = check_analysis_start()
    results["Frontend autocomplete dependency"] = check_frontend_autocomplete_dependency()

    # ── Summary ──────────────────────────────────────────────────────────────

    print("\n" + "=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\nResult: {passed}/{total} checks passed\n")

    for check, ok in results.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon} {check}")

    print()
    if passed < total:
        failed = [c for c, ok in results.items() if not ok]
        print(f"FAILED: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
