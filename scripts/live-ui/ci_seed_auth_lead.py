#!/usr/bin/env python3
"""Seed a CI user + minimal lead for authenticated live-UI Playwright smoke.

Prints JSON: {"email","user_id","lead_id"}

Usage (from repo root, with Flask app context / DATABASE_URL):
  cd backend && python ../scripts/live-ui/ci_seed_auth_lead.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

# Ensure backend is importable when run from repo root or backend/
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from env_loader import load_project_env  # noqa: E402

load_project_env()

from app import create_app, db  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


EMAIL = os.environ.get('BB_E2E_EMAIL', 'live-ui-ci@example.com')
PASSWORD = os.environ.get('BB_E2E_PASSWORD', 'LiveUiCiPassw0rd!')
DISPLAY = 'Live UI CI'


def main() -> int:
    app = create_app()
    with app.app_context():
        auth = AuthService()
        existing = User.query.filter_by(email_lower=EMAIL.lower()).first()
        if existing:
            user = existing
            # Ensure password matches CI expectation
            import bcrypt

            user.password_hash = bcrypt.hashpw(
                PASSWORD.encode('utf-8'),
                bcrypt.gensalt(rounds=12),
            ).decode('utf-8')
            user.password_set = True
            user.is_active = True
            db.session.commit()
        else:
            user = auth.create_user(EMAIL, PASSWORD, DISPLAY)

        lead = (
            Lead.query.filter_by(owner_user_id=user.user_id, source='live-ui-ci')
            .order_by(Lead.id.desc())
            .first()
        )
        if not lead:
            lead = Lead(
                property_street='100 Live UI Smoke St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60601',
                property_type='Multifamily',
                units=4,
                owner_first_name='Live',
                owner_last_name='UI',
                county_assessor_pin='00-00-000-000-0000',
                most_recent_sale='01/15/2020',
                most_recent_sale_price=500000.0,
                assessed_value=450000.0,
                lead_status='skip_trace',
                owner_user_id=user.user_id,
                source='live-ui-ci',
                date_identified=date.today(),
            )
            db.session.add(lead)
            db.session.commit()

        out = {
            'email': EMAIL,
            'user_id': user.user_id,
            'lead_id': lead.id,
        }
        print(json.dumps(out))
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
