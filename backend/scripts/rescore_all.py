"""Bulk rescore all leads using the unified LeadScoringEngine.

Run from backend/ directory:
    python scripts/rescore_all.py

Scores every lead: updates leads.lead_score, leads.recommended_action,
and appends lead_scores history rows.
"""
import os
import sys
from pathlib import Path

# Add backend to path
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
    n = engine.recalculate_all_lead_scores()
    logger.info("Done: %d leads scored", n)
