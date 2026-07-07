"""Cook County prospect feed ownership and admission thresholds."""
from __future__ import annotations

import logging
import os

from app.services.motivation_signal_service import STRUCTURED_MOTIVATION_CAP

logger = logging.getLogger(__name__)

DEFAULT_PROSPECT_MIN_MOTIVATION_PCT = 60.0


def get_prospect_min_motivation_pct() -> float:
    """Minimum distress motivation % required to enter Prospect Review."""
    raw = os.environ.get('COOK_COUNTY_PROSPECT_MIN_MOTIVATION_PCT', '').strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning('Invalid COOK_COUNTY_PROSPECT_MIN_MOTIVATION_PCT=%r', raw)
    return DEFAULT_PROSPECT_MIN_MOTIVATION_PCT


def motivation_pct(motivation_score: float, *, lead_category: str = 'residential') -> float:
    """Normalize raw structured motivation points to a 0–100 percentage."""
    cap = STRUCTURED_MOTIVATION_CAP.get(lead_category, STRUCTURED_MOTIVATION_CAP['residential'])
    if cap <= 0:
        return 0.0
    return round((motivation_score / cap) * 100, 1)


def min_motivation_score_for_queue(*, lead_category: str = 'residential') -> float:
    """Raw motivation_score floor matching get_prospect_min_motivation_pct()."""
    cap = STRUCTURED_MOTIVATION_CAP.get(lead_category, STRUCTURED_MOTIVATION_CAP['residential'])
    return get_prospect_min_motivation_pct() / 100.0 * cap


_CHICAGO_API_PLACEHOLDERS = frozenset({
    '',
    'your-chicago-data-api-key',
    'your-chicago-data-app-token',
    'replace_me',
})


def chicago_data_api_configured() -> bool:
    """True when Chicago open-data feeds can authenticate (app token present)."""
    for env_name in ('CHICAGO_DATA_API_KEY', 'SOCRATA_APP_TOKEN'):
        raw = os.environ.get(env_name, '').strip()
        if raw and raw.lower() not in _CHICAGO_API_PLACEHOLDERS:
            return True
    return False


def resolve_cook_county_prospect_owner_user_id() -> str:
    """Return the user_id that owns prospect candidates created by scheduled feeds."""
    explicit = os.environ.get('COOK_COUNTY_PROSPECT_OWNER_USER_ID', '').strip()
    if explicit:
        return explicit

    email = os.environ.get('COOK_COUNTY_PROSPECT_OWNER_EMAIL', '').strip()
    if email:
        try:
            from flask import has_app_context

            if has_app_context():
                from app.models.user import User

                user = User.query.filter_by(email_lower=email.lower()).first()
                if user and user.user_id:
                    return user.user_id
        except Exception as exc:
            logger.warning('Could not resolve prospect owner from email: %s', exc)

    raise ValueError(
        'COOK_COUNTY_PROSPECT_OWNER_USER_ID or COOK_COUNTY_PROSPECT_OWNER_EMAIL must be set '
        'for Cook County prospect feeds'
    )
