"""QueueService — badge counts and paginated results for all 7 lead queues."""
from datetime import date, timedelta

from sqlalchemy import exists, and_, or_, case, select

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.models.task import Task
from app.models.task_association import TaskAssociation


def _lead_to_queue_row(lead) -> dict:
    """Convert a Lead model instance to a queue row dict."""
    return {
        'id': lead.id,
        'owner_first_name': lead.owner_first_name,
        'owner_last_name': lead.owner_last_name,
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'lead_score': lead.lead_score,
        'lead_status': lead.lead_status,
        'recommended_action': lead.recommended_action,
        'has_property_match': lead.has_property_match,
        'last_contact_date': lead.last_contact_date.isoformat() if lead.last_contact_date else None,
        'last_hubspot_sync_at': lead.last_hubspot_sync_at.isoformat() if lead.last_hubspot_sync_at else None,
        'hubspot_deal_stage': lead.hubspot_deal_stage,
        'follow_up_overdue': lead.follow_up_overdue,
        'review_required': lead.review_required,
        'review_reason': lead.review_reason,
        'review_triggered_at': lead.review_triggered_at.isoformat() if lead.review_triggered_at else None,
        'unanswered_call_count': lead.unanswered_call_count,
        'is_warm': lead.is_warm,
    }


def _hubspot_task_overdue_subquery(cutoff_date):
    """Return an EXISTS subquery: lead has an open/overdue HubSpot task due on or before cutoff_date.

    Joins tasks → task_associations where target_type='lead' and target_id=Lead.id.
    Also checks tasks.lead_id directly for CRM-native tasks.
    Used by Today's Action (cutoff=today) and Follow-Up Overdue (cutoff=yesterday).
    """
    from datetime import datetime as _dt
    # Normalise cutoff to a datetime so the comparison works against Task.due_date (DateTime column)
    if not isinstance(cutoff_date, _dt):
        cutoff_dt = _dt(cutoff_date.year, cutoff_date.month, cutoff_date.day, 23, 59, 59)
    else:
        cutoff_dt = cutoff_date

    # Via task_associations (HubSpot-imported tasks)
    via_assoc = exists().where(
        and_(
            TaskAssociation.target_type == 'lead',
            TaskAssociation.target_id == Lead.id,
            TaskAssociation.task_id == Task.id,
            Task.status.in_(['open', 'overdue']),
            Task.due_date <= cutoff_dt,
        )
    )
    # Via direct lead_id FK (CRM-native tasks mirrored to tasks table)
    via_direct = exists().where(
        and_(
            Task.lead_id == Lead.id,
            Task.status.in_(['open', 'overdue']),
            Task.due_date <= cutoff_dt,
        )
    )
    return or_(via_assoc, via_direct)


class QueueService:
    """Computes badge counts and paginated rows for the 7 Actionable Lead Command Center queues."""

    def __init__(self, owner_user_id: str | None = None):
        """
        Args:
            owner_user_id: When set, all queries are scoped to leads owned by
                           this user.  When None (admin), all leads are included.
        """
        self._owner_user_id = owner_user_id

    def _base_query(self):
        """Return a Lead query scoped to this service's owner, if set.

        Leads with owner_user_id IS NULL are legacy/unowned records that
        are visible to all authenticated users (not just admins).
        """
        q = Lead.query
        if self._owner_user_id:
            q = q.filter(
                or_(Lead.owner_user_id == self._owner_user_id, Lead.owner_user_id.is_(None))
            )
        return q

    # ------------------------------------------------------------------
    # Badge counts
    # ------------------------------------------------------------------

    def get_counts(self) -> dict[str, int]:
        """Return badge counts for all 7 queues as a single dict."""
        today = date.today()
        seven_days_ago = today - timedelta(days=7)

        return {
            "todays_action": self._count_todays_action(today),
            "previously_warm": self._count_previously_warm(),
            "follow_up_overdue": self._count_follow_up_overdue(today, seven_days_ago),
            "no_next_action": self._count_no_next_action(),
            "needs_review": self._count_needs_review(),
            "do_not_contact": self._count_do_not_contact(),
            "missing_property_match": self._count_missing_property_match(),
        }

    # ------------------------------------------------------------------
    # Private count helpers
    # ------------------------------------------------------------------

    def _count_todays_action(self, today: date) -> int:
        """Today's Action: any lead that needs attention today.

        Matches leads where ANY of the following is true:
          - lead_status in (active, follow_up) AND recommended_action = 'follow_up_now'
          - lead_status in (active, follow_up) AND has an open lead_task due today
          - Has an open/overdue HubSpot task (tasks table) due today (any lead_status)
        """
        open_lead_task_due_today = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
                LeadTask.due_date <= today,
            )
        )
        hubspot_task_due_today = _hubspot_task_overdue_subquery(today)

        return (
            self._base_query()
            .filter(
                or_(
                    # CRM-native path: requires active/follow_up status
                    and_(
                        Lead.lead_status.in_(['active', 'follow_up']),
                        or_(
                            Lead.recommended_action == 'follow_up_now',
                            open_lead_task_due_today,
                        ),
                    ),
                    # HubSpot task path: any lead with an overdue HubSpot task
                    hubspot_task_due_today,
                )
            )
            .count()
        )

    def _count_previously_warm(self) -> int:
        """Previously Warm: leads where is_warm = True."""
        return self._base_query().filter(Lead.is_warm.is_(True)).count()

    def _count_follow_up_overdue(self, today: date, seven_days_ago: date) -> int:
        """Follow-Up Overdue: any lead with an overdue follow-up.

        Matches leads where ANY of the following is true:
          - Has an open lead_task with due_date in the past
          - recommended_action = 'follow_up_now' AND last_contact_date > 7 days ago
          - Has an open/overdue HubSpot task with due_date in the past (any lead_status)
        """
        yesterday = today - timedelta(days=1)
        open_lead_task_overdue = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
                LeadTask.due_date < today,
            )
        )
        hubspot_task_overdue = _hubspot_task_overdue_subquery(yesterday)

        return (
            self._base_query()
            .filter(
                or_(
                    open_lead_task_overdue,
                    and_(
                        Lead.recommended_action == 'follow_up_now',
                        Lead.last_contact_date < seven_days_ago,
                    ),
                    hubspot_task_overdue,
                )
            )
            .count()
        )

    def _count_no_next_action(self) -> int:
        """No Next Action: lead_status in (active, new) AND
        recommended_action in (null, 'create_task') AND no open tasks.
        """
        has_open_lead_task = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
            )
        )
        has_open_hubspot_task = exists().where(
            and_(
                TaskAssociation.target_type == 'lead',
                TaskAssociation.target_id == Lead.id,
                TaskAssociation.task_id == Task.id,
                Task.status.in_(['open', 'overdue']),
            )
        )
        has_open_direct_task = exists().where(
            and_(
                Task.lead_id == Lead.id,
                Task.status.in_(['open', 'overdue']),
            )
        )

        return (
            self._base_query()
            .filter(
                Lead.lead_status.in_(['active', 'new']),
                or_(
                    Lead.recommended_action.is_(None),
                    Lead.recommended_action.in_(['create_task', 'ready_for_outreach', 'add_contact_info']),
                ),
                ~has_open_lead_task,
                ~has_open_hubspot_task,
                ~has_open_direct_task,
            )
            .count()
        )

    def _count_needs_review(self) -> int:
        """Needs Review: review_required = true."""
        return self._base_query().filter(Lead.review_required.is_(True)).count()

    def _count_do_not_contact(self) -> int:
        """Do Not Contact: lead_status = 'do_not_contact'."""
        return self._base_query().filter(Lead.lead_status == 'do_not_contact').count()

    def _count_missing_property_match(self) -> int:
        """Missing Property Match: has_property_match = false AND no research task open."""
        has_research_task = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.task_type == 'research_missing_pin',
                LeadTask.status == 'open',
            )
        )
        return (
            self._base_query()
            .filter(
                Lead.has_property_match.is_(False),
                ~has_research_task,
            )
            .count()
        )

    # ------------------------------------------------------------------
    # Paginated queue methods
    # ------------------------------------------------------------------

    def get_todays_action(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """Today's Action — see _count_todays_action for criteria."""
        today = date.today()
        open_lead_task_due_today = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
                LeadTask.due_date <= today,
            )
        )
        hubspot_task_due_today = _hubspot_task_overdue_subquery(today)

        query = self._base_query().filter(
            or_(
                and_(
                    Lead.lead_status.in_(['active', 'follow_up']),
                    or_(
                        Lead.recommended_action == 'follow_up_now',
                        open_lead_task_due_today,
                    ),
                ),
                hubspot_task_due_today,
            )
        )
        total = query.count()
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        query = query.order_by(sort_col.desc() if sort_order == 'desc' else sort_col.asc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_lead_to_queue_row(lead) for lead in leads], total

    def get_previously_warm(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """Previously Warm: leads where is_warm = True."""
        query = self._base_query().filter(Lead.is_warm.is_(True))
        total = query.count()
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        query = query.order_by(sort_col.desc() if sort_order == 'desc' else sort_col.asc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_lead_to_queue_row(lead) for lead in leads], total

    def get_follow_up_overdue(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'last_contact_date',
        sort_order: str = 'asc',
    ) -> tuple[list[dict], int]:
        """Follow-Up Overdue — see _count_follow_up_overdue for criteria."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        seven_days_ago = today - timedelta(days=7)

        open_lead_task_overdue = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
                LeadTask.due_date < today,
            )
        )
        hubspot_task_overdue = _hubspot_task_overdue_subquery(yesterday)

        query = self._base_query().filter(
            or_(
                open_lead_task_overdue,
                and_(
                    Lead.recommended_action == 'follow_up_now',
                    Lead.last_contact_date < seven_days_ago,
                ),
                hubspot_task_overdue,
            )
        )
        total = query.count()
        sort_col = getattr(Lead, sort_by, Lead.last_contact_date)
        query = query.order_by(sort_col.asc() if sort_order == 'asc' else sort_col.desc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_lead_to_queue_row(lead) for lead in leads], total

    def get_no_next_action(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """No Next Action: active/new leads with no recommended action and no open tasks."""
        has_open_lead_task = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
            )
        )
        has_open_hubspot_task = exists().where(
            and_(
                TaskAssociation.target_type == 'lead',
                TaskAssociation.target_id == Lead.id,
                TaskAssociation.task_id == Task.id,
                Task.status.in_(['open', 'overdue']),
            )
        )
        has_open_direct_task = exists().where(
            and_(
                Task.lead_id == Lead.id,
                Task.status.in_(['open', 'overdue']),
            )
        )
        query = self._base_query().filter(
            Lead.lead_status.in_(['active', 'new']),
            or_(
                Lead.recommended_action.is_(None),
                Lead.recommended_action.in_(['create_task', 'ready_for_outreach', 'add_contact_info']),
            ),
            ~has_open_lead_task,
            ~has_open_hubspot_task,
            ~has_open_direct_task,
        )
        total = query.count()
        status_order = case((Lead.lead_status == 'new', 0), else_=1)
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        query = query.order_by(
            status_order.asc(),
            sort_col.desc() if sort_order == 'desc' else sort_col.asc(),
        )
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_lead_to_queue_row(lead) for lead in leads], total

    def get_needs_review(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'review_triggered_at',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """Needs Review: review_required = true."""
        query = self._base_query().filter(Lead.review_required.is_(True))
        total = query.count()
        sort_col = getattr(Lead, sort_by, Lead.review_triggered_at)
        query = query.order_by(sort_col.desc() if sort_order == 'desc' else sort_col.asc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_lead_to_queue_row(lead) for lead in leads], total

    def get_do_not_contact(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """Do Not Contact: lead_status = 'do_not_contact'."""
        query = self._base_query().filter(Lead.lead_status == 'do_not_contact')
        total = query.count()
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        query = query.order_by(sort_col.desc() if sort_order == 'desc' else sort_col.asc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_lead_to_queue_row(lead) for lead in leads], total

    def get_missing_property_match(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """Missing Property Match: has_property_match = false, no research task open."""
        has_research_task = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.task_type == 'research_missing_pin',
                LeadTask.status == 'open',
            )
        )
        query = self._base_query().filter(
            Lead.has_property_match.is_(False),
            ~has_research_task,
        )
        total = query.count()
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        query = query.order_by(sort_col.desc() if sort_order == 'desc' else sort_col.asc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_lead_to_queue_row(lead) for lead in leads], total
