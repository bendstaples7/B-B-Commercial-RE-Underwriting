"""TimelineService — unified timeline of Interactions and Tasks for a given target."""
from app import db
from app.models.interaction import Interaction
from app.models.interaction_association import InteractionAssociation
from app.models.task import Task
from app.models.task_association import TaskAssociation


class TimelineService:
    """
    Builds a unified, reverse-chronological timeline of Interactions and Tasks
    for any target (lead, organization, contact).

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
    """

    def get_timeline(
        self,
        target_type: str,
        target_id: int,
        entry_type: str = None,
        subtype: str = None,
        date_from=None,
        date_to=None,
    ) -> list:
        """
        Return a unified, reverse-chronological list of timeline entry dicts.

        Parameters
        ----------
        target_type : str
            One of 'lead', 'organization', 'contact'.
        target_id : int
            Primary key of the target record.
        entry_type : str, optional
            Filter to 'interaction' or 'task'.
        subtype : str, optional
            For interactions: interaction_type value (note/call/email/meeting/other).
            For tasks: task status value (open/completed/cancelled/overdue).
        date_from : datetime, optional
            Inclusive lower bound on the entry date.
        date_to : datetime, optional
            Inclusive upper bound on the entry date.

        Returns
        -------
        list of dict
            Each dict has keys: entry_type, subtype, date, body_or_title,
            source, hubspot_engagement_id.
            Sorted descending by date; entries with None dates appear last.
        """
        entries = []

        # ------------------------------------------------------------------ #
        # 1. Interactions                                                      #
        # ------------------------------------------------------------------ #
        if entry_type is None or entry_type == 'interaction':
            interactions = (
                db.session.query(Interaction)
                .join(
                    InteractionAssociation,
                    InteractionAssociation.interaction_id == Interaction.id,
                )
                .filter(
                    InteractionAssociation.target_type == target_type,
                    InteractionAssociation.target_id == target_id,
                )
            )

            if subtype is not None:
                interactions = interactions.filter(
                    Interaction.interaction_type == subtype
                )
            if date_from is not None:
                interactions = interactions.filter(
                    Interaction.occurred_at >= date_from
                )
            if date_to is not None:
                interactions = interactions.filter(
                    Interaction.occurred_at <= date_to
                )

            for interaction in interactions.all():
                entries.append({
                    'entry_type': 'interaction',
                    'subtype': interaction.interaction_type,
                    'date': interaction.occurred_at,
                    'body_or_title': interaction.body,
                    'source': interaction.source,
                    'hubspot_engagement_id': interaction.hubspot_engagement_id,
                })

        # ------------------------------------------------------------------ #
        # 2. Tasks                                                             #
        # ------------------------------------------------------------------ #
        if entry_type is None or entry_type == 'task':
            tasks = (
                db.session.query(Task)
                .join(
                    TaskAssociation,
                    TaskAssociation.task_id == Task.id,
                )
                .filter(
                    TaskAssociation.target_type == target_type,
                    TaskAssociation.target_id == target_id,
                )
            )

            if subtype is not None:
                tasks = tasks.filter(Task.status == subtype)

            for task in tasks.all():
                # Use due_date if present, otherwise fall back to created_at
                task_date = task.due_date if task.due_date is not None else task.created_at

                if date_from is not None and task_date is not None and task_date < date_from:
                    continue
                if date_to is not None and task_date is not None and task_date > date_to:
                    continue

                entries.append({
                    'entry_type': 'task',
                    'subtype': task.status,
                    'date': task_date,
                    'body_or_title': task.title,
                    'source': task.source,
                    'hubspot_engagement_id': None,
                })

        # ------------------------------------------------------------------ #
        # 3. Sort descending by date; None dates go last                      #
        # ------------------------------------------------------------------ #
        # Key: (has_date_flag, date_value)
        #   has_date_flag = 1 when date is present, 0 when None
        #   Sorting descending puts has_date_flag=1 before has_date_flag=0,
        #   and among dated entries the most recent date comes first.
        entries.sort(
            key=lambda e: (
                1 if e['date'] is not None else 0,
                e['date'] if e['date'] is not None else None,
            ),
            reverse=True,
        )

        return entries
