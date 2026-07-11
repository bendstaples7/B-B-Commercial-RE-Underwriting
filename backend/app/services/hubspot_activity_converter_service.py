"""HubSpotActivityConverterService — converts raw HubSpot engagements to internal records."""
import html as html_lib
import logging
import re
from datetime import datetime, timezone

from app import db
from app.models.interaction import Interaction
from app.models.interaction_association import InteractionAssociation
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.models.hubspot_match import HubSpotMatch

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html_tags(raw_html):
    """Strip HTML tags from a string and return collapsed plain text.

    Block-level closers and <br> are turned into spaces so adjacent words don't
    run together, remaining tags are removed, HTML entities are unescaped, and
    runs of whitespace are collapsed. Returns '' for falsy input.
    """
    if not raw_html:
        return ''
    text = re.sub(r'(?i)<\s*br\s*/?>', ' ', raw_html)
    text = re.sub(r'(?i)</\s*(p|div|li|tr|h[1-6])\s*>', ' ', text)
    text = _HTML_TAG_RE.sub('', text)
    text = html_lib.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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
        Body is sourced from metadata.text (plaintext), falling back to
        metadata.html with tags stripped — HubSpot EMAIL engagements do not use
        metadata.body. occurred_at is sourced from engagement.createdAt (milliseconds).
        """
        if self._interaction_exists(engagement.hubspot_id):
            logger.debug(
                "Interaction for hubspot_engagement_id=%s already exists — skipping.",
                engagement.hubspot_id,
            )
            return None

        metadata = engagement.raw_payload.get('metadata', {})
        body = self._extract_email_body(metadata)
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

        Idempotent on create: if hubspot_task_id already exists, reconciles status
        from the latest engagement payload instead of creating a duplicate.
        Status mapping: 'COMPLETED' → 'completed', all others → 'open'.
        """
        if self._task_exists(engagement.hubspot_id):
            updated = self.reconcile_task_from_engagement(engagement)
            if updated:
                return Task.query.filter_by(
                    hubspot_task_id=str(engagement.hubspot_id)
                ).first()
            logger.debug(
                "Task for hubspot_task_id=%s already exists — reconcile unchanged.",
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

        self._upsert_lead_tasks_for_task(task, associations)
        db.session.commit()
        logger.info(
            "Created Task(id=%s) from HubSpot engagement %s (status=%s).",
            task.id,
            engagement.hubspot_id,
            status,
        )
        return task

    def reconcile_task_from_engagement(self, engagement) -> bool:
        """Update an existing imported Task from the latest HubSpot engagement payload.

        Returns True when task.status (or completion_timestamp) changed.
        """
        task = Task.query.filter_by(hubspot_task_id=str(engagement.hubspot_id)).first()
        if task is None:
            return False

        new_status = self._map_hubspot_task_status(engagement)
        old_status = task.status
        # Legacy engagement payloads can lag behind HubSpot; never downgrade a
        # locally completed task back to open based on stale engagement data.
        if old_status == 'completed' and new_status != 'completed':
            logger.warning(
                "Skipping stale engagement reconcile for Task(id=%s) hubspot_task_id=%s: "
                "would downgrade completed → %s",
                task.id,
                engagement.hubspot_id,
                new_status,
            )
            return False
        changed = old_status != new_status

        task.raw_payload = engagement.raw_payload
        task.status = new_status
        if new_status == 'completed':
            if task.completion_timestamp is None:
                task.completion_timestamp = datetime.utcnow()
                changed = True
        elif task.completion_timestamp is not None:
            task.completion_timestamp = None
            changed = True

        self._upsert_lead_tasks_for_task(task)
        db.session.commit()

        if changed:
            logger.info(
                "Reconciled Task(id=%s) hubspot_task_id=%s status %s → %s",
                task.id,
                engagement.hubspot_id,
                old_status,
                new_status,
            )
            self._recompute_action_for_task(task)

        return changed

    def sync_task_from_crm_v3(self, record: dict, *, lead_id: int) -> str:
        """Sync a live HubSpot CRM v3 task onto a local Task row.

        Returns 'created', 'updated', or 'unchanged'.
        """
        hs_id = str(record.get('id', ''))
        if not hs_id:
            return 'unchanged'

        props = record.get('properties') or {}
        new_status = self._map_crm_v3_task_status(props)
        title = props.get('hs_task_subject') or '(No Subject)'
        body = props.get('hs_task_body') or None
        due_date = self._parse_hubspot_due_date(props.get('hs_timestamp'))
        raw_payload = {'properties': props, 'id': hs_id}

        from app.models.task_association import TaskAssociation

        task = Task.query.filter_by(hubspot_task_id=hs_id).first()
        if task is None:
            task = Task(
                title=title,
                body=body,
                due_date=due_date,
                status=new_status,
                source='hubspot_import',
                hubspot_task_id=hs_id,
                raw_payload=raw_payload,
            )
            db.session.add(task)
            db.session.flush()
            db.session.add(TaskAssociation(
                task_id=task.id,
                target_type='lead',
                target_id=lead_id,
            ))
            if new_status == 'completed':
                task.completion_timestamp = datetime.utcnow()
            self._upsert_lead_tasks_for_task(
                task,
                [{'target_type': 'lead', 'target_id': lead_id}],
            )
            db.session.commit()
            logger.info(
                'Created Task(id=%s) from live HubSpot CRM task %s (status=%s).',
                task.id, hs_id, new_status,
            )
            return 'created'

        old_status = task.status

        association_added = False
        if TaskAssociation.query.filter_by(
            task_id=task.id,
            target_type='lead',
            target_id=lead_id,
        ).first() is None:
            db.session.add(TaskAssociation(
                task_id=task.id,
                target_type='lead',
                target_id=lead_id,
            ))
            association_added = True

        changed = (
            association_added
            or task.status != new_status
            or task.title != title
            or task.body != body
            or task.due_date != due_date
        )
        task.title = title
        task.body = body
        task.due_date = due_date
        task.raw_payload = raw_payload
        task.status = new_status
        if new_status == 'completed':
            if task.completion_timestamp is None:
                task.completion_timestamp = datetime.utcnow()
                changed = True
        elif task.completion_timestamp is not None:
            task.completion_timestamp = None
            changed = True

        self._upsert_lead_tasks_for_task(
            task,
            [{'target_type': 'lead', 'target_id': lead_id}],
        )

        if not changed:
            db.session.commit()
            return 'unchanged'

        db.session.commit()
        logger.info(
            'Synced Task(id=%s) hubspot_task_id=%s status %s → %s',
            task.id, hs_id, old_status, new_status,
        )
        self._recompute_action_for_task(task)
        return 'updated'

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _upsert_lead_tasks_for_task(self, task: Task, associations: list | None = None) -> None:
        """Mirror lead-linked HubSpot Task rows into canonical LeadTask.

        Prefer LeadTask for Command Center Open Tasks; keep ``tasks`` for CRM
        association/queue consumers until those paths are migrated.
        """
        if not task.hubspot_task_id:
            return

        from app.services.lead_task_service import LeadTaskService

        lead_ids: set[int] = set()
        if associations:
            for assoc in associations:
                if assoc.get('target_type') == 'lead' and assoc.get('target_id') is not None:
                    lead_ids.add(int(assoc['target_id']))
        else:
            for row in TaskAssociation.query.filter_by(
                task_id=task.id,
                target_type='lead',
            ).all():
                lead_ids.add(int(row.target_id))
            if task.lead_id is not None:
                lead_ids.add(int(task.lead_id))

        if not lead_ids:
            return

        svc = LeadTaskService()
        for lead_id in lead_ids:
            try:
                svc.upsert_from_hubspot(
                    lead_id=lead_id,
                    hubspot_task_id=str(task.hubspot_task_id),
                    title=task.title or '(No Subject)',
                    status=task.status or 'open',
                    due_date=task.due_date,
                    commit=False,
                )
            except Exception as exc:
                logger.warning(
                    'LeadTask upsert failed for hubspot_task_id=%s lead_id=%s: %s',
                    task.hubspot_task_id,
                    lead_id,
                    exc,
                )

    @staticmethod
    def _map_crm_v3_task_status(props: dict) -> str:
        hs_status = (props.get('hs_task_status') or '').upper()
        return 'completed' if hs_status == 'COMPLETED' else 'open'

    @staticmethod
    def _map_hubspot_task_status(engagement) -> str:
        """Map HubSpot task status fields to internal task status."""
        metadata = engagement.raw_payload.get('metadata', {}) or {}
        hs_status = (metadata.get('status') or '').upper()
        if not hs_status:
            props = engagement.raw_payload.get('properties', {}) or {}
            hs_status = (props.get('hs_task_status') or '').upper()
        return 'completed' if hs_status == 'COMPLETED' else 'open'

    def _recompute_action_for_task(self, task) -> None:
        """Recompute recommended_action for leads linked to this task."""
        from app.models.task_association import TaskAssociation
        from app.services.action_engine_service import ActionEngineService

        lead_ids = [
            row.target_id
            for row in TaskAssociation.query.filter_by(
                task_id=task.id,
                target_type='lead',
            ).all()
        ]
        for lead_id in lead_ids:
            try:
                ActionEngineService.recompute_and_persist(lead_id)
            except Exception as exc:
                db.session.rollback()
                logger.warning(
                    "recompute_and_persist failed for lead_id=%s after task reconcile: %s",
                    lead_id,
                    exc,
                )

    # ------------------------------------------------------------------ #
    # Private helpers (continued)                                          #
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
    def _extract_email_body(metadata):
        """Extract body text from an EMAIL engagement's metadata.

        HubSpot EMAIL engagements store content in metadata.text (plaintext) and
        metadata.html — NOT metadata.body (which NOTE/CALL use). Order of
        preference: plaintext 'text'; then 'html' with tags stripped to plain
        text; then 'bodyPreview' (older/partial payloads expose only this);
        final fallback to ''.
        """
        metadata = metadata or {}
        text = metadata.get('text')
        if text:
            return text
        html = metadata.get('html')
        if html:
            return _strip_html_tags(html)
        preview = metadata.get('bodyPreview')
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
    def _parse_hubspot_due_date(value):
        """Parse HubSpot task due date from ms epoch or ISO-8601 string."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return HubSpotActivityConverterService._parse_ms_timestamp(value)
        text = str(value).strip()
        if text.isdigit():
            return HubSpotActivityConverterService._parse_ms_timestamp(text)
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except (ValueError, TypeError, OSError):
            logger.warning('Could not parse HubSpot due date value: %r', value)
            return None

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
