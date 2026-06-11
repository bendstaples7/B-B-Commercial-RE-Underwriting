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

    # --- Leads query: ILIKE on name/address fields with ownership scoping ---
    # ILIKE is PostgreSQL-specific; SQLite tests use LIKE via LOWER() fallback.
    _leads_sql_ilike = text("""
        SELECT
            id,
            owner_first_name,
            owner_last_name,
            property_street,
            lead_score,
            owner_user_id
        FROM leads
        WHERE
            (owner_user_id = :user_id OR :is_admin = TRUE)
            AND (owner_user_id IS NOT NULL OR :is_admin = TRUE)
            AND (
                owner_first_name ILIKE :pattern
                OR owner_last_name  ILIKE :pattern
                OR property_street  ILIKE :pattern
            )
        ORDER BY
            CASE
                WHEN owner_first_name ILIKE :prefix_pattern THEN 0
                WHEN owner_last_name  ILIKE :prefix_pattern THEN 0
                WHEN property_street  ILIKE :prefix_pattern THEN 0
                ELSE 1
            END,
            COALESCE(owner_last_name, property_street)
        LIMIT 10
    """)
    _leads_sql_like = text("""
        SELECT
            id,
            owner_first_name,
            owner_last_name,
            property_street,
            lead_score,
            owner_user_id
        FROM leads
        WHERE
            (owner_user_id = :user_id OR :is_admin = 1)
            AND (owner_user_id IS NOT NULL OR :is_admin = 1)
            AND (
                LOWER(owner_first_name) LIKE LOWER(:pattern)
                OR LOWER(owner_last_name)  LIKE LOWER(:pattern)
                OR LOWER(property_street)  LIKE LOWER(:pattern)
            )
        ORDER BY
            CASE
                WHEN LOWER(owner_first_name) LIKE LOWER(:prefix_pattern) THEN 0
                WHEN LOWER(owner_last_name)  LIKE LOWER(:prefix_pattern) THEN 0
                WHEN LOWER(property_street)  LIKE LOWER(:prefix_pattern) THEN 0
                ELSE 1
            END,
            COALESCE(owner_last_name, property_street)
        LIMIT 10
    """)
    _params = {
        'user_id': user_id,
        'is_admin': is_admin,
        'pattern': pattern,
        'prefix_pattern': prefix_pattern,
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
        first = (row.owner_first_name or '').strip()
        last = (row.owner_last_name or '').strip()
        street = (row.property_street or '').strip()

        if first and last:
            label = f"{first} {last}"
        elif first:
            label = first
        elif last:
            label = last
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
