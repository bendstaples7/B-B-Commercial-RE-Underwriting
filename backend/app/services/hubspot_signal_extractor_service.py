"""HubSpotSignalExtractorService — extracts seller motivation signals from HubSpot engagements."""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError

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

        Idempotent persistence: a candidate signal is omitted from the returned
        list when an equivalent signal already exists for its dedup key
        ``(lead_id, signal_type, source_engagement_id)`` (see
        ``_signal_already_exists``). This makes re-extraction across repeated
        sync runs safe — the same signal is never persisted twice — while
        distinct sources/types still produce distinct rows.

        Race-safe insert: each new signal is INSERTed inside its own SAVEPOINT
        (``db.session.begin_nested``) and flushed immediately. The
        ``_signal_already_exists`` pre-check is a fast path, but two extraction
        workers can both pass it concurrently; the database unique index
        ``uq_hubspot_signals_dedup`` then makes the losing INSERT raise
        ``IntegrityError``. That error is caught and the signal is skipped, so
        a concurrent duplicate can never poison the surrounding transaction or
        create a second row. Signals that fail this way are not returned.

        The returned records are already added to the session and flushed; the
        caller is still responsible for committing (re-adding them is a no-op).

        Args:
            engagement: A HubSpotEngagement model instance.
            lead_id:    The internal Lead.id to associate signals with.

        Returns:
            List of HubSpotSignal instances that were successfully inserted
            (added to the session and flushed) and are awaiting commit.
        """
        body_text = self._get_body_text(engagement)
        body_lower = body_text.lower()

        source_engagement_id = str(engagement.hubspot_id) if engagement.hubspot_id else None
        signals = []

        def _persist(signal) -> bool:
            """Insert one signal inside a SAVEPOINT; return True if it stuck.

            The ``_signal_already_exists`` pre-check above already skips known
            duplicates. This is the race backstop: if a concurrent worker
            inserted the same dedup key between that check and this flush, the
            ``uq_hubspot_signals_dedup`` unique index raises ``IntegrityError``
            on flush. We roll back ONLY this signal's savepoint and skip it,
            leaving the surrounding transaction usable so the remaining signals
            still persist.
            """
            try:
                with db.session.begin_nested():
                    db.session.add(signal)
                    db.session.flush()
                return True
            except IntegrityError:
                logger.debug(
                    "Signal %s for lead_id=%d source=%s already created by a "
                    "concurrent worker (unique index) — skipping (race).",
                    signal.signal_type, lead_id, source_engagement_id,
                )
                return False

        for signal_type, keywords in self._dictionary.items():
            # FOLLOW_UP_OVERDUE is handled separately — skip keyword matching
            if signal_type == 'FOLLOW_UP_OVERDUE':
                continue

            matched_keyword = self._find_keyword(body_lower, keywords)
            if matched_keyword:
                # Idempotent dedup: skip if an equivalent signal already exists
                # for this dedup key so re-extraction across sync runs does not
                # accumulate duplicate rows (see _signal_already_exists).
                if self._signal_already_exists(lead_id, signal_type, source_engagement_id):
                    logger.debug(
                        "Signal %s already exists for lead_id=%d source=%s — skipping (idempotent).",
                        signal_type, lead_id, source_engagement_id,
                    )
                    continue
                signal = HubSpotSignal(
                    lead_id=lead_id,
                    signal_type=signal_type,
                    source_engagement_id=source_engagement_id,
                    raw_evidence=matched_keyword,
                )
                if _persist(signal):
                    signals.append(signal)
                    logger.debug(
                        "Signal %s extracted for lead_id=%d (keyword=%r).",
                        signal_type, lead_id, matched_keyword,
                    )

        # FOLLOW_UP_OVERDUE: check for an open overdue task on this lead
        if self._has_overdue_task(lead_id) and not self._signal_already_exists(
            lead_id, 'FOLLOW_UP_OVERDUE', source_engagement_id
        ):
            signal = HubSpotSignal(
                lead_id=lead_id,
                signal_type='FOLLOW_UP_OVERDUE',
                source_engagement_id=source_engagement_id,
                raw_evidence='open overdue task detected',
            )
            if _persist(signal):
                signals.append(signal)
                logger.debug(
                    "Signal FOLLOW_UP_OVERDUE extracted for lead_id=%d (overdue task).",
                    lead_id,
                )

        return signals

    # ------------------------------------------------------------------
    # Idempotent persistence dedup
    # ------------------------------------------------------------------

    @staticmethod
    def _signal_already_exists(lead_id: int, signal_type: str,
                               source_engagement_id: Optional[str]) -> bool:
        """Return True if a HubSpotSignal already exists for this dedup key.

        Dedup key: ``(lead_id, signal_type, source_engagement_id)``.

        HubSpot signals represent boolean STATES, not counters. Re-extracting
        the SAME ``signal_type`` from the SAME source engagement for the SAME
        lead across multiple sync runs must NOT create duplicate rows (the bug
        that let a single re-extracted PRIOR_WARM_CONVERSATION stack +15 several
        times). Distinct sources (different ``source_engagement_id``) and
        distinct types still create distinct rows — only re-extraction of the
        exact same signal is skipped.

        ``source_engagement_id`` is the model's source column. When it is None
        (no source engagement) the key naturally degrades to
        ``(lead_id, signal_type)``, i.e. one sourceless row per type per lead.

        Special case — ``FOLLOW_UP_OVERDUE`` is a LEAD-LEVEL state, not tied to
        any single engagement. It is deduped on ``(lead_id, signal_type)`` only
        (ignoring ``source_engagement_id``) so it is not duplicated once per
        engagement processed for the same lead. All other signal types keep the
        full ``(lead_id, signal_type, source_engagement_id)`` key.
        """
        if signal_type == 'FOLLOW_UP_OVERDUE':
            return (
                HubSpotSignal.query
                .filter_by(lead_id=lead_id, signal_type=signal_type)
                .first()
            ) is not None
        return (
            HubSpotSignal.query
            .filter_by(
                lead_id=lead_id,
                signal_type=signal_type,
                source_engagement_id=source_engagement_id,
            )
            .first()
        ) is not None

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

    @classmethod
    def text_has_motivation_signal(cls, text: str) -> bool:
        """Return True when *text* matches any non-overdue signal keyword."""
        if not text or not str(text).strip():
            return False
        service = cls()
        body_lower = str(text).lower()
        for signal_type, keywords in service._dictionary.items():
            if signal_type == 'FOLLOW_UP_OVERDUE':
                continue
            if cls._find_keyword(body_lower, keywords):
                return True
        return False

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
