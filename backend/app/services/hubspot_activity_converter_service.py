"""HubSpotActivityConverterService — converts raw HubSpot engagements to internal records."""
import logging
from datetime import datetime, timezone

from app import db
from app.models.interaction import Interaction
from app.models.interaction_association import InteractionAssociation
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.models.hubspot_match import HubSpotMatch

logger = logging.getLogger(__name__)


class HubSpotActivityConverterService:
    """
    Converts raw HubSpotEngagement records into internal Interaction and Task records.

    Idempotent: re-running conversion for an already-converted engagement is a no-op.
    Orphaned: if no confirmed HubSpotMatch associations are found, the record is created
    with is_orphaned=True (for Interactions) or without associations (for Tasks).
    """

    # HubSpot stores timestamps as milliseconds since epoch
    _MS_PER_SECOND = 1000

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def convert_engagement(self, engagement):
        """
        Route to the appropriate converter based on engagement_type.

        Returns the created Interaction or Task, or None for unrecognized types.
        """
        etype = (engagement.engagement_type or '').upper()
        if etype == 'NOTE':
            return self.convert_note(engagement)
        elif etype == 'CALL':
            return self.convert_call(engagement)
        elif etype == 'TASK':
            return self.convert_task(engagement)
        elif etype == 'EMAIL':
            return self.convert_email(engagement)
        else:
            logger.warning(
                "Unrecognized HubSpot engagement type '%s' for hubspot_id=%s — skipping.",
                engagement.engagement_type,
                engagement.hubspot_id,
            )
            return None

    def convert_note(self, engagement):
        """
        Convert a HubSpot NOTE engagement to an internal Interaction(type='note').

        Idempotent: returns None if hubspot_engagement_id already exists.
        Body is sourced from metadata.body, falling back to engagement.bodyPreview.
        occurred_at is sourced from engagement.createdAt (milliseconds).
        """
        if self._interaction_exists(engagement.hubspot_id):
            logger.debug(
                "Interaction for hubspot_engagement_id=%s already exists — skipping.",
                engagement.hubspot_id,
            )
            return None

        body = self._extract_note_body(engagement.raw_payload)
        occurred_at = self._parse_ms_timestamp(
            engagement.raw_payload.get('engagement', {}).get('createdAt')
        )

        associations = self._resolve_associations(engagement)
        is_orphaned = len(associations) == 0

        interaction = Interaction(
            interaction_type='note',
            body=body,
            occurred_at=occurred_at,
            source='hubspot_import',
            hubspot_engagement_id=engagement.hubspot_id,
            raw_payload=engagement.raw_payload,
            is_orphaned=is_orphaned,
        )
        db.session.add(interaction)
        db.session.flush()  # populate interaction.id before creating associations

        for assoc in associations:
            db.session.add(InteractionAssociation(
                interaction_id=interaction.id,
                target_type=assoc['target_type'],
                target_id=assoc['target_id'],
            ))

        db.session.commit()
        logger.info(
            "Created Interaction(id=%s, type=note) from HubSpot engagement %s (orphaned=%s).",
            interaction.id,
            engagement.hubspot_id,
            is_orphaned,
        )

        # Option 3: extract signals inline immediately after creating the interaction
        self._extract_signals_for_interaction(interaction, associations)

        return interaction

    def convert_call(self, engagement):
        """
        Convert a HubSpot CALL engagement to an internal Interaction(type='call').

        Idempotent: returns None if hubspot_engagement_id already exists.
        Body is sourced from metadata.body, falling back to metadata.disposition.
        occurred_at is sourced from engagement.createdAt (milliseconds).
        """
        if self._interaction_exists(engagement.hubspot_id):
            logger.debug(
                "Interaction for hubspot_engagement_id=%s already exists — skipping.",
                engagement.hubspot_id,
            )
            return None

        body = self._extract_call_body(engagement.raw_payload)
        occurred_at = self._parse_ms_timestamp(
            engagement.raw_payload.get('engagement', {}).get('createdAt')
        )

        associations = self._resolve_associations(engagement)
        is_orphaned = len(associations) == 0

        interaction = Interaction(
            interaction_type='call',
            body=body,
            occurred_at=occurred_at,
            source='hubspot_import',
            hubspot_engagement_id=engagement.hubspot_id,
            raw_payload=engagement.raw_payload,
            is_orphaned=is_orphaned,
        )
        db.session.add(interaction)
        db.session.flush()

        for assoc in associations:
            db.session.add(InteractionAssociation(
                interaction_id=interaction.id,
                target_type=assoc['target_type'],
                target_id=assoc['target_id'],
            ))

        db.session.commit()
        logger.info(
            "Created Interaction(id=%s, type=call) from HubSpot engagement %s (orphaned=%s).",
            interaction.id,
            engagement.hubspot_id,
            is_orphaned,
        )

        # Option 3: extract signals inline immediately after creating the interaction
        self._extract_signals_for_interaction(interaction, associations)

        return interaction

    def convert_email(self, engagement):
        """
        Convert a HubSpot EMAIL engagement to an internal Interaction(type='email').

        Idempotent: returns None if hubspot_engagement_id already exists.
        Body is sourced from metadata.body, falling back to engagement.bodyPreview.
        occurred_at is sourced from engagement.createdAt (milliseconds).
        """
        if self._interaction_exists(engagement.hubspot_id):
            logger.debug(
                "Interaction for hubspot_engagement_id=%s already exists — skipping.",
                engagement.hubspot_id,
            )
            return None

        body = self._extract_note_body(engagement.raw_payload)  # same extraction as NOTE
        occurred_at = self._parse_ms_timestamp(
            engagement.raw_payload.get('engagement', {}).get('createdAt')
        )

        associations = self._resolve_associations(engagement)
        is_orphaned = len(associations) == 0

        interaction = Interaction(
            interaction_type='email',
            body=body,
            occurred_at=occurred_at,
            source='hubspot_import',
            hubspot_engagement_id=engagement.hubspot_id,
            raw_payload=engagement.raw_payload,
            is_orphaned=is_orphaned,
        )
        db.session.add(interaction)
        db.session.flush()

        for assoc in associations:
            db.session.add(InteractionAssociation(
                interaction_id=interaction.id,
                target_type=assoc['target_type'],
                target_id=assoc['target_id'],
            ))

        db.session.commit()
        logger.info(
            "Created Interaction(id=%s, type=email) from HubSpot engagement %s (orphaned=%s).",
            interaction.id,
            engagement.hubspot_id,
            is_orphaned,
        )
        self._extract_signals_for_interaction(interaction, associations)
        return interaction

    def convert_task(self, engagement):
        """
        Convert a HubSpot TASK engagement to an internal Task.

        Idempotent: returns None if hubspot_task_id already exists.
        Status mapping: 'COMPLETED' → 'completed', all others → 'open'.
        Title from metadata.subject, body from metadata.body,
        due_date from engagement.timestamp (the task's scheduled date).
        Note: metadata.taskDate is not populated by HubSpot's legacy API;
        the canonical due date is stored in engagement.timestamp.
        """
        if self._task_exists(engagement.hubspot_id):
            logger.debug(
                "Task for hubspot_task_id=%s already exists — skipping.",
                engagement.hubspot_id,
            )
            return None

        metadata = engagement.raw_payload.get('metadata', {})
        engagement_obj = engagement.raw_payload.get('engagement', {})
        title = metadata.get('subject') or '(No Subject)'
        body = metadata.get('body') or None
        # Due date lives in engagement.timestamp (milliseconds), not metadata.taskDate.
        # Only parse when a value is actually present; leave NULL when both are absent
        # so tasks with no due date don't get stamped with the import time.
        _ts_value = engagement_obj.get('timestamp') or metadata.get('taskDate')
        due_date = self._parse_ms_timestamp(_ts_value) if _ts_value is not None else None
        hs_status = (metadata.get('status') or '').upper()
        status = 'completed' if hs_status == 'COMPLETED' else 'open'

        associations = self._resolve_associations(engagement)

        task = Task(
            title=title,
            body=body,
            due_date=due_date,
            status=status,
            source='hubspot_import',
            hubspot_task_id=engagement.hubspot_id,
            raw_payload=engagement.raw_payload,
        )
        db.session.add(task)
        db.session.flush()

        for assoc in associations:
            # TaskAssociation only supports 'lead' and 'organization' target types
            if assoc['target_type'] in ('lead', 'organization'):
                db.session.add(TaskAssociation(
                    task_id=task.id,
                    target_type=assoc['target_type'],
                    target_id=assoc['target_id'],
                ))

        db.session.commit()
        logger.info(
            "Created Task(id=%s) from HubSpot engagement %s (status=%s).",
            task.id,
            engagement.hubspot_id,
            status,
        )
        return task

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _resolve_associations(self, engagement):
        """
        Look up confirmed HubSpotMatch records for each associated deal/contact/company ID
        from engagement.raw_payload['associations'].

        Returns a list of {target_type, target_id} dicts for all confirmed matches.
        Returns an empty list if no confirmed matches are found.
        """
        associations_payload = engagement.raw_payload.get('associations', {})
        results = []

        # Map HubSpot association key → HubSpot record type used in HubSpotMatch
        type_map = {
            'dealIds': 'deal',
            'contactIds': 'contact',
            'companyIds': 'company',
        }

        for payload_key, record_type in type_map.items():
            ids = associations_payload.get(payload_key) or []
            for hs_id in ids:
                hs_id_str = str(hs_id)
                match = HubSpotMatch.query.filter_by(
                    hubspot_record_type=record_type,
                    hubspot_id=hs_id_str,
                    status='confirmed',
                ).first()
                if match and match.internal_record_id is not None:
                    target_type = match.internal_record_type  # 'lead' or 'organization'
                    results.append({
                        'target_type': target_type,
                        'target_id': match.internal_record_id,
                    })
                else:
                    logger.debug(
                        "No confirmed HubSpotMatch for %s id=%s — skipping association.",
                        record_type,
                        hs_id_str,
                    )

        return results

    def _resolve_associations_by_engagement_id(self, hubspot_engagement_id):
        """Look up the HubSpotEngagement by ID and resolve its associations.

        Used by the orphan re-resolution pass in run_convert_hubspot_activities.
        Returns [] if the engagement no longer exists in the database.
        """
        from app.models.hubspot_engagement import HubSpotEngagement
        engagement = HubSpotEngagement.query.filter_by(
            hubspot_id=str(hubspot_engagement_id)
        ).first()
        if engagement is None:
            return []
        return self._resolve_associations(engagement)

    @staticmethod
    def _extract_note_body(raw_payload):
        """Extract body text from a NOTE engagement payload."""
        metadata = raw_payload.get('metadata', {})
        body = metadata.get('body')
        if body:
            return body
        # Fallback to bodyPreview on the engagement object
        engagement_obj = raw_payload.get('engagement', {})
        preview = engagement_obj.get('bodyPreview')
        if preview:
            return preview
        return ''

    @staticmethod
    def _extract_call_body(raw_payload):
        """Extract body text from a CALL engagement payload."""
        metadata = raw_payload.get('metadata', {})
        body = metadata.get('body')
        if body:
            return body
        # Fallback to disposition (e.g. "CONNECTED", "LEFT_VOICEMAIL")
        disposition = metadata.get('disposition')
        if disposition:
            return disposition
        # Final fallback to bodyPreview
        engagement_obj = raw_payload.get('engagement', {})
        preview = engagement_obj.get('bodyPreview')
        if preview:
            return preview
        return ''

    @staticmethod
    def _parse_ms_timestamp(ms_value):
        """
        Convert a HubSpot millisecond epoch timestamp to a Python datetime (UTC, naive).

        Returns datetime.utcnow() if ms_value is None or invalid.
        """
        if ms_value is None:
            return datetime.utcnow()
        try:
            seconds = int(ms_value) / 1000.0
            return datetime.utcfromtimestamp(seconds)
        except (ValueError, TypeError, OSError):
            logger.warning("Could not parse HubSpot timestamp value: %r", ms_value)
            return datetime.utcnow()

    def _extract_signals_for_interaction(self, interaction, associations):
        """Option 3: Extract signals inline immediately after an Interaction is created.

        Runs the signal extractor against the interaction body for each lead
        association, persisting HubSpotSignal records and applying suppression
        flags in the same request cycle. Errors are logged but never propagate
        — signal extraction failure must never prevent activity conversion.
        """
        lead_ids = [
            a['target_id'] for a in associations
            if a.get('target_type') == 'lead'
        ]
        if not lead_ids:
            return

        try:
            from app.services.hubspot_signal_extractor_service import HubSpotSignalExtractorService

            extractor = HubSpotSignalExtractorService()

            class _Adapter:
                def __init__(self, body, hubspot_id):
                    self.raw_payload = {'metadata': {'body': body or ''}}
                    self.hubspot_id = hubspot_id

            adapter = _Adapter(interaction.body, interaction.hubspot_engagement_id)

            for lead_id in lead_ids:
                signals = extractor.extract_signals(adapter, lead_id)
                for signal in signals:
                    db.session.add(signal)
                if signals:
                    extractor.apply_suppression(signals)

            db.session.commit()
            logger.debug(
                "_extract_signals_for_interaction: interaction_id=%s lead_ids=%s",
                interaction.id, lead_ids,
            )
        except Exception as exc:
            logger.warning(
                "_extract_signals_for_interaction: failed for interaction_id=%s: %s",
                interaction.id, exc,
            )
            db.session.rollback()

    @staticmethod
    def _interaction_exists(hubspot_engagement_id):
        """Return True if an Interaction with this hubspot_engagement_id already exists."""
        return (
            Interaction.query
            .filter_by(hubspot_engagement_id=str(hubspot_engagement_id))
            .first()
        ) is not None

    @staticmethod
    def _task_exists(hubspot_task_id):
        """Return True if a Task with this hubspot_task_id already exists."""
        return (
            Task.query
            .filter_by(hubspot_task_id=str(hubspot_task_id))
            .first()
        ) is not None
