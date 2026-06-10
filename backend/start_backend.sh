#!/bin/bash
set -e
cd "$(dirname "$0")"
source venv/bin/activate
export DATABASE_URL="postgresql://jeffreyops@localhost:5433/real_estate_analysis"
export FLASK_DEBUG=1
python run.py