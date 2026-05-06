"""Multifamily Excel/Google Sheets import/export API endpoints.

Provides endpoints for exporting a Deal to an Excel workbook or Google Sheets
document, and importing a workbook to create a new Deal.

Requirements: 12.1-12.5, 13.1-13.4
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request, send_file
from marshmallow import ValidationError

from app import db, limiter
from app.exceptions import RealEstateAnalysisException
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.excel_export_service import ExcelExportService
from app.services.multifamily.excel_import_service import ExcelImportService
from app.services.multifamily.google_sheets_export_service import GoogleSheetsExportService

logger = logging.getLogger(__name__)

multifamily_import_export_bp = Blueprint('multifamily_import_export', __name__)


# ---------------------------------------------------------------------------
# Shared error handling (same pattern as other multifamily controllers)
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
        except RealEstateAnalysisException as e:
            logger.warning("Application error [%s]: %s", e.status_code, e.message)
            return jsonify({
                'error': e.message,
                **e.payload,
            }), e.status_code
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


def get_user_id() -> str:
    """Extract user ID from request headers."""
    return request.headers.get('X-User-Id', 'anonymous')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@multifamily_import_export_bp.route('/deals/<int:deal_id>/export/excel', methods=['GET'])
@handle_errors
def export_deal_excel(deal_id):
    """Export a Deal to an Excel workbook.

    Returns the .xlsx file as a downloadable attachment.

    Requirements: 12.1-12.4
    """
    import io

    user_id = get_user_id()

    # Permission check
    deal_service = DealService()
    if not deal_service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    export_service = ExcelExportService()
    xlsx_bytes = export_service.export_deal(deal_id)

    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'deal_{deal_id}_pro_forma.xlsx',
    )


@multifamily_import_export_bp.route('/deals/import/excel', methods=['POST'])
@limiter.limit("10 per hour")
@handle_errors
def import_deal_excel():
    """Import an Excel workbook to create a new Deal.

    Expects a multipart/form-data request with a 'file' field containing
    the .xlsx workbook.

    Requirements: 13.1-13.4
    """
    user_id = get_user_id()

    if 'file' not in request.files:
        return jsonify({
            'error': 'Validation error',
            'message': 'No file provided. Upload a .xlsx file in the "file" field.',
        }), 400

    file = request.files['file']
    if not file.filename or not file.filename.endswith('.xlsx'):
        return jsonify({
            'error': 'Validation error',
            'message': 'File must be a .xlsx workbook.',
        }), 400

    import_service = ExcelImportService()
    result = import_service.import_workbook(user_id, file)
    db.session.commit()

    # Build the response with parse report
    parse_report = []
    for report in result.parse_report:
        parse_report.append({
            'sheet_name': report.sheet_name,
            'rows_parsed': report.rows_parsed,
            'rows_skipped': report.rows_skipped,
            'warnings': report.warnings,
        })

    return jsonify({
        'deal_id': result.deal_id,
        'message': 'Workbook imported successfully',
        'parse_report': parse_report,
    }), 201


@multifamily_import_export_bp.route('/deals/<int:deal_id>/export/sheets', methods=['GET'])
@handle_errors
def export_deal_sheets(deal_id):
    """Export a Deal to a new Google Sheets document.

    Requires the requesting user to have previously authenticated with Google
    OAuth2 (via the existing /api/leads/import/authenticate endpoint).  The
    stored OAuthToken is retrieved from the database and used to create a new
    Google Sheets spreadsheet with the same 10-sheet structure as the Excel
    export.

    Returns:
        JSON with ``url`` pointing to the created Google Sheets document.

    Requirements: 12.5
    """
    from app.models.import_job import OAuthToken

    user_id = get_user_id()

    # Permission check — same guard as the Excel export route
    deal_service = DealService()
    if not deal_service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    # Retrieve the stored OAuth token for this user
    oauth_token = OAuthToken.query.filter_by(user_id=user_id).first()
    if oauth_token is None:
        return jsonify({
            'error': 'Google account not connected',
            'error_type': 'oauth_token_missing',
            'message': (
                'No Google OAuth token found for this user. '
                'Please authenticate via /api/leads/import/authenticate first.'
            ),
        }), 401

    sheets_service = GoogleSheetsExportService()
    url = sheets_service.export_deal_to_sheets(deal_id, oauth_token)

    logger.info("Deal %s exported to Google Sheets by user %s: %s", deal_id, user_id, url)
    return jsonify({
        'url': url,
        'message': 'Deal exported successfully to Google Sheets',
    }), 200
