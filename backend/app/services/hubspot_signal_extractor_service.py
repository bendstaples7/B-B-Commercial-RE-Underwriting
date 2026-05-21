"""HubSpotSignalExtractorService — extracts seller motivation signals from HubSpot engagements."""
import logging
from datetime import datetime
from typing import Optional

from app import db
from app.models.hubspot_signal import HubSpotSignal
from app.models.hubspot_signal_dictionary import HubSpotSignalDictionary
from app.models.lead import Lead
from app.models.task import Task
from app.models.task_association import TaskAssociation

logger = logging.getLogger(__name__)


class HubSpotSignalExtractorService:
    """
    Extracts HubSpot_Signal records from imported engagement body text using a
    configurable keyword dictionary stored in the hubspot_signal_dictionary table.

    Usage:
        service = HubSpotSignalExtractorService()
        signals = service.extract_signals(engagement, lead_id=42)
        db.session.add_all(signals)
        db.session.flush()
        service.apply_suppression(signals)
        db.session.commit()
    """

    def __init__(self):
        self._dictionary = self._load_dictionary()

    # ------------------------------------------------------------------
    # Dictionary loading
    # ------------------------------------------------------------------

    def _load_dictionary(self) -> dict:
        """
        Query all HubSpotSignalDictionary records and return a mapping of
        signal_type → list[keyword] (all keywords lowercased for fast matching).
        """
        records = HubSpotSignalDictionary.query.all()
        result = {}
        for record in records:
            keywords = record.keywords or []
            result[record.signal_type] = [kw.lower() for kw in keywords]
        logger.debug("Loaded signal dictionary with %d signal types.", len(result))
        return result

    # ------------------------------------------------------------------
    # Body text extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_body_text(engagement) -> str:
        """
        Extract the body text from a HubSpotEngagement's raw_payload.

        HubSpot engagement payloads nest body text in different locations
        depending on the engagement type:
          - metadata.body  (notes, calls)
          - engagement.bodyPreview  (older API format)

        Returns an empty string if no body text is found.
        """
        payload = engagement.raw_payload or {}

        # Try metadata.body first (most common)
        metadata = payload.get('metadata') or {}
        body = metadata.get('body')
        if body:
            return str(body)

        # Fall back to engagement.bodyPreview
        engagement_block = payload.get('engagement') or {}
        body_preview = engagement_block.get('bodyPreview')
        if body_preview:
            return str(body_preview)

        return ''

    # ------------------------------------------------------------------
    # Overdue task check
    # ------------------------------------------------------------------

    @staticmethod
    def _has_overdue_task(lead_id: int) -> bool:
        """
        Return True if the lead has at least one open Task whose due_date is
        in the past (i.e., the task is overdue).

        Per Requirement 16.4: FOLLOW_UP_OVERDUE is set based on the presence
        of an open Task with a past due date, NOT on keyword matching alone.
        """
        now = datetime.utcnow()
        overdue_task = (
            db.session.query(Task)
            .join(TaskAssociation, TaskAssociation.task_id == Task.id)
            .filter(
                TaskAssociation.target_type == 'lead',
                TaskAssociation.target_id == lead_id,
                Task.status == 'open',
                Task.due_date != None,  # noqa: E711
                Task.due_date < now,
            )
            .first()
        )
        return overdue_task is not None

    # ------------------------------------------------------------------
    # Signal extraction
    # ------------------------------------------------------------------

    def extract_signals(self, engagement, lead_id: int) -> list:
        """
        Scan the engagement body text case-insensitively against all keyword
        lists in the dictionary and return a list of HubSpotSignal records
        ready to be persisted.

        Special handling:
          - FOLLOW_UP_OVERDUE is determined by checking for an open overdue
            Task associated with the lead, not by keyword matching.

        The caller is responsible for adding the returned records to the
        session and committing.

        Args:
            engagement: A HubSpotEngagement model instance.
            lead_id:    The internal Lead.id to associate signals with.

        Returns:
            List of unsaved HubSpotSignal instances.
        """
        body_text = self._get_body_text(engagement)
        body_lower = body_text.lower()

        source_engagement_id = str(engagement.hubspot_id) if engagement.hubspot_id else None
        signals = []

        for signal_type, keywords in self._dictionary.items():
            # FOLLOW_UP_OVERDUE is handled separately — skip keyword matching
            if signal_type == 'FOLLOW_UP_OVERDUE':
                continue

            matched_keyword = self._find_keyword(body_lower, keywords)
            if matched_keyword:
                signal = HubSpotSignal(
                    lead_id=lead_id,
                    signal_type=signal_type,
                    source_engagement_id=source_engagement_id,
                    raw_evidence=matched_keyword,
                )
                signals.append(signal)
                logger.debug(
                    "Signal %s extracted for lead_id=%d (keyword=%r).",
                    signal_type, lead_id, matched_keyword,
                )

        # FOLLOW_UP_OVERDUE: check for an open overdue task on this lead
        if self._has_overdue_task(lead_id):
            signal = HubSpotSignal(
                lead_id=lead_id,
                signal_type='FOLLOW_UP_OVERDUE',
                source_engagement_id=source_engagement_id,
                raw_evidence='open overdue task detected',
            )
            signals.append(signal)
            logger.debug(
                "Signal FOLLOW_UP_OVERDUE extracted for lead_id=%d (overdue task).",
                lead_id,
            )

        return signals

    # ------------------------------------------------------------------
    # Keyword matching helper
    # ------------------------------------------------------------------

    @staticmethod
    def _find_keyword(body_lower: str, keywords: list) -> Optional[str]:
        """
        Return the first keyword found in body_lower (case-insensitive
        substring match), or None if no keyword matches.
        """
        for keyword in keywords:
            if keyword in body_lower:
                return keyword
        return None

    # ------------------------------------------------------------------
    # Suppression application
    # ------------------------------------------------------------------

    def apply_suppression(self, signals: list) -> None:
        """
        For any DO_NOT_CONTACT or WRONG_NUMBER signal in the provided list,
        set suppression_flag=True on the associated Lead record and commit.

        Args:
            signals: List of HubSpotSignal instances (already persisted or
                     at least flushed so lead_id is populated).
        """
        suppression_types = {'DO_NOT_CONTACT', 'WRONG_NUMBER'}
        suppressed_lead_ids = set()

        for signal in signals:
            if signal.signal_type in suppression_types:
                suppressed_lead_ids.add(signal.lead_id)

        if not suppressed_lead_ids:
            return

        leads = Lead.query.filter(Lead.id.in_(suppressed_lead_ids)).all()
        for lead in leads:
            if not lead.suppression_flag:
                lead.suppression_flag = True
                logger.info(
                    "Suppression flag set on lead_id=%d due to signal %s.",
                    lead.id,
                    next(
                        s.signal_type for s in signals
                        if s.lead_id == lead.id and s.signal_type in suppression_types
                    ),
                )

        db.session.commit()
