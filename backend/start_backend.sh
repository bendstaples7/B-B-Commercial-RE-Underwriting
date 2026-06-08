#!/bin/bash
set -e
cd /home/jeffreyops/B-B-Commercial-RE-Underwriting/backend
source venv/bin/activate
export DATABASE_URL="postgresql://jeffreyops@localhost:5433/real_estate_analysis"
export FLASK_DEBUG=1
python run.py