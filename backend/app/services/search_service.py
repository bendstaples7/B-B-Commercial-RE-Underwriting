"""Ranked fuzzy search service using PostgreSQL pg_trgm (with SQLite fallback).

Supports multi-token cross-field matching, relevance scoring, and typo tolerance.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app import db

logger = logging.getLogger(__name__)

# Pagination defaults (mirrored in search_controller)
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 100
MAX_SESSIONS = 100

# Scoring weights (tunable)
WEIGHT_FULL_NAME_SIM = 3.0
WEIGHT_STREET_SIM = 2.0
WEIGHT_DOCUMENT_SIM = 1.5
WEIGHT_TOKEN_SIM = 1.0
WEIGHT_PREFIX_BONUS = 0.5
WEIGHT_PHONE_EMAIL_BOOST = 2.0
WEIGHT_WARM = 1.0
WEIGHT_CONTACTED_STATUS = 0.5
WEIGHT_RECENT_HUBSPOT = 0.2
WEIGHT_LEAD_SCORE_FACTOR = 0.3
WEIGHT_EXACT_FIELD_MATCH = 12.0
WEIGHT_PREFIX_FIELD_MATCH = 9.0
WEIGHT_CONTAINS_FIELD_MATCH = 7.0
TOKEN_SIMILARITY_THRESHOLD = 0.25

CONTACTED_STATUSES = (
    'mailing_contacted_no_interest',
    'mailing_contacted_interested',
    'negotiating_remote',
    'in_person_appointment',
    'offer_delivered',
)

# SQL expression for search document when column is unavailable (SQLite / pre-migration).
SEARCH_DOCUMENT_EXPR = """
lower(trim(
    coalesce(l.owner_first_name,'') || ' ' ||
    coalesce(l.owner_last_name,'') || ' ' ||
    coalesce(l.owner_2_first_name,'') || ' ' ||
    coalesce(l.owner_2_last_name,'') || ' ' ||
    coalesce(l.property_street,'') || ' ' ||
    coalesce(l.property_city,'') || ' ' ||
    coalesce(l.property_state,'') || ' ' ||
    coalesce(l.property_zip,'')
))
"""

FULL_NAME_EXPR = """
lower(trim(
    coalesce(l.owner_first_name,'') || ' ' || coalesce(l.owner_last_name,'')
))
"""


def tokenize_query(query: str) -> list[str]:
    """Split a query into search tokens.

    Rules:
    - Split on whitespace
    - Strip surrounding punctuation from each token
    - Drop empty tokens
    - Drop single-char tokens UNLESS the query has multiple tokens (allows "Ronald J")
    - Drop single-char tokens that are not alphanumeric
    """
    raw_parts = query.strip().split()
    cleaned: list[str] = []
    for part in raw_parts:
        token = part.strip(".,;:!?'\"()[]{}")
        if not token:
            continue
        cleaned.append(token)

    if len(cleaned) <= 1:
        return [t for t in cleaned if len(t) >= 2]

    result: list[str] = []
    for token in cleaned:
        if len(token) >= 2:
            result.append(token)
        elif len(token) == 1 and token.isalnum():
            result.append(token)
    return result


def build_search_document_from_row(row: Any) -> str:
    """Build normalized search document text from a lead row (Python fallback)."""
    parts = [
        getattr(row, 'owner_first_name', None),
        getattr(row, 'owner_last_name', None),
        getattr(row, 'owner_2_first_name', None),
        getattr(row, 'owner_2_last_name', None),
        getattr(row, 'property_street', None),
        getattr(row, 'property_city', None),
        getattr(row, 'property_state', None),
        getattr(row, 'property_zip', None),
    ]
    return ' '.join(p.strip() for p in parts if p and str(p).strip()).lower()


def _digits_only(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _normalize_search_text(value: str | None) -> str:
    return ' '.join((value or '').lower().split())


def phone_query_digits(query: str) -> str:
    """Return digits only when the query is plausibly a phone number.

    Address searches such as ``3208 W Wabansia`` must not match every phone
    containing 3208 merely because the query includes a street number.
    """
    if re.search(r'[A-Za-z@]', query or ''):
        return ''
    digits = _digits_only(query)
    return digits if len(digits) >= 4 else ''


def _token_matches_text(token: str, text_value: str, fuzzy: bool = False) -> bool:
    """Return True if token matches text (substring; optional fuzzy for typos)."""
    t = token.lower()
    hay = (text_value or '').lower()
    if not hay:
        return False
    if t in hay:
        return True
    # Single-char tokens: allow last-name / word prefix (e.g. "J" → "Jutkins")
    if len(t) == 1 and hay.startswith(t):
        return True
    if fuzzy and len(t) >= 4:
        # Simple typo tolerance: allow one-char deletion in token vs words in hay
        for word in hay.split():
            if abs(len(word) - len(t)) <= 1 and (
                word.startswith(t[: max(1, len(t) - 1)])
                or t.startswith(word[: max(1, len(word) - 1)])
            ):
                return True
    return False


def _get_primary_contact_names(session, lead_id: int) -> tuple[Optional[str], Optional[str]]:
    """Load primary contact first/last name for label and token matching."""
    from app.models.contact import Contact
    from app.models.property_contact import PropertyContact

    row = (
        session.query(Contact.first_name, Contact.last_name)
        .join(PropertyContact, PropertyContact.contact_id == Contact.id)
        .filter(
            PropertyContact.property_id == lead_id,
            PropertyContact.is_primary.is_(True),
        )
        .first()
    )
    if not row:
        return None, None
    return row.first_name, row.last_name


def _token_matches_lead(
    token: str,
    row: Any,
    *,
    fuzzy: bool = False,
    contact_names: Optional[list[tuple[str, str]]] = None,
) -> bool:
    """Return True if token appears in any searchable lead field."""
    fields = [
        getattr(row, 'owner_first_name', None),
        getattr(row, 'owner_last_name', None),
        getattr(row, 'owner_2_first_name', None),
        getattr(row, 'owner_2_last_name', None),
        getattr(row, 'property_street', None),
        getattr(row, 'property_city', None),
        getattr(row, 'property_state', None),
        getattr(row, 'property_zip', None),
        getattr(row, 'email_1', None),
        getattr(row, 'email_2', None),
        getattr(row, 'email_3', None),
        getattr(row, 'email_4', None),
        getattr(row, 'email_5', None),
    ]
    doc = build_search_document_from_row(row)
    if _token_matches_text(token, doc, fuzzy=fuzzy):
        return True
    for val in fields:
        if val and _token_matches_text(token, str(val), fuzzy=fuzzy):
            return True
    if contact_names:
        for first, last in contact_names:
            if _token_matches_text(token, first, fuzzy=fuzzy):
                return True
            if _token_matches_text(token, last, fuzzy=fuzzy):
                return True
            if _token_matches_text(token, f'{first} {last}', fuzzy=fuzzy):
                return True
    return False


def _phone_match(row: Any, q_digits: str, contact_phones: Optional[list[str]] = None) -> bool:
    if not q_digits or len(q_digits) < 4:
        return False
    for slot in ('phone_1', 'phone_2', 'phone_3', 'phone_4', 'phone_5', 'phone_6', 'phone_7'):
        val = getattr(row, slot, None)
        if val and q_digits in _digits_only(str(val)):
            return True
    if contact_phones:
        for val in contact_phones:
            if val and q_digits in _digits_only(val):
                return True
    return False


def _email_match(row: Any, pattern: str, contact_emails: Optional[list[str]] = None) -> bool:
    pat = pattern.lower().strip('%')
    for slot in ('email_1', 'email_2', 'email_3', 'email_4', 'email_5'):
        val = getattr(row, slot, None)
        if val and pat in str(val).lower():
            return True
    if contact_emails:
        for val in contact_emails:
            if val and pat in val.lower():
                return True
    return False


def compute_python_relevance_score(
    row: Any,
    query: str,
    tokens: Sequence[str],
    *,
    q_digits: str = '',
    contact_names: Optional[list[tuple[str, str]]] = None,
    fuzzy: bool = False,
) -> float:
    """Compute relevance score for SQLite / Python fallback path."""
    q_lower = _normalize_search_text(query)
    doc = build_search_document_from_row(row)
    full_name = ' '.join(
        p for p in [
            (getattr(row, 'owner_first_name', None) or '').strip(),
            (getattr(row, 'owner_last_name', None) or '').strip(),
        ] if p
    ).lower()
    street = _normalize_search_text(getattr(row, 'property_street', None))

    score = 0.0
    if full_name == q_lower or street == q_lower:
        score += WEIGHT_EXACT_FIELD_MATCH
    elif full_name.startswith(q_lower) or street.startswith(q_lower):
        score += WEIGHT_PREFIX_FIELD_MATCH
    elif q_lower in full_name or q_lower in street:
        score += WEIGHT_CONTAINS_FIELD_MATCH

    if full_name and q_lower in full_name:
        score += WEIGHT_FULL_NAME_SIM
    elif full_name and any(_token_matches_text(t, full_name, fuzzy=fuzzy) for t in tokens):
        score += WEIGHT_FULL_NAME_SIM * 0.7

    if street and q_lower in street:
        score += WEIGHT_STREET_SIM
    elif street and any(_token_matches_text(t, street, fuzzy=fuzzy) for t in tokens):
        score += WEIGHT_STREET_SIM * 0.7

    if doc and q_lower in doc:
        score += WEIGHT_DOCUMENT_SIM

    for token in tokens:
        if _token_matches_text(token, doc, fuzzy=fuzzy):
            score += WEIGHT_TOKEN_SIM
        if full_name.startswith(token.lower()):
            score += WEIGHT_PREFIX_BONUS
        if street.startswith(token.lower()):
            score += WEIGHT_PREFIX_BONUS

    if _phone_match(row, q_digits) or _email_match(row, q_lower, contact_emails=None):
        score += WEIGHT_PHONE_EMAIL_BOOST

    if getattr(row, 'is_warm', False):
        score += WEIGHT_WARM
    status = getattr(row, 'lead_status', None)
    if status in CONTACTED_STATUSES:
        score += WEIGHT_CONTACTED_STATUS
    lead_score = getattr(row, 'lead_score', None) or 0
    score += WEIGHT_LEAD_SCORE_FACTOR * (float(lead_score) / 100.0)

    last_sync = getattr(row, 'last_hubspot_sync_at', None)
    if last_sync:
        try:
            now = datetime.now(timezone.utc)
            sync_dt = last_sync if last_sync.tzinfo else last_sync.replace(tzinfo=timezone.utc)
            if now - sync_dt <= timedelta(days=30):
                score += WEIGHT_RECENT_HUBSPOT
        except Exception:
            pass

    return round(score, 4)


def build_match_context(row: Any, q_trimmed: str, q_digits: str) -> dict | None:
    """Determine match context for display (phone/email)."""
    matched_phone = getattr(row, 'matched_phone', None)
    if matched_phone:
        return {'type': 'phone', 'value': matched_phone}

    if q_digits and len(q_digits) >= 4:
        for slot in ('phone_1', 'phone_2', 'phone_3', 'phone_4', 'phone_5', 'phone_6', 'phone_7'):
            val = getattr(row, slot, None) or ''
            if val and q_digits in _digits_only(str(val)):
                return {'type': 'phone', 'value': val}

    matched_email = getattr(row, 'matched_email', None)
    if matched_email:
        return {'type': 'email', 'value': matched_email}

    query = _normalize_search_text(q_trimmed)
    tokens = tokenize_query(query)
    street = (getattr(row, 'property_street', None) or '').strip()
    normalized_street = _normalize_search_text(street)
    if street and (
        query in normalized_street
        or (tokens and all(_token_matches_text(token, normalized_street) for token in tokens))
    ):
        return {'type': 'address', 'value': street}

    name = ' '.join(
        part for part in (
            (getattr(row, 'primary_contact_first_name', None) or '').strip(),
            (getattr(row, 'primary_contact_last_name', None) or '').strip(),
        ) if part
    ) or ' '.join(
        part for part in (
            (getattr(row, 'owner_first_name', None) or '').strip(),
            (getattr(row, 'owner_last_name', None) or '').strip(),
        ) if part
    )
    normalized_name = _normalize_search_text(name)
    if name and (
        query in normalized_name
        or (tokens and all(_token_matches_text(token, normalized_name) for token in tokens))
    ):
        return {'type': 'name', 'value': name}

    return None


def build_lead_label(row: Any) -> str:
    """Build display label for a lead search result."""
    primary_first = (getattr(row, 'primary_contact_first_name', None) or '').strip()
    primary_last = (getattr(row, 'primary_contact_last_name', None) or '').strip()
    legacy_first = (getattr(row, 'owner_first_name', None) or '').strip()
    legacy_last = (getattr(row, 'owner_last_name', None) or '').strip()
    street = (getattr(row, 'property_street', None) or '').strip()

    if primary_first or primary_last:
        first, last = primary_first, primary_last
    else:
        first, last = legacy_first, legacy_last

    if first and last:
        name = f'{first} {last}'
    elif first:
        name = first
    elif last:
        name = last
    else:
        name = ''

    if name and street:
        return f'{name} · {street}'
    if name:
        return name
    if street:
        return street
    return 'Unknown Lead'


@dataclass
class SearchResult:
    q: str
    page: int
    per_page: int
    leads: list[dict]
    leads_total: int
    sessions: list[dict]
    sessions_total: int


class SearchService:
    """Ranked fuzzy search across leads and analysis sessions."""

    def __init__(self, session=None):
        self.session = session or db.session

    def search(
        self,
        q: str,
        user_id: str,
        is_admin: bool,
        page: int = DEFAULT_PAGE,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> SearchResult:
        q_trimmed = q.strip()
        tokens = tokenize_query(q_trimmed)
        if not tokens:
            tokens = [q_trimmed]

        q_digits = phone_query_digits(q_trimmed)
        offset = (page - 1) * per_page

        dialect = self._dialect_name()
        use_postgres = dialect == 'postgresql' and self._supports_trgm()

        if use_postgres:
            try:
                leads_rows, leads_total = self._search_leads_postgres(
                    q_trimmed, tokens, q_digits, user_id, is_admin, per_page, offset,
                )
                sessions_rows, sessions_total = self._search_sessions_postgres(
                    q_trimmed, tokens, user_id, is_admin,
                )
            except (OperationalError, ProgrammingError) as exc:
                logger.warning('Postgres search failed, falling back to Python: %s', exc)
                self.session.rollback()
                use_postgres = False

        if not use_postgres:
            leads_rows, leads_total = self._search_leads_python(
                q_trimmed, tokens, q_digits, user_id, is_admin, per_page, offset,
            )
            sessions_rows, sessions_total = self._search_sessions_python(
                q_trimmed, tokens, user_id, is_admin,
            )

        leads = []
        for row in leads_rows:
            relevance = getattr(row, 'relevance_score', None)
            leads.append({
                'id': row.id,
                'type': 'lead',
                'label': build_lead_label(row),
                'nav_path': f'/leads/{row.id}',
                'lead_score': getattr(row, 'lead_score', None),
                'lead_status': getattr(row, 'lead_status', None),
                'relevance_score': float(relevance) if relevance is not None else None,
                'match_context': build_match_context(row, q_trimmed, q_digits),
            })

        if leads:
            from app.services.contact_service import ContactService
            enrichment = ContactService().portfolio_enrichment_for_leads(
                [item['id'] for item in leads],
            )
            for item in leads:
                extra = enrichment.get(item['id']) or {}
                item['property_count'] = extra.get('property_count', 1)
                item['person_key'] = extra.get('person_key')
                item['owner_display_name'] = extra.get('owner_display_name')
                item['property_street'] = extra.get('property_street')
                item['portfolio_properties'] = extra.get('portfolio_properties') or []

        sessions = []
        for row in sessions_rows:
            address = (row.address or '').strip()
            label = address if address else 'Unknown Address'
            created_at_iso = None
            if row.created_at:
                created_at_iso = (
                    row.created_at.isoformat()
                    if hasattr(row.created_at, 'isoformat')
                    else str(row.created_at)
                )
            step = row.current_step
            if hasattr(step, 'name'):
                step = step.name
            status = 'Complete' if step == 'REPORT_GENERATION' else 'In Progress'
            sessions.append({
                'id': row.id,
                'type': 'session',
                'label': label,
                'nav_path': f'/analysis/arv/{row.session_id}',
                'created_at': created_at_iso,
                'status': status,
                'relevance_score': float(getattr(row, 'relevance_score', 0) or 0),
            })

        return SearchResult(
            q=q_trimmed,
            page=page,
            per_page=per_page,
            leads=leads,
            leads_total=leads_total,
            sessions=sessions,
            sessions_total=sessions_total,
        )

    def _dialect_name(self) -> str:
        try:
            return db.engine.dialect.name
        except Exception:
            return 'postgresql'

    def _supports_trgm(self) -> bool:
        try:
            result = self.session.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            ).scalar()
            return result is not None
        except Exception:
            return False

    def _has_search_document_column(self) -> bool:
        try:
            result = self.session.execute(
                text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'leads' AND column_name = 'search_document'
                """)
            ).scalar()
            return result is not None
        except Exception:
            return False

    def _document_sql(self) -> str:
        if self._has_search_document_column():
            return 'COALESCE(l.search_document, \'\')'
        return SEARCH_DOCUMENT_EXPR.strip()

    def _build_token_predicates(self, tokens: Sequence[str], params: dict) -> str:
        """Build AND-ed SQL predicates: each token must match document or contact."""
        doc = self._document_sql()
        clauses = []
        for i, token in enumerate(tokens):
            key = f'token_{i}'
            params[key] = token.lower()
            clauses.append(f"""(
                {doc} ILIKE '%' || :{key} || '%'
                OR similarity({doc}, :{key}) > :token_threshold
                OR similarity({FULL_NAME_EXPR.strip()}, :{key}) > :token_threshold
                OR COALESCE(l.property_street, '') ILIKE '%' || :{key} || '%'
                OR COALESCE(l.owner_last_name, '') ILIKE :{key} || '%'
                OR COALESCE(l.owner_first_name, '') ILIKE :{key} || '%'
                OR EXISTS (
                    SELECT 1 FROM property_contacts pca
                    JOIN contacts ca ON ca.id = pca.contact_id
                    WHERE pca.property_id = l.id
                      AND (
                        ca.first_name ILIKE '%' || :{key} || '%'
                        OR ca.last_name ILIKE '%' || :{key} || '%'
                        OR similarity(lower(trim(coalesce(ca.first_name,'') || ' ' || coalesce(ca.last_name,''))), :{key}) > :token_threshold
                      )
                )
            )""")
        return ' AND '.join(clauses) if clauses else 'TRUE'

    def _phone_email_predicate(self) -> str:
        return """
            (
                :phone_digits_pattern IS NOT NULL AND (
                    regexp_replace(COALESCE(l.phone_1,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_2,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_3,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_4,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_5,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_6,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_7,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR EXISTS (
                        SELECT 1 FROM property_contacts pcp
                        JOIN contact_phones cpp ON cpp.contact_id = pcp.contact_id
                        WHERE pcp.property_id = l.id
                          AND regexp_replace(COALESCE(cpp.value,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    )
                )
                OR l.email_1 ILIKE :pattern
                OR l.email_2 ILIKE :pattern
                OR l.email_3 ILIKE :pattern
                OR l.email_4 ILIKE :pattern
                OR l.email_5 ILIKE :pattern
                OR EXISTS (
                    SELECT 1 FROM property_contacts pce
                    JOIN contact_emails cex ON cex.contact_id = pce.contact_id
                    WHERE pce.property_id = l.id AND cex.value ILIKE :pattern
                )
            )
        """

    def _relevance_score_sql(self) -> str:
        doc = self._document_sql()
        contacted = ', '.join(f"'{s}'" for s in CONTACTED_STATUSES)
        normalized_street = (
            "lower(regexp_replace(trim(COALESCE(l.property_street, '')), '\\s+', ' ', 'g'))"
        )
        normalized_name = (
            f"lower(regexp_replace(trim({FULL_NAME_EXPR.strip()}), '\\s+', ' ', 'g'))"
        )
        return f"""
        (
            CASE
                WHEN {normalized_street} = :q_normalized
                     OR {normalized_name} = :q_normalized
                    THEN {WEIGHT_EXACT_FIELD_MATCH}
                WHEN strpos({normalized_street}, :q_normalized) = 1
                     OR strpos({normalized_name}, :q_normalized) = 1
                    THEN {WEIGHT_PREFIX_FIELD_MATCH}
                WHEN strpos({normalized_street}, :q_normalized) > 0
                     OR strpos({normalized_name}, :q_normalized) > 0
                    THEN {WEIGHT_CONTAINS_FIELD_MATCH}
                ELSE 0
            END
            + {WEIGHT_FULL_NAME_SIM} * similarity({FULL_NAME_EXPR.strip()}, lower(:q))
            + {WEIGHT_STREET_SIM} * similarity(COALESCE(l.property_street, ''), lower(:q))
            + {WEIGHT_DOCUMENT_SIM} * similarity({doc}, lower(:q))
            + CASE WHEN COALESCE(l.is_warm, FALSE) THEN {WEIGHT_WARM} ELSE 0 END
            + CASE WHEN l.lead_status IN ({contacted}) THEN {WEIGHT_CONTACTED_STATUS} ELSE 0 END
            + {WEIGHT_LEAD_SCORE_FACTOR} * (COALESCE(l.lead_score, 0) / 100.0)
            + CASE WHEN l.last_hubspot_sync_at IS NOT NULL
                    AND l.last_hubspot_sync_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '30 days'
                   THEN {WEIGHT_RECENT_HUBSPOT} ELSE 0 END
            + CASE WHEN :phone_digits_pattern IS NOT NULL AND (
                    regexp_replace(COALESCE(l.phone_1,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_2,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_3,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_4,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_5,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_6,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                    OR regexp_replace(COALESCE(l.phone_7,''), '[^0-9]', '', 'g') LIKE :phone_digits_pattern
                ) THEN {WEIGHT_PHONE_EMAIL_BOOST} ELSE 0 END
            + CASE WHEN l.email_1 ILIKE :pattern OR l.email_2 ILIKE :pattern
                    OR l.email_3 ILIKE :pattern OR l.email_4 ILIKE :pattern
                    OR l.email_5 ILIKE :pattern
                   THEN {WEIGHT_PHONE_EMAIL_BOOST} ELSE 0 END
        )
        """

    def _search_leads_postgres(
        self,
        q_trimmed: str,
        tokens: Sequence[str],
        q_digits: str,
        user_id: str,
        is_admin: bool,
        per_page: int,
        offset: int,
    ):
        params: dict[str, Any] = {
            'user_id': user_id,
            'is_admin': is_admin,
            'q': q_trimmed,
            'q_normalized': _normalize_search_text(q_trimmed),
            'pattern': f'%{q_trimmed}%',
            'phone_digits_pattern': f'%{q_digits}%' if len(q_digits) >= 4 else None,
            'token_threshold': TOKEN_SIMILARITY_THRESHOLD,
            'limit': per_page,
            'offset': offset,
        }
        token_pred = self._build_token_predicates(tokens, params)
        phone_email = self._phone_email_predicate()
        relevance = self._relevance_score_sql()
        doc = self._document_sql()

        sql = text(f"""
            SELECT
                l.id,
                l.owner_first_name,
                l.owner_last_name,
                l.property_street,
                l.lead_score,
                l.lead_status,
                l.owner_user_id,
                l.is_warm,
                l.last_hubspot_sync_at,
                l.phone_1, l.phone_2, l.phone_3, l.phone_4,
                l.phone_5, l.phone_6, l.phone_7,
                l.email_1, l.email_2, l.email_3, l.email_4, l.email_5,
                primary_c.first_name AS primary_contact_first_name,
                primary_c.last_name AS primary_contact_last_name,
                {relevance} AS relevance_score,
                COUNT(*) OVER() AS leads_total,
                CASE
                    WHEN :phone_digits_pattern IS NOT NULL AND (
                        regexp_replace(COALESCE(l.phone_1,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    ) THEN l.phone_1
                    WHEN :phone_digits_pattern IS NOT NULL AND (
                        regexp_replace(COALESCE(l.phone_2,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    ) THEN l.phone_2
                    WHEN :phone_digits_pattern IS NOT NULL AND (
                        regexp_replace(COALESCE(l.phone_3,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    ) THEN l.phone_3
                    WHEN :phone_digits_pattern IS NOT NULL AND (
                        regexp_replace(COALESCE(l.phone_4,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    ) THEN l.phone_4
                    WHEN :phone_digits_pattern IS NOT NULL AND (
                        regexp_replace(COALESCE(l.phone_5,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    ) THEN l.phone_5
                    WHEN :phone_digits_pattern IS NOT NULL AND (
                        regexp_replace(COALESCE(l.phone_6,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    ) THEN l.phone_6
                    WHEN :phone_digits_pattern IS NOT NULL AND (
                        regexp_replace(COALESCE(l.phone_7,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                    ) THEN l.phone_7
                    WHEN :phone_digits_pattern IS NOT NULL THEN (
                        SELECT cp2.value FROM property_contacts pc2
                        JOIN contact_phones cp2 ON cp2.contact_id = pc2.contact_id
                        WHERE pc2.property_id = l.id
                          AND regexp_replace(COALESCE(cp2.value,''),'[^0-9]','','g') LIKE :phone_digits_pattern
                        LIMIT 1
                    )
                    ELSE NULL
                END AS matched_phone,
                CASE
                    WHEN l.email_1 ILIKE :pattern THEN l.email_1
                    WHEN l.email_2 ILIKE :pattern THEN l.email_2
                    WHEN l.email_3 ILIKE :pattern THEN l.email_3
                    WHEN l.email_4 ILIKE :pattern THEN l.email_4
                    WHEN l.email_5 ILIKE :pattern THEN l.email_5
                    ELSE (
                        SELECT ce3.value FROM property_contacts pc3
                        JOIN contact_emails ce3 ON ce3.contact_id = pc3.contact_id
                        WHERE pc3.property_id = l.id AND ce3.value ILIKE :pattern
                        LIMIT 1
                    )
                END AS matched_email
            FROM leads l
            LEFT JOIN LATERAL (
                SELECT c.first_name, c.last_name
                FROM property_contacts pc
                JOIN contacts c ON c.id = pc.contact_id
                WHERE pc.property_id = l.id AND pc.is_primary = TRUE
                ORDER BY pc.id
                LIMIT 1
            ) primary_c ON TRUE
            WHERE
                (l.owner_user_id = :user_id OR :is_admin = TRUE)
                AND (l.owner_user_id IS NOT NULL OR :is_admin = TRUE)
                AND (
                    ({token_pred})
                    OR {doc} % lower(:q)
                    OR {phone_email}
                )
            ORDER BY relevance_score DESC, l.lead_score DESC NULLS LAST, l.id
            LIMIT :limit OFFSET :offset
        """)

        rows = self.session.execute(sql, params).fetchall()
        total = int(rows[0].leads_total) if rows else 0
        return rows, total

    def _search_sessions_postgres(
        self,
        q_trimmed: str,
        tokens: Sequence[str],
        user_id: str,
        is_admin: bool,
    ):
        params: dict[str, Any] = {
            'user_id': user_id,
            'is_admin': is_admin,
            'q': q_trimmed,
            'pattern': f'%{q_trimmed}%',
            'token_threshold': TOKEN_SIMILARITY_THRESHOLD,
            'sessions_limit': MAX_SESSIONS,
        }
        token_clauses = []
        for i, token in enumerate(tokens):
            key = f'stoken_{i}'
            params[key] = token.lower()
            token_clauses.append(
                f"(LOWER(pf.address) ILIKE '%' || :{key} || '%' "
                f"OR similarity(LOWER(pf.address), :{key}) > :token_threshold)"
            )
        token_pred = ' AND '.join(token_clauses) if token_clauses else 'TRUE'

        sql = text(f"""
            SELECT
                a.id, a.session_id, a.user_id, a.created_at, a.current_step, pf.address,
                similarity(LOWER(pf.address), lower(:q)) AS relevance_score,
                COUNT(*) OVER() AS sessions_total
            FROM analysis_sessions a
            JOIN property_facts pf ON pf.session_id = a.id
            WHERE
                (a.user_id = :user_id OR :is_admin = TRUE)
                AND (
                    ({token_pred})
                    OR LOWER(pf.address) % lower(:q)
                    OR pf.address ILIKE :pattern
                )
            ORDER BY relevance_score DESC, pf.address
            LIMIT :sessions_limit
        """)
        rows = self.session.execute(sql, params).fetchall()
        total = int(rows[0].sessions_total) if rows else 0
        return rows, total

    def _search_leads_python(
        self,
        q_trimmed: str,
        tokens: Sequence[str],
        q_digits: str,
        user_id: str,
        is_admin: bool,
        per_page: int,
        offset: int,
    ):
        """SQLite fallback: filter and rank in Python."""
        from app.models.lead import Property as Lead

        query = self.session.query(Lead)
        if not is_admin:
            query = query.filter(Lead.owner_user_id == user_id)

        candidates = query.all()
        scored: list[tuple[float, Any]] = []

        for lead in candidates:
            primary_first, primary_last = _get_primary_contact_names(self.session, lead.id)
            contact_names = (
                [(primary_first or '', primary_last or '')]
                if primary_first or primary_last
                else None
            )
            if _phone_match(lead, q_digits) or _email_match(lead, f'%{q_trimmed}%'):
                matched = True
            else:
                matched = all(
                    _token_matches_lead(t, lead, fuzzy=True, contact_names=contact_names)
                    for t in tokens
                )
            if not matched:
                continue
            score = compute_python_relevance_score(
                lead, q_trimmed, tokens, q_digits=q_digits, fuzzy=True,
                contact_names=contact_names,
            )
            lead.primary_contact_first_name = primary_first  # type: ignore[attr-defined]
            lead.primary_contact_last_name = primary_last  # type: ignore[attr-defined]
            lead.relevance_score = score  # type: ignore[attr-defined]
            lead.matched_phone = None  # type: ignore[attr-defined]
            lead.matched_email = None  # type: ignore[attr-defined]
            scored.append((score, lead))

        scored.sort(key=lambda x: (-x[0], -(getattr(x[1], 'lead_score', 0) or 0), x[1].id))
        total = len(scored)
        page_rows = [lead for _, lead in scored[offset: offset + per_page]]

        # Wrap with leads_total attribute
        class RowWrapper:
            def __init__(self, lead, total_count):
                self.__dict__.update(lead.__dict__)
                self.id = lead.id
                self.leads_total = total_count
                for attr in (
                    'owner_first_name', 'owner_last_name', 'property_street',
                    'lead_score', 'lead_status', 'relevance_score',
                    'primary_contact_first_name', 'primary_contact_last_name',
                    'matched_phone', 'matched_email',
                    'phone_1', 'phone_2', 'phone_3', 'phone_4',
                    'phone_5', 'phone_6', 'phone_7',
                ):
                    if hasattr(lead, attr):
                        setattr(self, attr, getattr(lead, attr))

        return [RowWrapper(lead, total) for lead in page_rows], total

    def _search_sessions_python(
        self,
        q_trimmed: str,
        tokens: Sequence[str],
        user_id: str,
        is_admin: bool,
    ):
        from types import SimpleNamespace

        from app.models.analysis_session import AnalysisSession
        from app.models.property_facts import PropertyFacts

        sessions_q = (
            self.session.query(AnalysisSession, PropertyFacts)
            .join(PropertyFacts, PropertyFacts.session_id == AnalysisSession.id)
        )
        if not is_admin:
            sessions_q = sessions_q.filter(AnalysisSession.user_id == user_id)

        results = []
        for session, pf in sessions_q.all():
            addr = (pf.address or '').lower()
            if not addr:
                continue
            if not all(_token_matches_text(t, addr, fuzzy=True) for t in tokens):
                if q_trimmed.lower() not in addr:
                    continue
            score = 1.0 if q_trimmed.lower() in addr else 0.5
            results.append((score, session, pf))

        results.sort(key=lambda x: (-x[0], (x[2].address or '')))
        total = len(results)
        rows = []
        for score, session, pf in results[:MAX_SESSIONS]:
            rows.append(SimpleNamespace(
                id=session.id,
                session_id=session.session_id,
                user_id=session.user_id,
                created_at=session.created_at,
                current_step=session.current_step,
                address=pf.address,
                relevance_score=score,
                sessions_total=total,
            ))
        return rows, total
