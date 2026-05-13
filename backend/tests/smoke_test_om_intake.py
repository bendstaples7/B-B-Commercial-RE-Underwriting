"""
End-to-end smoke test for the Commercial OM PDF Intake feature.

Runs against a LIVE local server (Flask + Celery + Redis must be running).

Verifies the COMPLETE user flow including confirm:
  1. Upload PDF → job created (PENDING)
  2. Pipeline advances to EXTRACTING (PDF parsing + task chain works)
  3. If Gemini API key is set: wait for REVIEW, then confirm → Deal created
  4. If no Gemini key: test confirm against the most recent REVIEW job in the DB

The smoke test FAILS if the confirm endpoint returns an error, even if the
pipeline itself worked. A feature is only "working" when a Deal can be created.

Usage:
    python backend/tests/smoke_test_om_intake.py

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000/api/om-intake"
DEALS_URL = "http://localhost:5000/api/multifamily/deals"
HEADERS = {"X-User-Id": "smoke-test-user"}
PARSE_TIMEOUT_SECONDS = 30
FULL_PIPELINE_TIMEOUT_SECONDS = 300
POLL_INTERVAL = 2

_MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 200>>
stream
BT /F1 12 Tf 50 750 Td
(Offering Memorandum - 123 Main Street Chicago IL) Tj
0 -20 Td (Asking Price: $2,500,000) Tj
0 -20 Td (Unit Count: 10 units) Tj
0 -20 Td (Cap Rate: 6.5%) Tj
0 -20 Td (NOI: $162,500) Tj
0 -20 Td (Unit Mix: 5x 2BR/1BA at $1,200/mo, 5x 1BR/1BA at $950/mo) Tj
ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000274 00000 n
0000000526 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
605
%%EOF"""


def _request(method, path, data=None, content_type="application/json", base=BASE_URL):
    url = f"{base}{path}"
    req = urllib.request.Request(url, method=method)
    for k, v in HEADERS.items():
        req.add_header(k, v)
    if data is not None:
        req.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"status": resp.status, "body": json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": json.loads(e.read())}


def _upload_pdf():
    boundary = b"----SmokeTestBoundary"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="smoke_test.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
        + _MINIMAL_PDF
        + b"\r\n--" + boundary + b"--\r\n"
    )
    return _request("POST", "/jobs", data=body,
                    content_type=f"multipart/form-data; boundary={boundary.decode()}")


def _poll(job_id, targets, timeout):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = _request("GET", f"/jobs/{job_id}")
        if r["status"] == 200:
            s = r["body"].get("intake_status")
            if s != last:
                print(f"  → {s}")
                last = s
            if s in targets:
                return s
        time.sleep(POLL_INTERVAL)
    return "TIMEOUT"


def _find_review_job():
    """Find the most recent job in REVIEW status to use for confirm testing."""
    r = _request("GET", "/jobs?page_size=25")
    if r["status"] != 200:
        return None
    for job in r["body"].get("jobs", []):
        if job.get("intake_status") == "REVIEW":
            return job["id"]
    return None


def _confirm_job(job_id):
    """Call confirm on a job in REVIEW status. Returns (success, deal_id, error)."""
    review = _request("GET", f"/jobs/{job_id}/review")
    if review["status"] != 200:
        return False, None, f"GET /review returned {review['status']}"

    om = (review["body"] or {}).get("extracted_om_data") or {}

    def _val(field):
        f = om.get(field, {})
        return f.get("value") if isinstance(f, dict) else None

    confirmed_data = {
        "asking_price": _val("asking_price") or 2500000,
        "unit_count": _val("unit_count") or 10,
        "unit_mix": [
            {"unit_type_label": "2BR/1BA", "unit_count": 5, "sqft": 850,
             "current_avg_rent": 1200, "proforma_rent": 1400},
            {"unit_type_label": "1BR/1BA", "unit_count": 5, "sqft": 650,
             "current_avg_rent": 950, "proforma_rent": 1100},
        ],
        "expense_items": [],
        "other_income_items": [],
    }

    result = _request("POST", f"/jobs/{job_id}/confirm", data=confirmed_data)
    if result["status"] == 200:
        return True, result["body"].get("deal_id"), None
    elif result["status"] == 409:
        # Already confirmed — that's fine, get the deal_id
        deal_id = result["body"].get("deal_id")
        return True, deal_id, None
    else:
        return False, None, f"HTTP {result['status']}: {result['body']}"


PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  ✅ {name}")
    else:
        FAILED.append(name)
        print(f"  ❌ {name}" + (f": {detail}" if detail else ""))


def run():
    has_api_key = bool(os.getenv("GOOGLE_AI_API_KEY", "").strip())

    print("\n" + "=" * 60)
    print("  OM Intake Smoke Test — Full Flow Including Confirm")
    print(f"  Gemini: {'enabled' if has_api_key else 'not configured'}")
    print("=" * 60 + "\n")

    # ------------------------------------------------------------------
    # Step 1: Upload
    # ------------------------------------------------------------------
    print("Step 1: Upload PDF")
    upload = _upload_pdf()
    check("Upload returns 201", upload["status"] == 201,
          f"got {upload['status']}: {upload['body']}")
    if upload["status"] != 201:
        print("Cannot continue — is the server running?")
        return False
    job_id = upload["body"].get("intake_job_id")
    check("Response contains intake_job_id", job_id is not None)
    print(f"  Job ID: {job_id}\n")

    # ------------------------------------------------------------------
    # Step 2: Pipeline mechanics (reaches EXTRACTING within 30s)
    # ------------------------------------------------------------------
    print(f"Step 2: Pipeline mechanics (timeout: {PARSE_TIMEOUT_SECONDS}s)")
    status = _poll(job_id, {"EXTRACTING", "REVIEW", "CONFIRMED", "FAILED"}, PARSE_TIMEOUT_SECONDS)
    print()
    check("Pipeline advances past PENDING",
          status in ("EXTRACTING", "REVIEW", "CONFIRMED", "FAILED"),
          f"stuck at {status}")
    if status == "TIMEOUT":
        print("  Is the Celery worker running?")

    # ------------------------------------------------------------------
    # Step 3: Full pipeline (if Gemini configured)
    # ------------------------------------------------------------------
    if has_api_key and status == "EXTRACTING":
        print(f"Step 3: Full pipeline (timeout: {FULL_PIPELINE_TIMEOUT_SECONDS}s)")
        status = _poll(job_id, {"REVIEW", "CONFIRMED", "FAILED"}, FULL_PIPELINE_TIMEOUT_SECONDS)
        print()
        check("Full pipeline reaches REVIEW", status in ("REVIEW", "CONFIRMED"),
              f"final: {status}")
        if status == "FAILED":
            r = _request("GET", f"/jobs/{job_id}")
            print(f"  Error: {r['body'].get('error_message')}")
    elif not has_api_key:
        print("Step 3: Skipped (no Gemini key)\n")

    # ------------------------------------------------------------------
    # Step 4: Confirm — ALWAYS tested
    # Tests against the current job if it reached REVIEW, otherwise finds
    # the most recent REVIEW job in the DB. This step is REQUIRED to pass.
    # ------------------------------------------------------------------
    print("Step 4: Confirm intake → Deal creation (REQUIRED)")
    confirm_job_id = job_id if status == "REVIEW" else None

    if confirm_job_id is None:
        # Find a REVIEW job from a previous run
        confirm_job_id = _find_review_job()
        if confirm_job_id:
            print(f"  Using existing REVIEW job {confirm_job_id} for confirm test")
        else:
            check("Confirm endpoint tested", False,
                  "No job in REVIEW status available. Run with Gemini API key to test confirm.")
            print()
            _print_summary()
            return len(FAILED) == 0

    success, deal_id, error = _confirm_job(confirm_job_id)
    check("POST /confirm returns 200 or 409", success, error or "")
    if success and deal_id:
        check("Confirm response contains deal_id", True)
        print(f"  Deal ID: {deal_id}")

        # Verify the Deal actually exists
        deal_result = _request("GET", f"/{deal_id}", base=DEALS_URL)
        check("Deal exists in database",
              deal_result["status"] == 200,
              f"GET /deals/{deal_id} returned {deal_result['status']}")
    print()

    _print_summary()
    return len(FAILED) == 0


def _print_summary():
    print("=" * 60)
    print(f"  Results: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print(f"  Failed: {', '.join(FAILED)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
