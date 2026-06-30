"""Bulk rescore all leads using the unified LeadScoringEngine.

Run from backend/ directory:
    python scripts/rescore_all.py

Updates live lead fields (lead_score, recommended_action, recommended_contact_method)
via bulk_rescore; does not append lead_scores history rows.
"""
import os
import sys
from pathlib import Path

# Add backend to path
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# Load project .env (root + backend) — same as Flask / dev.py
from env_loader import load_project_env
load_project_env()

# Must have a proper SECRET_KEY for Flask — require it to be set in environment
# (no fallback; the script will fail at app init if SECRET_KEY is missing)

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('rescore_all')

from app import create_app

# Use development config so it connects to the real PostgreSQL DB
app = create_app('development')

with app.app_context():
    from app.services.lead_scoring_engine import LeadScoringEngine
    from app.models.lead import Lead

    total = Lead.query.count()
    logger.info("Scoring %d leads...", total)

    engine = LeadScoringEngine()
    n = engine.bulk_rescore('default')
    logger.info("Done: %d leads rescored (live fields only, no history rows)", n)
