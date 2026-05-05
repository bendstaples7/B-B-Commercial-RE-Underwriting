"""Lead Score API endpoints.

Provides endpoints for retrieving lead scores and triggering recalculation
using the DeterministicScoringEngine.
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request

from app import db, limiter
from app.models.lead import Lead
from app.models.lead_score import LeadScore
from app.services.deterministic_scoring_engine import DeterministicScoringEngine

logger = logging.getLogger(__name__)

lead_score_bp = Blueprint('lead_scores', __name__)

scoring_engine = DeterministicScoringEngine()


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Validation error',
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
# Helpers
# ---------------------------------------------------------------------------

def _serialize_lead_score(score: LeadScore) -> dict:
    """Serialize a LeadScore record to a dictionary."""
    return {
        'id': score.id,
        'lead_id': score.lead_id,
        'property_id': score.property_id,
        'score_version': score.score_version,
        'total_score': score.total_score,
        'score_tier': score.score_tier,
        'data_quality_score': score.data_quality_score,
        'recommended_action': score.recommended_action,
        'top_signals': score.top_signals,
        'score_details': score.score_details,
        'missing_data': score.missing_data,
        'created_at': score.created_at.isoformat() if score.created_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@lead_score_bp.route('/<int:lead_id>', methods=['GET'])
@limiter.limit("600 per minute")
@handle_errors
def get_lead_score(lead_id):
    """Get the latest score and full score history for a lead.

    Returns
    -------
    200: { latest: LeadScoreRecord | null, history: LeadScoreRecord[] }
    404: Lead not found
    """
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({
            'error': 'Lead not found',
            'message': f'Lead {lead_id} does not exist',
        }), 404

    # Get all score records ordered by created_at desc
    score_records = (
        LeadScore.query
        .filter_by(lead_id=lead_id)
        .order_by(LeadScore.created_at.desc())
        .all()
    )

    latest = _serialize_lead_score(score_records[0]) if score_records else None
    history = [_serialize_lead_score(s) for s in score_records]

    return jsonify({
        'latest': latest,
        'history': history,
    }), 200


@lead_score_bp.route('/recalculate', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def recalculate_scores():
    """Recalculate lead score(s).

    Request body (JSON)
    -------------------
    lead_id : int — recalculate a single lead
    source_type : str — recalculate all leads matching this source type
    all : bool — recalculate all active leads

    Exactly one of lead_id, source_type, or all=true must be provided.

    Returns
    -------
    200: { success: true, message: str, score?: LeadScoreRecord, count?: int }
    400: Invalid parameters
    404: Lead not found (when lead_id specified)
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body must be a JSON object',
        }), 400

    lead_id = data.get('lead_id')
    source_type = data.get('source_type')
    recalculate_all = data.get('all', False)

    # Validate that exactly one target is specified
    targets_specified = sum([
        lead_id is not None,
        bool(source_type),
        bool(recalculate_all),
    ])

    if targets_specified == 0:
        return jsonify({
            'error': 'Validation error',
            'message': 'Must specify lead_id, source_type, or all=true',
        }), 400

    if targets_specified > 1:
        return jsonify({
            'error': 'Validation error',
            'message': 'Specify only one of lead_id, source_type, or all=true',
        }), 400

    # Single lead recalculation
    if lead_id is not None:
        try:
            lead_id = int(lead_id)
        except (TypeError, ValueError):
            return jsonify({
                'error': 'Validation error',
                'message': 'lead_id must be an integer',
            }), 400

        lead = db.session.get(Lead, lead_id)
        if not lead:
            return jsonify({
                'error': 'Lead not found',
                'message': f'Lead {lead_id} does not exist',
            }), 404

        score = scoring_engine.recalculate_lead_score(lead)
        logger.info("Recalculated score for lead %d", lead_id)

        return jsonify({
            'success': True,
            'message': f'Score recalculated for lead {lead_id}',
            'score': _serialize_lead_score(score),
        }), 200

    # Source type recalculation
    if source_type:
        count = scoring_engine.recalculate_by_source_type(source_type)
        logger.info("Recalculated %d leads for source_type=%s", count, source_type)

        return jsonify({
            'success': True,
            'message': f'Recalculated scores for {count} leads with source_type "{source_type}"',
            'count': count,
        }), 200

    # All leads recalculation
    if recalculate_all:
        count = scoring_engine.recalculate_all_lead_scores()
        logger.info("Recalculated all lead scores: %d leads", count)

        return jsonify({
            'success': True,
            'message': f'Recalculated scores for {count} leads',
            'count': count,
        }), 200
