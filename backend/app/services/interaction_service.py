"""InteractionService — business logic for Interaction CRUD and timeline delegation.

Implements all operations required by Requirements 2.1–2.4, 2.6:
  - create  — validate body + at least one association target, persist records
  - update  — update body / occurred_at / interaction_type
  - delete  — hard-delete with cascade via SQLAlchemy relationship
  - get     — fetch single Interaction with its associations
  - list    — paginated, filterable by target_type / target_id
  - get_timeline — delegate to TimelineService
"""
import logging
import unicodedata
from datetime import datetime
from typing import Optional

from app import db
from app.models.interaction import Interaction
from app.models.interaction_association import InteractionAssociation
from app.exceptions import InteractionValidationError, ResourceNotFoundError
from app.services.timeline_service import TimelineService

logger = logging.getLogger(__name__)


def _strip_invisible(value: str) -> str:
    """Strip all Unicode whitespace and control characters from *value*.

    Stricter than ``str.strip()`` — handles Unicode Zs (space separators) and
    Cc (control characters) so inputs like '\\x7f' are treated as empty.
    """
    cleaned = ''.join(
        ch for ch in value
        if not (unicodedata.category(ch).startswith('C') or unicodedata.category(ch) == 'Zs')
    )
    return cleaned.strip()


class InteractionService:
    """Service class for all Interaction-related operations.

    All database writes use ``db.session`` and commit at the end of each
    operation.  Callers are responsible for providing a valid application
    context (i.e. running inside a Flask request or app-context block).
    """

    def __init__(self):
        self._timeline_service = TimelineService()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, data: dict) -> Interaction:
        """Create a new Interaction and its association records.

        Parameters
        ----------
        data : dict
            Must contain:
            - ``body`` (str, non-empty)
            - ``interaction_type`` (str)
            - ``occurred_at`` (datetime or ISO string)
            - ``associations`` (list of dicts with ``target_type`` and ``target_id``)
            Optional:
            - ``source`` (str, default 'manual')
            - ``hubspot_engagement_id`` (str)
            - ``raw_payload`` (dict)
            - ``is_orphaned`` (bool)

        Returns
        -------
        Interaction
            The newly created and persisted Interaction.

        Raises
        ------
        InteractionValidationError
            If ``body`` is empty or ``associations`` contains no valid targets.
        """
        # Validate body
        body = _strip_invisible(data.get('body') or '')
        if not body:
            raise InteractionValidationError(
                "Interaction body must not be empty.",
                field='body',
                value=data.get('body'),
            )

        # Validate associations
        associations = data.get('associations') or []
        valid_associations = [
            a for a in associations
            if a.get('target_type') and a.get('target_id') is not None
        ]
        if not valid_associations:
            raise InteractionValidationError(
                "At least one association target (target_type + target_id) is required.",
                field='associations',
                value=None,
            )

        # Parse occurred_at if it's a string
        occurred_at = data.get('occurred_at')
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        if occurred_at is None:
            occurred_at = datetime.utcnow()

        interaction = Interaction(
            interaction_type=data.get('interaction_type', 'note'),
            body=body,
            occurred_at=occurred_at,
            source=data.get('source', 'manual'),
            hubspot_engagement_id=data.get('hubspot_engagement_id'),
            raw_payload=data.get('raw_payload'),
            is_orphaned=data.get('is_orphaned', False),
        )
        db.session.add(interaction)
        db.session.flush()  # populate interaction.id before creating associations

        for assoc_data in valid_associations:
            assoc = InteractionAssociation(
                interaction_id=interaction.id,
                target_type=assoc_data['target_type'],
                target_id=assoc_data['target_id'],
            )
            db.session.add(assoc)

        db.session.commit()
        logger.info(
            "Created Interaction id=%d type=%r with %d association(s)",
            interaction.id, interaction.interaction_type, len(valid_associations),
        )
        return interaction

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, interaction_id: int, data: dict) -> Interaction:
        """Update an existing Interaction's body, occurred_at, or interaction_type.

        Only fields present in *data* are updated.

        Parameters
        ----------
        interaction_id : int
        data : dict
            Partial or full set of updatable fields:
            ``body``, ``occurred_at``, ``interaction_type``.

        Returns
        -------
        Interaction
            The updated Interaction.

        Raises
        ------
        ResourceNotFoundError
            If no Interaction with *interaction_id* exists.
        InteractionValidationError
            If ``body`` is explicitly provided but is empty.
        """
        interaction = self._get_or_raise(interaction_id)

        if 'body' in data:
            body = _strip_invisible(data['body'] or '')
            if not body:
                raise InteractionValidationError(
                    "Interaction body must not be empty.",
                    field='body',
                    value=data['body'],
                )
            interaction.body = body

        if 'occurred_at' in data:
            occurred_at = data['occurred_at']
            if isinstance(occurred_at, str):
                occurred_at = datetime.fromisoformat(occurred_at)
            interaction.occurred_at = occurred_at

        if 'interaction_type' in data:
            interaction.interaction_type = data['interaction_type']

        interaction.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info("Updated Interaction id=%d", interaction.id)
        return interaction

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, interaction_id: int) -> None:
        """Hard-delete an Interaction and its associations (cascade).

        Parameters
        ----------
        interaction_id : int

        Raises
        ------
        ResourceNotFoundError
            If no Interaction with *interaction_id* exists.
        """
        interaction = self._get_or_raise(interaction_id)
        db.session.delete(interaction)
        db.session.commit()
        logger.info("Deleted Interaction id=%d", interaction_id)

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------

    def get(self, interaction_id: int) -> Interaction:
        """Fetch a single Interaction with its associations eagerly loaded.

        Parameters
        ----------
        interaction_id : int

        Returns
        -------
        Interaction

        Raises
        ------
        ResourceNotFoundError
            If no Interaction with *interaction_id* exists.
        """
        interaction = self._get_or_raise(interaction_id)
        # Trigger loading of associations (lazy='dynamic' — call .all() to materialise)
        _ = interaction.associations.all()
        return interaction

    # ------------------------------------------------------------------
    # List (paginated + filtered)
    # ------------------------------------------------------------------

    def list(
        self,
        filters: Optional[dict] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple:
        """Return a paginated list of Interactions with optional filters.

        Supported filter keys:
        - ``target_type`` (str): filter by association target_type
        - ``target_id`` (int): filter by association target_id (requires target_type)
        - ``interaction_type`` (str): exact match on interaction_type
        - ``source`` (str): exact match on source

        Parameters
        ----------
        filters : dict or None
        page : int
            1-based page number.
        per_page : int
            Number of records per page.

        Returns
        -------
        tuple[list[Interaction], int]
            A 2-tuple of (records for this page, total matching count).
        """
        filters = filters or {}
        query = db.session.query(Interaction)

        # Join on InteractionAssociation when filtering by target
        if filters.get('target_type') or filters.get('target_id') is not None:
            query = query.join(
                InteractionAssociation,
                InteractionAssociation.interaction_id == Interaction.id,
            )
            if filters.get('target_type'):
                query = query.filter(
                    InteractionAssociation.target_type == filters['target_type']
                )
            if filters.get('target_id') is not None:
                query = query.filter(
                    InteractionAssociation.target_id == filters['target_id']
                )
            # Avoid duplicates when an interaction has multiple associations
            query = query.distinct()

        if filters.get('interaction_type'):
            query = query.filter(
                Interaction.interaction_type == filters['interaction_type']
            )
        if filters.get('source'):
            query = query.filter(Interaction.source == filters['source'])

        query = query.order_by(Interaction.occurred_at.desc())

        total = query.count()
        records = query.offset((page - 1) * per_page).limit(per_page).all()

        return records, total

    # ------------------------------------------------------------------
    # Timeline delegation
    # ------------------------------------------------------------------

    def get_timeline(
        self,
        target_type: str,
        target_id: int,
        filters: Optional[dict] = None,
    ) -> list:
        """Return a unified timeline for a target by delegating to TimelineService.

        Parameters
        ----------
        target_type : str
            One of 'lead', 'organization', 'contact'.
        target_id : int
            Primary key of the target record.
        filters : dict or None
            Optional filter keys forwarded to TimelineService:
            ``entry_type``, ``subtype``, ``date_from``, ``date_to``.

        Returns
        -------
        list of dict
            Unified, reverse-chronological timeline entries.
        """
        filters = filters or {}
        return self._timeline_service.get_timeline(
            target_type=target_type,
            target_id=target_id,
            entry_type=filters.get('entry_type'),
            subtype=filters.get('subtype'),
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, interaction_id: int) -> Interaction:
        """Fetch an Interaction by id or raise ResourceNotFoundError."""
        interaction = Interaction.query.get(interaction_id)
        if interaction is None:
            raise ResourceNotFoundError(
                f"Interaction id={interaction_id} not found.",
                payload={'interaction_id': interaction_id},
            )
        return interaction
