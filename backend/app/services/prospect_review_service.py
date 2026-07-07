"""Approve / reject prospect candidates and import as leads."""
from __future__ import annotations

import logging
from datetime import datetime

from app import db
from app.models.lead import Property
from app.models.motivation_signal import ProspectCandidate, ProspectFeedState
from app.services.cook_county_prospect_config import (
    chicago_data_api_configured,
    min_motivation_score_for_queue,
)
from app.services.prospect_area_filter_service import apply_area_filter_to_candidates
from app.services.cook_county_enrichment_service import schedule_cook_county_enrichment_after_commit
from app.services.deduplication_engine import DeduplicationEngine
from app.services.lead_ingestion_service import LeadIngestionService
from app.services.motivation_signal_service import MotivationSignalService
from app.services.lead_refresh import refresh_lead_scoring

logger = logging.getLogger(__name__)

SIGNAL_SOURCE_TYPE_MAP = {
    'TAX_SCAVENGER_SALE': 'tax_distress',
    'TAX_ANNUAL_SALE': 'tax_distress',
    'CHICAGO_SCOFFLAW': 'manual_distress',
    'BUILDING_VIOLATION': 'manual_distress',
}


def _candidate_base_query(owner_user_id: str, *, is_admin: bool = False):
    query = ProspectCandidate.query
    if not is_admin:
        query = query.filter_by(owner_user_id=owner_user_id)
    return query


def _queue_eligible_query(query):
    """Prospects that meet address and motivation admission rules."""
    min_score = min_motivation_score_for_queue()
    return (
        query.filter(ProspectCandidate.motivation_score >= min_score)
        .filter(ProspectCandidate.property_street.isnot(None))
        .filter(ProspectCandidate.property_street != '')
    )


def _fetch_eligible_candidates(
    owner_user_id: str,
    *,
    status: str = 'pending',
    min_score: float = 0.0,
    is_admin: bool = False,
) -> list[ProspectCandidate]:
    query = _candidate_base_query(owner_user_id, is_admin=is_admin)
    if status:
        query = query.filter_by(status=status)
    if status == 'pending':
        query = _queue_eligible_query(query)
    if min_score > 0:
        query = query.filter(ProspectCandidate.motivation_score >= min_score)
    return query.order_by(ProspectCandidate.motivation_score.desc()).all()


def count_pending_candidates(owner_user_id: str, *, is_admin: bool = False) -> int:
    rows = _fetch_eligible_candidates(owner_user_id, status='pending', is_admin=is_admin)
    filtered, stats = apply_area_filter_to_candidates(rows, owner_user_id)
    return stats.total_filtered


def get_prospect_feed_status() -> dict:
    """Return sync timestamps and per-feed state for the prospect review UI."""
    states = ProspectFeedState.query.order_by(ProspectFeedState.feed_name).all()
    feeds = [
        {
            'feed_name': state.feed_name,
            'last_synced_at': (
                state.last_synced_at.isoformat() + 'Z' if state.last_synced_at else None
            ),
            'rows_processed': state.rows_processed,
        }
        for state in states
    ]
    synced_times = [state.last_synced_at for state in states if state.last_synced_at]
    last_sync_at = max(synced_times) if synced_times else None
    return {
        'last_sync_at': last_sync_at.isoformat() + 'Z' if last_sync_at else None,
        'feeds': feeds,
        'next_scheduled_label': '11:00 PM Central',
        'chicago_api_configured': chicago_data_api_configured(),
    }


def list_candidates(
    owner_user_id: str,
    *,
    status: str = 'pending',
    page: int = 1,
    per_page: int = 20,
    min_score: float = 0.0,
    is_admin: bool = False,
) -> tuple[list[ProspectCandidate], int, dict]:
    all_rows = _fetch_eligible_candidates(
        owner_user_id,
        status=status,
        min_score=min_score,
        is_admin=is_admin,
    )
    filtered, stats = apply_area_filter_to_candidates(all_rows, owner_user_id)
    total = len(filtered)
    start = (page - 1) * per_page
    rows = filtered[start:start + per_page]
    return rows, total, stats.as_dict()


def reject_candidate(
    candidate_id: int,
    owner_user_id: str,
    reviewer_id: str,
    reason: str = '',
    *,
    is_admin: bool = False,
) -> ProspectCandidate:
    query = _candidate_base_query(owner_user_id, is_admin=is_admin)
    candidate = query.filter_by(id=candidate_id).first()
    if candidate is None:
        raise ValueError(f'Prospect candidate {candidate_id} not found')
    if candidate.status != 'pending':
        raise ValueError(f'Candidate {candidate_id} is not pending')
    candidate.status = 'rejected'
    candidate.reviewed_at = datetime.utcnow()
    candidate.reviewed_by = reviewer_id
    candidate.rejection_reason = reason or None
    db.session.commit()
    return candidate


def approve_candidate(
    candidate_id: int,
    owner_user_id: str,
    reviewer_id: str,
    *,
    is_admin: bool = False,
) -> dict:
    query = _candidate_base_query(owner_user_id, is_admin=is_admin)
    candidate = query.filter_by(id=candidate_id).first()
    if candidate is None:
        raise ValueError(f'Prospect candidate {candidate_id} not found')
    if candidate.status not in ('pending', 'duplicate'):
        raise ValueError(f'Candidate {candidate_id} cannot be approved from status {candidate.status}')
    if not (candidate.property_street or '').strip():
        raise ValueError('Cannot approve prospect without a street address')

    if candidate.duplicate_lead_id:
        lead = db.session.get(Property, candidate.duplicate_lead_id)
        if lead:
            candidate.status = 'imported'
            candidate.imported_lead_id = lead.id
            candidate.reviewed_at = datetime.utcnow()
            candidate.reviewed_by = reviewer_id
            db.session.commit()
            return {'lead_id': lead.id, 'duplicate': True}

    source_type = SIGNAL_SOURCE_TYPE_MAP.get(
        candidate.primary_signal_type,
        'manual_distress',
    )
    normalized = {
        'property_street': candidate.property_street,
        'property_city': candidate.property_city,
        'property_state': candidate.property_state or 'IL',
        'county_assessor_pin': candidate.pin,
        'source_type': source_type,
        'data_source': 'cook_county_prospect_feed',
        'owner_user_id': owner_user_id,
        'lead_category': 'residential',
        'notes': f'Imported from prospect feed {candidate.source_feed}',
    }

    dedup = DeduplicationEngine()
    from app.services.gis.base import GISConnectorRegistry
    ingestion = LeadIngestionService(dedup_engine=dedup, gis_registry=GISConnectorRegistry)
    job = ingestion._create_import_job(owner_user_id, 'prospect_feed')
    result = dedup.process_record(normalized, job.id)
    lead = result.lead
    is_creation = result.outcome == 'created'

    connector = ingestion._gis_connector_for_lead(lead)
    if connector:
        ingestion._enrich_with_gis(lead, connector, job.id)

    ingestion._set_skip_trace_flag(lead, is_creation)
    ingestion._set_review_required_flag(lead, is_creation)
    lead.last_import_job_id = job.id
    db.session.add(lead)
    db.session.flush()

    if candidate.signals:
        MotivationSignalService().copy_signals_to_lead(candidate.signals, lead.id)
        MotivationSignalService().sync_from_lead(lead, commit=False)

    schedule_cook_county_enrichment_after_commit(lead.id)

    job.status = 'completed'
    job.completed_at = datetime.utcnow()
    job.rows_processed = 1
    job.rows_imported = 1
    db.session.flush()

    refresh_lead_scoring(lead.id)

    candidate.status = 'imported'
    candidate.imported_lead_id = lead.id
    candidate.reviewed_at = datetime.utcnow()
    candidate.reviewed_by = reviewer_id
    db.session.commit()

    return {'lead_id': lead.id, 'duplicate': False, 'import_job_id': job.id}
