"""Extract, persist, and score structured motivation signals for leads."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from app import db
from app.models.motivation_signal import MotivationSignal
from app.services.scoring_rubric import MOTIVATION_KEYWORDS, SOURCE_TYPE_DISTRESS_QUALIFYING

logger = logging.getLogger(__name__)

SIGNAL_LABELS = {
    'TAX_SCAVENGER_SALE': 'Scavenger tax sale',
    'TAX_ANNUAL_SALE': 'Annual tax sale',
    'CHICAGO_SCOFFLAW': 'Chicago scofflaw',
    'BUILDING_VIOLATION': 'Building violation',
    'VACANT_BUILDING': 'Vacant / abandoned building',
    'FORECLOSURE_AUCTION': 'Sheriff foreclosure auction',
    'BUILDING_COMPLAINT': '311 building complaint',
    'MANUAL_PRIORITY': 'Manual priority',
    'NOTES_KEYWORD': 'Motivation in notes',
    'SOURCE_TYPE_DISTRESS': 'Distress source type',
    'HUBSPOT_MOTIVATION': 'HubSpot motivation',
    'TAX_EXEMPT': 'Tax exempt',
    'ASSESSMENT_APPEAL': 'Assessment appeal',
}

POINTS_RESIDENTIAL = {
    'TAX_SCAVENGER_SALE': 12.0,
    'TAX_ANNUAL_SALE': 10.0,
    'CHICAGO_SCOFFLAW': 10.0,
    'BUILDING_VIOLATION': 5.0,
    'BUILDING_VIOLATION_SEVERE': 8.0,
    'VACANT_BUILDING': 8.0,
    'FORECLOSURE_AUCTION': 12.0,
    'BUILDING_COMPLAINT': 5.0,
    'MANUAL_PRIORITY': 10.0,
    'NOTES_KEYWORD': 10.0,
    'SOURCE_TYPE_DISTRESS': 10.0,
    'HUBSPOT_MOTIVATION': 5.0,
    'TAX_EXEMPT': -15.0,
    'ASSESSMENT_APPEAL': 2.0,
}

POINTS_COMMERCIAL = {
    'TAX_SCAVENGER_SALE': 10.0,
    'TAX_ANNUAL_SALE': 8.0,
    'CHICAGO_SCOFFLAW': 8.0,
    'BUILDING_VIOLATION': 4.0,
    'BUILDING_VIOLATION_SEVERE': 7.0,
    'VACANT_BUILDING': 7.0,
    'FORECLOSURE_AUCTION': 10.0,
    'BUILDING_COMPLAINT': 4.0,
    'MANUAL_PRIORITY': 10.0,
    'NOTES_KEYWORD': 10.0,
    'SOURCE_TYPE_DISTRESS': 10.0,
    'HUBSPOT_MOTIVATION': 5.0,
    'TAX_EXEMPT': -15.0,
    'ASSESSMENT_APPEAL': 2.0,
}

STRUCTURED_MOTIVATION_CAP = {'residential': 25.0, 'commercial': 20.0}
TOTAL_MOTIVATION_CAP = 40.0

SEVERE_VIOLATION_CODES = frozenset({'CN', 'EV', 'BLDG', 'FAIL'})

# Signals whose points decay with event age (full weight through 90 days).
RECENCY_DECAY_SIGNAL_TYPES = frozenset({
    'BUILDING_VIOLATION',
    'BUILDING_COMPLAINT',
    'VACANT_BUILDING',
})

SIGNAL_EVENT_DATE_KEYS: dict[str, tuple[str, ...]] = {
    'BUILDING_VIOLATION': ('violation_date', 'date_issued'),
    'BUILDING_COMPLAINT': ('created_date',),
    'VACANT_BUILDING': ('created_date',),
}


@dataclass
class ExtractedSignal:
    signal_type: str
    severity: str
    points: float
    source: str
    source_dataset: Optional[str] = None
    evidence_key: Optional[str] = None
    evidence: Optional[dict] = None
    base_points: Optional[float] = None
    recency_multiplier: Optional[float] = None
    event_date: Optional[str] = None


def _parse_json_field(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value


def _points_for(signal_type: str, lead_category: str, *, severe: bool = False) -> float:
    table = POINTS_COMMERCIAL if lead_category == 'commercial' else POINTS_RESIDENTIAL
    if signal_type == 'BUILDING_VIOLATION' and severe:
        return table.get('BUILDING_VIOLATION_SEVERE', table['BUILDING_VIOLATION'])
    return table.get(signal_type, 0.0)


def _violation_severity(code: Optional[str]) -> bool:
    if not code:
        return False
    upper = str(code).upper()
    return any(upper.startswith(prefix) for prefix in SEVERE_VIOLATION_CODES)


def _parse_event_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def parse_signal_event_date(signal_type: str, evidence: Optional[dict]) -> Optional[datetime]:
    """Return the most relevant event date for recency scoring."""
    if not evidence or not isinstance(evidence, dict):
        return None
    rows = evidence.get('rows')
    if isinstance(rows, list):
        dates = [
            parse_signal_event_date(signal_type, row)
            for row in rows
            if isinstance(row, dict)
        ]
        dates = [d for d in dates if d is not None]
        return max(dates) if dates else None
    for key in SIGNAL_EVENT_DATE_KEYS.get(signal_type, ()):
        parsed = _parse_event_datetime(evidence.get(key))
        if parsed is not None:
            return parsed
    return None


def recency_multiplier(
    event_date: Optional[datetime],
    *,
    reference: Optional[datetime] = None,
) -> float:
    """Decay weight by age: 100% (0–90d), 75% (91–365d), 50% (1–2y), 25% (2y+)."""
    if event_date is None:
        return 1.0
    ref = reference or datetime.utcnow()
    days = (ref.date() - event_date.date()).days
    if days <= 90:
        return 1.0
    if days <= 365:
        return 0.75
    if days <= 730:
        return 0.50
    return 0.25


def points_with_recency(
    signal_type: str,
    lead_category: str,
    evidence: Optional[dict],
    *,
    severe: bool = False,
    reference: Optional[datetime] = None,
) -> tuple[float, float, float, Optional[str]]:
    """Return (adjusted_points, base_points, multiplier, event_date_iso)."""
    base = _points_for(signal_type, lead_category, severe=severe)
    if signal_type not in RECENCY_DECAY_SIGNAL_TYPES:
        return base, base, 1.0, None
    event_date = parse_signal_event_date(signal_type, evidence)
    multiplier = recency_multiplier(event_date, reference=reference)
    adjusted = round(base * multiplier, 2)
    event_iso = event_date.date().isoformat() if event_date else None
    return adjusted, base, multiplier, event_iso


def _signal_with_recency(
    *,
    signal_type: str,
    severity: str,
    lead_category: str,
    source: str,
    source_dataset: Optional[str],
    evidence_key: Optional[str],
    evidence: Optional[dict],
    severe: bool = False,
    reference: Optional[datetime] = None,
) -> ExtractedSignal:
    adjusted, base, multiplier, event_iso = points_with_recency(
        signal_type,
        lead_category,
        evidence,
        severe=severe,
        reference=reference,
    )
    return ExtractedSignal(
        signal_type=signal_type,
        severity=severity,
        points=adjusted,
        source=source,
        source_dataset=source_dataset,
        evidence_key=evidence_key,
        evidence=evidence,
        base_points=base if multiplier < 1.0 else None,
        recency_multiplier=multiplier if multiplier < 1.0 else None,
        event_date=event_iso,
    )


def extract_signals_from_lead(lead) -> list[ExtractedSignal]:
    """Derive motivation signals from lead columns without DB access."""
    category = getattr(lead, 'lead_category', 'residential') or 'residential'
    signals: list[ExtractedSignal] = []

    source_type = getattr(lead, 'source_type', None)
    if source_type in SOURCE_TYPE_DISTRESS_QUALIFYING:
        signals.append(ExtractedSignal(
            signal_type='SOURCE_TYPE_DISTRESS',
            severity='high',
            points=_points_for('SOURCE_TYPE_DISTRESS', category),
            source='ingestion',
            evidence_key=source_type,
            evidence={'source_type': source_type},
        ))

    priority = getattr(lead, 'manual_priority', None)
    if priority is not None:
        try:
            pval = float(priority)
            if pval > 0:
                signals.append(ExtractedSignal(
                    signal_type='MANUAL_PRIORITY',
                    severity='high' if pval >= 4 else 'medium',
                    points=min(pval * 2.0, _points_for('MANUAL_PRIORITY', category)),
                    source='ingestion',
                    evidence_key=str(int(pval)),
                    evidence={'manual_priority': pval},
                ))
        except (TypeError, ValueError):
            pass

    notes = getattr(lead, 'notes', None) or ''
    if notes.strip():
        notes_lower = notes.lower()
        for keyword in MOTIVATION_KEYWORDS:
            if keyword in notes_lower:
                signals.append(ExtractedSignal(
                    signal_type='NOTES_KEYWORD',
                    severity='medium',
                    points=_points_for('NOTES_KEYWORD', category),
                    source='notes',
                    evidence_key=keyword,
                    evidence={'keyword': keyword},
                ))
                break

    tax_distress = _parse_json_field(getattr(lead, 'tax_distress_data', None))
    if isinstance(tax_distress, dict):
        if tax_distress.get('scavenger_tax_sale'):
            rows = tax_distress['scavenger_tax_sale']
            if isinstance(rows, list) and rows:
                signals.append(ExtractedSignal(
                    signal_type='TAX_SCAVENGER_SALE',
                    severity='high',
                    points=_points_for('TAX_SCAVENGER_SALE', category),
                    source='cook_county_enrichment',
                    source_dataset='ydgz-vkrp',
                    evidence_key='scavenger',
                    evidence={'rows': rows[:3]},
                ))
        elif tax_distress:
            signals.append(ExtractedSignal(
                signal_type='TAX_ANNUAL_SALE',
                severity='high',
                points=_points_for('TAX_ANNUAL_SALE', category),
                source='cook_county_enrichment',
                source_dataset='55ju-2fs9',
                evidence_key='tax_sale',
                evidence={'rows': tax_distress if isinstance(tax_distress, list) else [tax_distress]},
            ))
    elif isinstance(tax_distress, list) and tax_distress:
        signals.append(ExtractedSignal(
            signal_type='TAX_ANNUAL_SALE',
            severity='high',
            points=_points_for('TAX_ANNUAL_SALE', category),
            source='cook_county_enrichment',
            source_dataset='55ju-2fs9',
            evidence_key='tax_sale',
            evidence={'rows': tax_distress[:3]},
        ))

    violation_data = _parse_json_field(getattr(lead, 'violation_data', None))
    if isinstance(violation_data, dict):
        scofflaw = violation_data.get('chicago_scofflaw')
        if isinstance(scofflaw, list) and scofflaw:
            signals.append(ExtractedSignal(
                signal_type='CHICAGO_SCOFFLAW',
                severity='high',
                points=_points_for('CHICAGO_SCOFFLAW', category),
                source='cook_county_enrichment',
                source_dataset='rz4d-qp2m',
                evidence_key='scofflaw',
                evidence={'rows': scofflaw[:3]},
            ))
        violations = violation_data.get('chicago_building_violations')
        if isinstance(violations, list) and violations:
            violation_rows = [row for row in violations[:3] if isinstance(row, dict)]
            severe = any(
                _violation_severity(row.get('violation_code'))
                for row in violation_rows
            )
            violation_evidence = {'rows': violation_rows, 'severe': severe}
            signals.append(_signal_with_recency(
                signal_type='BUILDING_VIOLATION',
                severity='high' if severe else 'medium',
                lead_category=category,
                source='cook_county_enrichment',
                source_dataset='22u3-xenr',
                evidence_key='violations',
                evidence=violation_evidence,
                severe=severe,
            ))
        vacant = violation_data.get('chicago_vacant_buildings')
        if isinstance(vacant, list) and vacant:
            vacant_rows = [row for row in vacant[:3] if isinstance(row, dict)]
            signals.append(_signal_with_recency(
                signal_type='VACANT_BUILDING',
                severity='high',
                lead_category=category,
                source='cook_county_enrichment',
                source_dataset='v6vf-nfxy',
                evidence_key='vacant',
                evidence={'rows': vacant_rows},
            ))
        complaints = violation_data.get('chicago_311_complaints')
        if isinstance(complaints, list) and complaints:
            complaint_rows = [row for row in complaints[:3] if isinstance(row, dict)]
            signals.append(_signal_with_recency(
                signal_type='BUILDING_COMPLAINT',
                severity='medium',
                lead_category=category,
                source='cook_county_enrichment',
                source_dataset='v6vf-nfxy',
                evidence_key='311_complaints',
                evidence={'rows': complaint_rows},
            ))
        foreclosure = violation_data.get('cook_county_foreclosure')
        if isinstance(foreclosure, list) and foreclosure:
            signals.append(ExtractedSignal(
                signal_type='FORECLOSURE_AUCTION',
                severity='high',
                points=_points_for('FORECLOSURE_AUCTION', category),
                source='cook_county_enrichment',
                source_dataset='cook_county_sheriff',
                evidence_key='foreclosure',
                evidence={'rows': foreclosure[:3]},
            ))

    permit_data = _parse_json_field(getattr(lead, 'permit_data', None))
    if isinstance(permit_data, dict):
        if permit_data.get('tax_exempt'):
            signals.append(ExtractedSignal(
                signal_type='TAX_EXEMPT',
                severity='low',
                points=_points_for('TAX_EXEMPT', category),
                source='cook_county_enrichment',
                source_dataset='vgzx-68gb',
                evidence_key='tax_exempt',
                evidence=permit_data.get('tax_exempt'),
            ))
        appeals = permit_data.get('appeals')
        if isinstance(appeals, list) and appeals:
            signals.append(ExtractedSignal(
                signal_type='ASSESSMENT_APPEAL',
                severity='low',
                points=_points_for('ASSESSMENT_APPEAL', category),
                source='cook_county_enrichment',
                source_dataset='y282-6ig3',
                evidence_key='appeals',
                evidence={'rows': appeals[:3]},
            ))

    return signals


def _cap_score(raw: float, lead_category: str) -> float:
    cap = STRUCTURED_MOTIVATION_CAP.get(lead_category, STRUCTURED_MOTIVATION_CAP['residential'])
    return max(-cap, min(raw, cap))


def compute_structured_motivation_score(lead, *, signals: Optional[list[ExtractedSignal]] = None) -> float:
    """Sum active signal points with category cap."""
    category = getattr(lead, 'lead_category', 'residential') or 'residential'
    lead_id = getattr(lead, 'id', None)

    if signals is None and isinstance(lead_id, int):
        try:
            from flask import has_app_context
        except ImportError:
            has_app_context = lambda: False  # noqa: E731
        if has_app_context():
            rows = (
                MotivationSignal.query.filter_by(lead_id=lead_id, is_active=True).all()
            )
            if rows:
                return _cap_score(sum(r.points for r in rows), category)

    extracted = signals if signals is not None else extract_signals_from_lead(lead)
    return _cap_score(sum(s.points for s in extracted), category)


def build_signal_summary(signals: list[ExtractedSignal], limit: int = 3) -> list[dict]:
    ranked = sorted(signals, key=lambda s: abs(s.points), reverse=True)
    summary = []
    for sig in ranked[:limit]:
        summary.append({
            'signal_type': sig.signal_type,
            'label': SIGNAL_LABELS.get(sig.signal_type, sig.signal_type),
            'points': sig.points,
            'severity': sig.severity,
        })
    return summary


def primary_signal_label(lead) -> Optional[str]:
    summary = getattr(lead, 'motivation_signal_summary', None) or []
    if isinstance(summary, list) and summary:
        return summary[0].get('label')
    signals = extract_signals_from_lead(lead)
    if not signals:
        return None
    top = max(signals, key=lambda s: abs(s.points))
    return SIGNAL_LABELS.get(top.signal_type, top.signal_type)


class MotivationSignalService:
    """Sync motivation signals for a lead and update denormalized score fields."""

    def sync_from_lead(self, lead, *, commit: bool = True) -> float:
        lead_id = getattr(lead, 'id', None)
        extracted = extract_signals_from_lead(lead)
        active_keys = {
            (s.signal_type, s.evidence_key or '')
            for s in extracted
        }

        if isinstance(lead_id, int):
            existing = MotivationSignal.query.filter_by(lead_id=lead_id).all()
            for row in existing:
                key = (row.signal_type, row.evidence_key or '')
                if key not in active_keys:
                    row.is_active = False

            for sig in extracted:
                evidence_key = sig.evidence_key or ''
                row = MotivationSignal.query.filter_by(
                    lead_id=lead_id,
                    signal_type=sig.signal_type,
                    evidence_key=evidence_key,
                ).first()
                if row is None:
                    row = MotivationSignal(
                        lead_id=lead_id,
                        signal_type=sig.signal_type,
                        evidence_key=evidence_key,
                    )
                    db.session.add(row)
                row.severity = sig.severity
                row.points = sig.points
                row.source = sig.source
                row.source_dataset = sig.source_dataset
                row.evidence = sig.evidence
                row.detected_at = datetime.utcnow()
                row.is_active = True

        score = compute_structured_motivation_score(lead, signals=extracted)
        lead.motivation_score = score
        lead.motivation_signal_summary = build_signal_summary(extracted)

        if commit and isinstance(lead_id, int):
            db.session.add(lead)
            db.session.commit()
        elif commit:
            db.session.add(lead)
            db.session.flush()

        return score

    def copy_signals_to_lead(self, from_candidate_signals: list[dict], lead_id: int) -> None:
        """Attach precomputed prospect signals to a newly imported lead."""
        for item in from_candidate_signals:
            sig_type = item.get('signal_type')
            if not sig_type:
                continue
            row = MotivationSignal(
                lead_id=lead_id,
                signal_type=sig_type,
                severity=item.get('severity', 'medium'),
                points=float(item.get('points', 0)),
                source='prospect_feed',
                evidence_key=item.get('evidence_key'),
                evidence=item.get('evidence'),
                is_active=True,
            )
            db.session.add(row)


def structured_motivation_score(lead) -> float:
    """Rubric entry point — uses persisted signals when available."""
    return compute_structured_motivation_score(lead)


BACKFILL_BATCH_SIZE = 200


def backfill_motivation_signals(
    *,
    batch_size: int = BACKFILL_BATCH_SIZE,
    last_id: int = 0,
) -> dict:
    """Nightly batch: sync motivation signals and rescore Cook County leads."""
    from app.models.lead import Property as LeadModel
    from app.services.cook_county_enrichment_service import COOK_COUNTY_MARKET
    from app.services.gis.routing import _resolve_market
    from app.services.lead_refresh import refresh_lead_scoring

    summary = {
        'status': 'completed',
        'processed': 0,
        'synced': 0,
        'skipped': 0,
        'errors': 0,
        'last_id': last_id,
    }
    svc = MotivationSignalService()
    cursor = last_id

    while True:
        batch = (
            LeadModel.query.filter(
                LeadModel.id > cursor,
                LeadModel.property_state.in_(('IL', 'Illinois', 'il')),
            )
            .order_by(LeadModel.id)
            .limit(batch_size)
            .all()
        )
        if not batch:
            break

        for lead in batch:
            cursor = lead.id
            summary['processed'] += 1
            if _resolve_market(lead) != COOK_COUNTY_MARKET:
                summary['skipped'] += 1
                continue
            try:
                svc.sync_from_lead(lead, commit=False)
                refresh_lead_scoring(lead.id)
                summary['synced'] += 1
            except Exception as exc:
                logger.warning('backfill_motivation_signals failed for lead %s: %s', lead.id, exc)
                summary['errors'] += 1
                db.session.rollback()

        try:
            db.session.commit()
        except Exception as exc:
            logger.error('backfill_motivation_signals commit failed: %s', exc)
            db.session.rollback()
            summary['status'] = 'error'
            break

        summary['last_id'] = cursor
        if len(batch) < batch_size:
            break

    return summary
