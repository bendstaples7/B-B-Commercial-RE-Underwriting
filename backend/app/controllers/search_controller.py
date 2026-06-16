"""Search API endpoint.

Provides a single GET /api/search endpoint that searches across leads
(by owner name or property address) and analysis sessions (by property
address). Results are ownership-scoped: regular users see only their own
records; admin users see all records.
"""
import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request
from marshmallow import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import db
from app.api_utils import require_auth

logger = logging.getLogger(__name__)

search_bp = Blueprint('search', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supports_trgm(db_session) -> bool:
    """Return True if pg_trgm extension is available."""
    try:
        result = db_session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        ).scalar()
        return result is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Error handling decorator (local copy following project convention)
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Invalid request',
                'message': str(e),
            }), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': getattr(e, 'name', 'HTTP error'),
                    'message': e.description,
                }), e.code
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Match context helper
# ---------------------------------------------------------------------------

def _build_match_context(row, q_trimmed: str, q_digits: str) -> dict | None:
    """Determine which field caused this row to match and return context for display.

    Returns a dict like:
        {"type": "phone", "value": "(773) 454-0106"}
        {"type": "email", "value": "owner@example.com"}
    or None if the match was on a name/address (already visible in the label).

    Priority: phone → email → (name/address → None, already shown in label)
    """
    matched_phone = getattr(row, 'matched_phone', None)
    if matched_phone:
        return {'type': 'phone', 'value': matched_phone}

    # If SQL didn't catch it (SQLite fallback), check raw phone columns
    if q_digits and len(q_digits) >= 4:
        import re as _re
        for slot in ('phone_1', 'phone_2', 'phone_3', 'phone_4',
                     'phone_5', 'phone_6', 'phone_7'):
            val = getattr(row, slot, None) or ''
            if val and q_digits in _re.sub(r'\D', '', val):
                return {'type': 'phone', 'value': val}

    # Email match
    matched_email = getattr(row, 'matched_email', None)
    if matched_email:
        return {'type': 'email', 'value': matched_email}

    # Name / address — these are already visible in the label, so no extra context needed
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@search_bp.route('/search', methods=['GET'])
@handle_errors
@require_auth
def search():
    """Search across leads and analysis sessions.

    Query parameters
    ----------------
    q : str
        The search query string. Must be 2–200 characters after trimming
        whitespace. Returns 400 if missing, too short, or too long.

    Returns
    -------
    200 : {"leads": [...], "sessions": [...]}
        Matched records scoped to the authenticated user. Admin users
        (g.is_admin = True) receive results across all users.
    400 : {"message": "..."} for invalid q parameter.
    401 : If unauthenticated (handled by @require_auth).
    """
    # --- Read and validate q ---
    q = request.args.get('q')

    if q is None:
        return jsonify({'message': 'Missing required parameter: q'}), 400

    q_trimmed = q.strip()

    if len(q_trimmed) < 2:
        return jsonify({'message': 'Query must be at least 2 characters'}), 400

    if len(q_trimmed) > 200:
        return jsonify({'message': 'Query must not exceed 200 characters'}), 400

    # --- Ownership context (server-authoritative, never from client) ---
    user_id = g.user_id
    is_admin = g.is_admin

    # --- Build search patterns ---
    pattern = f'%{q_trimmed}%'
    prefix_pattern = f'{q_trimmed}%'

    # --- Phone digit normalisation ---
    # Strip all non-digit characters from the query so that "555-555-5555",
    # "5555555555", and "5555" (last-4) all resolve to the same digit string.
    # The SQL side strips digits from stored values using regexp_replace so we
    # can compare apples-to-apples regardless of how the number was formatted.
    import re as _re
    q_digits = _re.sub(r'\D', '', q_trimmed)   # e.g. "555-555-5555" → "5555555555"
    is_phone_query = len(q_digits) >= 4         # at least 4 digits = plausible phone search
    phone_digits_pattern = f'%{q_digits}%' if is_phone_query else None

    # --- Leads query ---
    # Joins to property_contacts + contacts so that:
    #   1. Searching by a contact's name (e.g. "Luke") returns the property.
    #   2. Searching by phone/email returns the property.
    #   3. The result label shows the primary contact name when one exists,
    #      falling back to the legacy flat owner columns.
    #
    # Phone matching (PostgreSQL): strips non-digits from both sides using
    # regexp_replace so "555-555-5555", "5555555555", and last-4 "5555" all match.
    #
    # ILIKE is PostgreSQL-specific; SQLite tests use LIKE via LOWER() fallback.
    _leads_sql_ilike = text("""
        SELECT
            l.id,
            l.owner_first_name,
            l.owner_last_name,
            l.property_street,
            l.lead_score,
            l.owner_user_id,
            primary_c.first_name  AS primary_contact_first_name,
            primary_c.last_name   AS primary_contact_last_name,
            -- Correlated subqueries for match_context: only set when the SPECIFIC
            -- field actually matched the query, avoiding the MAX()-over-Cartesian-
            -- product problem where an unrelated contact's phone leaks through.
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
                    SELECT cp2.value
                    FROM property_contacts pc2
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
                    SELECT ce3.value
                    FROM property_contacts pc3
                    JOIN contact_emails ce3 ON ce3.contact_id = pc3.contact_id
                    WHERE pc3.property_id = l.id
                      AND ce3.value ILIKE :pattern
                    LIMIT 1
                )
                ELSE NULL
            END AS matched_email
        FROM leads l
        LEFT JOIN property_contacts pc_primary
            ON pc_primary.property_id = l.id
            AND pc_primary.is_primary = TRUE
        LEFT JOIN contacts primary_c
            ON primary_c.id = pc_primary.contact_id
        WHERE
            (l.owner_user_id = :user_id OR :is_admin = TRUE)
            AND (l.owner_user_id IS NOT NULL OR :is_admin = TRUE)
            AND (
                -- Name / address matching
                l.owner_first_name  ILIKE :pattern
                OR l.owner_last_name   ILIKE :pattern
                OR l.owner_2_first_name ILIKE :pattern
                OR l.owner_2_last_name  ILIKE :pattern
                OR l.property_street   ILIKE :pattern
                OR EXISTS (
                    SELECT 1 FROM property_contacts pca
                    JOIN contacts ca ON ca.id = pca.contact_id
                    WHERE pca.property_id = l.id
                      AND (ca.first_name ILIKE :pattern OR ca.last_name ILIKE :pattern)
                )
                -- Email matching (flat columns + relational)
                OR l.email_1 ILIKE :pattern
                OR l.email_2 ILIKE :pattern
                OR l.email_3 ILIKE :pattern
                OR l.email_4 ILIKE :pattern
                OR l.email_5 ILIKE :pattern
                OR EXISTS (
                    SELECT 1 FROM property_contacts pce
                    JOIN contact_emails cex ON cex.contact_id = pce.contact_id
                    WHERE pce.property_id = l.id
                      AND cex.value ILIKE :pattern
                )
                -- Phone matching via digit normalisation (PostgreSQL regexp_replace)
                -- Strips all non-digit characters before comparing, so
                -- "555-555-5555", "5555555555", and "5555" (last-4) all match.
                OR (
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
                )
            )
        ORDER BY
            CASE
                WHEN l.owner_first_name ILIKE :prefix_pattern THEN 0
                WHEN l.owner_last_name  ILIKE :prefix_pattern THEN 0
                WHEN l.property_street  ILIKE :prefix_pattern THEN 0
                WHEN primary_c.first_name ILIKE :prefix_pattern THEN 0
                WHEN primary_c.last_name  ILIKE :prefix_pattern THEN 0
                ELSE 1
            END,
            COALESCE(primary_c.last_name, l.owner_last_name, l.property_street)
        LIMIT 10
    """)
    # SQLite fallback — no regexp_replace, so phone matching uses LIKE on raw value.
    # This is acceptable for tests since real phone search only runs on PostgreSQL.
    _leads_sql_like = text("""
        SELECT
            l.id,
            l.owner_first_name,
            l.owner_last_name,
            l.property_street,
            l.lead_score,
            l.owner_user_id,
            primary_c.first_name  AS primary_contact_first_name,
            primary_c.last_name   AS primary_contact_last_name,
            NULL AS matched_phone,
            NULL AS matched_email
        FROM leads l
        LEFT JOIN property_contacts pc_primary
            ON pc_primary.property_id = l.id
            AND pc_primary.is_primary = 1
        LEFT JOIN contacts primary_c
            ON primary_c.id = pc_primary.contact_id
        LEFT JOIN property_contacts pc_any
            ON pc_any.property_id = l.id
        LEFT JOIN contacts any_c
            ON any_c.id = pc_any.contact_id
        LEFT JOIN contact_phones cp
            ON cp.contact_id = any_c.id
        LEFT JOIN contact_emails ce
            ON ce.contact_id = any_c.id
        WHERE
            (l.owner_user_id = :user_id OR :is_admin = 1)
            AND (l.owner_user_id IS NOT NULL OR :is_admin = 1)
            AND (
                LOWER(l.owner_first_name)   LIKE LOWER(:pattern)
                OR LOWER(l.owner_last_name)    LIKE LOWER(:pattern)
                OR LOWER(COALESCE(l.owner_2_first_name,'')) LIKE LOWER(:pattern)
                OR LOWER(COALESCE(l.owner_2_last_name,''))  LIKE LOWER(:pattern)
                OR LOWER(l.property_street)    LIKE LOWER(:pattern)
                OR LOWER(any_c.first_name)     LIKE LOWER(:pattern)
                OR LOWER(any_c.last_name)      LIKE LOWER(:pattern)
                OR LOWER(COALESCE(l.email_1,'')) LIKE LOWER(:pattern)
                OR LOWER(COALESCE(l.email_2,'')) LIKE LOWER(:pattern)
                OR LOWER(COALESCE(l.email_3,'')) LIKE LOWER(:pattern)
                OR LOWER(COALESCE(l.email_4,'')) LIKE LOWER(:pattern)
                OR LOWER(COALESCE(l.email_5,'')) LIKE LOWER(:pattern)
                OR LOWER(COALESCE(ce.value,''))  LIKE LOWER(:pattern)
                OR COALESCE(l.phone_1,'') LIKE :phone_raw_pattern
                OR COALESCE(l.phone_2,'') LIKE :phone_raw_pattern
                OR COALESCE(l.phone_3,'') LIKE :phone_raw_pattern
                OR COALESCE(l.phone_4,'') LIKE :phone_raw_pattern
                OR COALESCE(l.phone_5,'') LIKE :phone_raw_pattern
                OR COALESCE(l.phone_6,'') LIKE :phone_raw_pattern
                OR COALESCE(l.phone_7,'') LIKE :phone_raw_pattern
                OR COALESCE(cp.value,'')  LIKE :phone_raw_pattern
            )
        GROUP BY
            l.id, l.owner_first_name, l.owner_last_name,
            l.property_street, l.lead_score, l.owner_user_id,
            primary_c.first_name, primary_c.last_name
        ORDER BY
            CASE
                WHEN LOWER(l.owner_first_name) LIKE LOWER(:prefix_pattern) THEN 0
                WHEN LOWER(l.owner_last_name)  LIKE LOWER(:prefix_pattern) THEN 0
                WHEN LOWER(l.property_street)  LIKE LOWER(:prefix_pattern) THEN 0
                WHEN LOWER(COALESCE(primary_c.first_name, '')) LIKE LOWER(:prefix_pattern) THEN 0
                WHEN LOWER(COALESCE(primary_c.last_name, ''))  LIKE LOWER(:prefix_pattern) THEN 0
                ELSE 1
            END,
            COALESCE(primary_c.last_name, l.owner_last_name, l.property_street)
        LIMIT 10
    """)
    _params = {
        'user_id': user_id,
        'is_admin': is_admin,
        'pattern': pattern,
        'prefix_pattern': prefix_pattern,
        'phone_digits_pattern': phone_digits_pattern,   # None when query has <4 digits
        'phone_raw_pattern': pattern,                   # SQLite fallback: raw LIKE on stored value
    }

    # Detect dialect: SQLite does not support ILIKE
    # Use db.engine.dialect.name — works with SQLAlchemy 1.x and 2.x
    try:
        dialect_name = db.engine.dialect.name
    except Exception:
        dialect_name = 'postgresql'
    if dialect_name == 'sqlite':
        leads_results = db.session.execute(_leads_sql_like, _params).fetchall()
    else:
        try:
            leads_results = db.session.execute(_leads_sql_ilike, _params).fetchall()
        except OperationalError:
            # Fallback for any dialect that doesn't support ILIKE
            leads_results = db.session.execute(_leads_sql_like, _params).fetchall()

    # --- Sessions query (task 2.3) ---
    # ILIKE is not supported by SQLite (used in tests); fall back to LIKE on failure.
    try:
        sessions_results = db.session.execute(
            text("""
                SELECT
                    a.id,
                    a.session_id,
                    a.user_id,
                    a.created_at,
                    a.current_step,
                    pf.address
                FROM analysis_sessions a
                JOIN property_facts pf ON pf.session_id = a.id
                WHERE
                    (a.user_id = :user_id OR :is_admin = TRUE)
                    AND pf.address ILIKE :pattern
                ORDER BY
                    CASE WHEN pf.address ILIKE :prefix_pattern THEN 0 ELSE 1 END,
                    pf.address
                LIMIT 5
            """),
            {
                'user_id': user_id,
                'is_admin': is_admin,
                'pattern': pattern,
                'prefix_pattern': prefix_pattern,
            }
        ).fetchall()
    except OperationalError:
        # SQLite fallback: ILIKE not supported, use case-insensitive LIKE via LOWER()
        sessions_results = db.session.execute(
            text("""
                SELECT
                    a.id,
                    a.session_id,
                    a.user_id,
                    a.created_at,
                    a.current_step,
                    pf.address
                FROM analysis_sessions a
                JOIN property_facts pf ON pf.session_id = a.id
                WHERE
                    (a.user_id = :user_id OR :is_admin = 1)
                    AND LOWER(pf.address) LIKE LOWER(:pattern)
                ORDER BY
                    CASE WHEN LOWER(pf.address) LIKE LOWER(:prefix_pattern) THEN 0 ELSE 1 END,
                    pf.address
                LIMIT 5
            """),
            {
                'user_id': user_id,
                'is_admin': is_admin,
                'pattern': pattern,
                'prefix_pattern': prefix_pattern,
            }
        ).fetchall()

    # --- Serialize leads ---
    leads = []
    for row in leads_results:
        # Source-level fallback: if the primary contact has any name part set,
        # use primary_first + primary_last (blanks for missing parts). Only fall
        # back to legacy flat columns when the primary contact has no name at all.
        # This prevents hybrid names like "Luke Carlson" (primary first, legacy last).
        primary_first = (row.primary_contact_first_name or '').strip()
        primary_last = (row.primary_contact_last_name or '').strip()
        legacy_first = (row.owner_first_name or '').strip()
        legacy_last = (row.owner_last_name or '').strip()
        street = (row.property_street or '').strip()

        if primary_first or primary_last:
            first, last = primary_first, primary_last
        else:
            first, last = legacy_first, legacy_last

        if first and last:
            name = f"{first} {last}"
        elif first:
            name = first
        elif last:
            name = last
        else:
            name = ""

        # Always include the address so searching by number shows the property
        # clearly. Format: "Luke · 4263 W Montrose Ave Apt 1" or just the
        # address when there's no contact name.
        if name and street:
            label = f"{name} · {street}"
        elif name:
            label = name
        elif street:
            label = street
        else:
            label = "Unknown Lead"

        leads.append({
            'id': row.id,
            'type': 'lead',
            'label': label,
            'nav_path': f"/properties/{row.id}",
            'lead_score': row.lead_score,
            'match_context': _build_match_context(row, q_trimmed, q_digits),
        })

    # --- Serialize sessions ---
    sessions = []
    for row in sessions_results:
        address = (row.address or '').strip()
        label = address if address else "Unknown Address"

        created_at_iso = None
        if row.created_at:
            if hasattr(row.created_at, 'isoformat'):
                created_at_iso = row.created_at.isoformat()
            else:
                created_at_iso = str(row.created_at)

        # current_step is stored as the enum name string (e.g. 'REPORT_GENERATION')
        # when retrieved via raw SQL. WorkflowStep.REPORT_GENERATION is the final step.
        step = row.current_step
        # Handle both raw string and enum object (defensive)
        if hasattr(step, 'name'):
            step = step.name
        status = 'Complete' if step == 'REPORT_GENERATION' else 'In Progress'

        sessions.append({
            'id': row.id,
            'type': 'session',
            'label': label,
            'nav_path': f"/analysis/arv/{row.session_id}",
            'created_at': created_at_iso,
            'status': status,
        })

    return jsonify({'leads': leads, 'sessions': sessions}), 200
