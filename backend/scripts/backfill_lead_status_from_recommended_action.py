"""One-time migration: populate lead_status from recommended_action.

Leads have recommended_action values that indicate their actual pipeline
stage, but lead_status defaults to 'awaiting_skip_trace' for all records.
This script updates lead_status based on recommended_action so the kanban
view correctly distributes leads across columns.

Mapping:
  add_contact_info    → skip_trace        (needs contact info before outreach)
  resolve_match       → mailing_contacted_interested (matched to a property)
  analyze_property    → negotiating_remote (analysis in progress)
  NULL / other        → awaiting_skip_trace (already the default — no change)
"""
import os
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# Load .env
_env_file = _backend_dir / '.env'
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('backfill_lead_status')

from app import create_app, db
from app.models.lead import Lead
from sqlalchemy import text

app = create_app('development')
print_func = print  # use print so output isn't swallowed by app logging config

with app.app_context():
    # --- Step 1: Before counts ---
    print_func("=== BEFORE: lead_status distribution ===", flush=True)
    before = db.session.execute(
        text("SELECT lead_status, COUNT(*) FROM leads GROUP BY lead_status ORDER BY lead_status")
    ).fetchall()
    for row in before:
        print_func(f"  {str(row[0]):35s} {row[1]}", flush=True)

    print_func("", flush=True)
    print_func("=== BEFORE: recommended_action distribution ===", flush=True)
    ra_counts = db.session.execute(
        text("SELECT recommended_action, COUNT(*) FROM leads GROUP BY recommended_action ORDER BY recommended_action")
    ).fetchall()
    for row in ra_counts:
        print_func(f"  {str(row[0] or 'NULL'):35s} {row[1]}", flush=True)

    # --- Step 2: Perform the update ---
    print_func("", flush=True)
    print_func("Updating lead_status based on recommended_action...", flush=True)

    # Mapping: recommended_action → lead_status
    mapping = {
        'add_contact_info': 'skip_trace',
        'resolve_match':    'mailing_contacted_interested',
        'analyze_property': 'negotiating_remote',
    }

    total_updated = 0
    for ra_value, ls_value in mapping.items():
        result = db.session.execute(
            text("""
                UPDATE leads
                SET lead_status = :ls_value,
                    updated_at = NOW()
                WHERE recommended_action = :ra_value
                  AND lead_status != :ls_value
            """),
            {'ls_value': ls_value, 'ra_value': ra_value}
        )
        n = result.rowcount
        if n > 0:
            print_func(f"  {ra_value} → {ls_value} : {n} rows", flush=True)
            total_updated += n
        else:
            print_func(f"  {ra_value} → {ls_value} : 0 rows (already up-to-date)", flush=True)

    db.session.commit()
    print_func(f"Total rows updated: {total_updated}", flush=True)

    # --- Step 3: After counts ---
    print_func("", flush=True)
    print_func("=== AFTER: lead_status distribution ===", flush=True)
    after = db.session.execute(
        text("SELECT lead_status, COUNT(*) FROM leads GROUP BY lead_status ORDER BY lead_status")
    ).fetchall()
    for row in after:
        print_func(f"  {str(row[0]):35s} {row[1]}", flush=True)