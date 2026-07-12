"""QueueService — badge counts and paginated results for all 7 lead queues."""
from datetime import date, datetime, timedelta
from typing import ClassVar

from sqlalchemy import exists, and_, or_, case, select

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry, MailQueueItem
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.services.queue_order_cache import queue_order_cache
from app.services.open_letter_contact_mapper import is_mailable_lead
from app.services.recommended_action_metadata import get_recommended_action_display
from app.services.outreach_method_service import resolve_outreach_contacts_for_leads
from app.services.scoring_rubric import format_last_sale_at, is_recently_sold
from app.services.entity_owner_policy import is_cold_mail_blocked

# Statuses that represent active outreach pipeline (not terminal or suppressed)
ACTIVE_PIPELINE_STATUSES = [
    'skip_trace',
    'awaiting_skip_trace',
    'mailing_no_contact_made',
    'mailing_contacted_no_interest',
    'mailing_contacted_interested',
    'negotiating_remote',
    'in_person_appointment',
    'offer_delivered',
]

# Statuses where outreach is in progress (has had contact)
CONTACTED_STATUSES = [
    'mailing_contacted_no_interest',
    'mailing_contacted_interested',
    'negotiating_remote',
    'in_person_appointment',
    'offer_delivered',
]


def _lead_to_queue_row(
    lead,
    outreach_contacts: dict[int, dict | None] | None = None,
    *,
    last_mailed_at=None,
    owner_displays: dict[int, dict] | None = None,
) -> dict:
    """Convert a Lead model instance to a queue row dict."""
    contact_method = lead.recommended_contact_method
    ra_display = get_recommended_action_display(lead.recommended_action, contact_method)
    lead_id = getattr(lead, 'id', None)
    if outreach_contacts is not None and isinstance(lead_id, int):
        outreach_contact = outreach_contacts.get(lead_id)
    else:
        from app.services.outreach_method_service import resolve_outreach_contact
        outreach_contact = resolve_outreach_contact(lead, contact_method)

    display = {}
    if owner_displays is not None and isinstance(lead_id, int):
        display = owner_displays.get(lead_id) or {}
    owner_first = display.get('first_name') or lead.owner_first_name
    owner_last = display.get('last_name') or lead.owner_last_name
    flat_display = ' '.join(
        part for part in (lead.owner_first_name, lead.owner_last_name) if part
    ) or None
    owner_display_name = display.get('owner_display_name') or flat_display
    best_phone = display.get('best_phone') or getattr(lead, 'phone_1', None)
    best_email = display.get('best_email') or getattr(lead, 'email_1', None)

    return {
        'id': lead.id,
        'owner_first_name': owner_first,
        'owner_last_name': owner_last,
        'owner_display_name': owner_display_name,
        'best_phone': best_phone,
        'best_email': best_email,
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'lead_score': lead.lead_score,
        'lead_status': lead.lead_status,
        'recommended_action': lead.recommended_action,
        'recommended_contact_method': contact_method,
        'outreach_action_label': ra_display.get('label'),
        'outreach_contact': outreach_contact,
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
        'last_mailed_at': last_mailed_at,
        'last_sale_at': format_last_sale_at(lead),
    }


def _leads_to_queue_rows(leads: list) -> list[dict]:
    """Build queue rows with batched outreach + owner-display resolution (avoids N+1)."""
    from app.services.contact_service import batch_owner_display_for_leads

    contacts = resolve_outreach_contacts_for_leads(leads)
    owner_displays = batch_owner_display_for_leads(
        [lead.id for lead in leads if isinstance(getattr(lead, 'id', None), int)]
    )
    return [
        _lead_to_queue_row(lead, contacts, owner_displays=owner_displays)
        for lead in leads
    ]


def _apply_queue_sort(query, sort_by: str, sort_order: str, default_col=None):
    """Order queue results; tie-break lead_score sorts with motivation_score DESC."""
    sort_col = getattr(Lead, sort_by, default_col or Lead.lead_score)
    if sort_order == 'desc':
        primary = sort_col.desc()
    else:
        primary = sort_col.asc()
    if sort_by == 'lead_score' or sort_col is Lead.lead_score:
        return query.order_by(primary, Lead.motivation_score.desc(), Lead.id.asc())
    return query.order_by(primary, Lead.id.asc())


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


def _lead_awaiting_mail_subquery():
    """Lead is staged in a mail batch and should not surface as a due native task.

    Prefer MailQueueItem; keep legacy up_next_to_mail for uncleared rows.
    """
    queued_item = exists().where(
        and_(
            MailQueueItem.lead_id == Lead.id,
            MailQueueItem.status == 'queued',
            MailQueueItem.user_id == Lead.owner_user_id,
        )
    )
    return or_(Lead.up_next_to_mail.is_(True), queued_item)


def _open_lead_task_due_today_excluding_mail_awaiting(today: date):
    """Open native task due today, excluding leads waiting in a mail batch."""
    return and_(
        exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
                LeadTask.due_date <= today,
            )
        ),
        ~_lead_awaiting_mail_subquery(),
    )


def _open_lead_task_overdue_excluding_mail_awaiting(today: date):
    """Open native task overdue, excluding leads waiting in a mail batch."""
    return and_(
        exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == 'open',
                LeadTask.due_date < today,
            )
        ),
        ~_lead_awaiting_mail_subquery(),
    )


def _hubspot_task_overdue_excluding_mail_awaiting(cutoff_date):
    """HubSpot task overdue, excluding leads waiting in a mail batch."""
    return and_(
        _hubspot_task_overdue_subquery(cutoff_date),
        ~_lead_awaiting_mail_subquery(),
    )


# Outreach display filters for Today's Action (match frontend outreachDisplayLabel).
TODAYS_ACTION_OUTREACH_FILTERS = frozenset({
    'mail_now', 'call_now', 'email_now', 'text_now',
})


def _outreach_filter_clause(outreach: str | None):
    """SQLAlchemy clause for Mail Now / Call Now / etc. display labels."""
    if not outreach:
        return None
    key = outreach.strip().lower()
    if key == 'mail_now':
        return or_(
            Lead.recommended_action == 'mail_ready',
            and_(
                Lead.recommended_action == 'follow_up_now',
                Lead.recommended_contact_method == 'direct_mail',
            ),
        )
    if key == 'call_now':
        return or_(
            Lead.recommended_action == 'call_ready',
            and_(
                Lead.recommended_action == 'follow_up_now',
                Lead.recommended_contact_method == 'phone',
            ),
        )
    if key == 'email_now':
        return and_(
            Lead.recommended_action == 'follow_up_now',
            Lead.recommended_contact_method == 'email',
        )
    if key == 'text_now':
        return and_(
            Lead.recommended_action == 'follow_up_now',
            Lead.recommended_contact_method == 'text',
        )
    return None


def normalize_todays_outreach_filter(outreach: str | None) -> str | None:
    if not outreach:
        return None
    key = outreach.strip().lower()
    return key if key in TODAYS_ACTION_OUTREACH_FILTERS else None


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

        Non-admin users see only leads they own (exact match on owner_user_id).
        Leads with owner_user_id IS NULL are not visible to non-admin users.
        Admins (owner_user_id=None passed in) see all leads.
        """
        q = Lead.query
        if self._owner_user_id:
            q = q.filter(Lead.owner_user_id == self._owner_user_id)
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

    def count_mail_candidates(self, mail_user_id: str) -> int:
        """Leads recommended for mail that are not already queued by this user."""
        query = self._mail_candidates_query(mail_user_id)
        return sum(
            1 for lead in query.all()
            if (
                not is_recently_sold(lead)
                and is_mailable_lead(lead)
                and not is_cold_mail_blocked(lead)
            )
        )

    # ------------------------------------------------------------------
    # Private count helpers
    # ------------------------------------------------------------------

    def _count_todays_action(self, today: date) -> int:
        """Today's Action: due work only (open tasks due today or earlier)."""
        return self._todays_action_query(today).count()

    def _todays_action_query(self, today: date | None = None, outreach: str | None = None):
        """Base Today's Action membership query, optionally filtered by outreach label."""
        today = today or date.today()
        open_lead_task_due_today = _open_lead_task_due_today_excluding_mail_awaiting(today)
        hubspot_task_due_today = _hubspot_task_overdue_excluding_mail_awaiting(today)
        query = self._base_query().filter(
            Lead.lead_status.in_(ACTIVE_PIPELINE_STATUSES),
            or_(
                open_lead_task_due_today,
                hubspot_task_due_today,
            ),
        )
        clause = _outreach_filter_clause(normalize_todays_outreach_filter(outreach))
        if clause is not None:
            query = query.filter(clause)
        return query

    def get_todays_action_outreach_counts(self) -> dict[str, int]:
        """Counts of Today's Action leads by outreach display bucket."""
        today = date.today()
        base_total = self._todays_action_query(today).count()
        return {
            'all': base_total,
            'mail_now': self._todays_action_query(today, 'mail_now').count(),
            'call_now': self._todays_action_query(today, 'call_now').count(),
            'email_now': self._todays_action_query(today, 'email_now').count(),
            'text_now': self._todays_action_query(today, 'text_now').count(),
        }

    def get_todays_action_lead_ids(self, outreach: str | None = None) -> list[int]:
        """All Today's Action lead IDs matching an optional outreach filter."""
        query = self._todays_action_query(outreach=outreach)
        query = _apply_queue_sort(query, 'lead_score', 'desc')
        return [row[0] for row in query.with_entities(Lead.id).all()]

    def get_todays_action(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
        outreach: str | None = None,
    ) -> tuple[list[dict], int]:
        """Today's Action — due open tasks; optional outreach display filter."""
        query = self._todays_action_query(outreach=outreach)
        total = query.count()
        query = _apply_queue_sort(query, sort_by, sort_order)
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_leads_to_queue_rows(leads), total]

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
        open_lead_task_overdue = _open_lead_task_overdue_excluding_mail_awaiting(today)
        hubspot_task_overdue = _hubspot_task_overdue_excluding_mail_awaiting(yesterday)

        return (
            self._base_query()
            .filter(
                or_(
                    open_lead_task_overdue,
                    and_(
                        Lead.recommended_action == 'follow_up_now',
                        Lead.last_contact_date < seven_days_ago,
                        ~_lead_awaiting_mail_subquery(),
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
                Lead.lead_status.in_(ACTIVE_PIPELINE_STATUSES),
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
        query = _apply_queue_sort(query, sort_by, sort_order)
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_leads_to_queue_rows(leads), total]

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

        open_lead_task_overdue = _open_lead_task_overdue_excluding_mail_awaiting(today)
        hubspot_task_overdue = _hubspot_task_overdue_excluding_mail_awaiting(yesterday)

        query = self._base_query().filter(
            or_(
                open_lead_task_overdue,
                and_(
                    Lead.recommended_action == 'follow_up_now',
                    Lead.last_contact_date < seven_days_ago,
                    ~_lead_awaiting_mail_subquery(),
                ),
                hubspot_task_overdue,
            )
        )
        total = query.count()
        sort_col = getattr(Lead, sort_by, Lead.last_contact_date)
        query = query.order_by(sort_col.asc() if sort_order == 'asc' else sort_col.desc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_leads_to_queue_rows(leads), total]

    def get_no_next_action(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """No Next Action: active/new leads with no recommended action and no open tasks."""
        query = self._no_next_action_query()
        total = query.count()
        status_order = case((Lead.lead_status == 'awaiting_skip_trace', 0), else_=1)
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        if sort_by == 'lead_score':
            query = query.order_by(
                status_order.asc(),
                sort_col.desc() if sort_order == 'desc' else sort_col.asc(),
                Lead.motivation_score.desc(),
                Lead.id.asc(),
            )
        else:
            query = query.order_by(
                status_order.asc(),
                sort_col.desc() if sort_order == 'desc' else sort_col.asc(),
                Lead.id.asc(),
            )
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_leads_to_queue_rows(leads), total]

    def _no_next_action_query(self):
        """Base query for No Next Action queue membership."""
        from sqlalchemy import and_, exists, or_
        from app.models.lead_task import LeadTask
        from app.models.task import Task
        from app.models.task_association import TaskAssociation

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
        return self._base_query().filter(
            Lead.lead_status.in_(ACTIVE_PIPELINE_STATUSES),
            or_(
                Lead.recommended_action.is_(None),
                Lead.recommended_action.in_(['create_task', 'ready_for_outreach', 'add_contact_info']),
            ),
            ~has_open_lead_task,
            ~has_open_hubspot_task,
            ~has_open_direct_task,
        )

    def get_no_next_action_status_counts(self) -> dict[str, int]:
        """Count leads in No Next Action queue grouped by lead_status."""
        from sqlalchemy import func

        rows = (
            self._no_next_action_query()
            .with_entities(Lead.lead_status, func.count(Lead.id))
            .group_by(Lead.lead_status)
            .all()
        )
        return {str(status): count for status, count in rows}

    def get_no_next_action_lead_ids_by_status(self, lead_status: str) -> list[int]:
        """All lead ids in No Next Action queue with the given status."""
        leads = (
            self._no_next_action_query()
            .filter(Lead.lead_status == lead_status)
            .with_entities(Lead.id)
            .all()
        )
        return [row[0] for row in leads]

    def bulk_update_no_next_action_status(
        self,
        source_status: str,
        target_status: str,
        *,
        reason: str = '',
        actor: str = 'anonymous',
    ) -> dict:
        """Update all No Next Action leads with source_status to target_status."""
        from app.services.lead_status_service import apply_lead_status_change

        lead_ids = self.get_no_next_action_lead_ids_by_status(source_status)
        leads_by_id = {
            lead.id: lead
            for lead in Lead.query.filter(Lead.id.in_(lead_ids)).all()
        } if lead_ids else {}
        successes = 0
        failures = 0
        for lead_id in lead_ids:
            try:
                lead = leads_by_id.get(lead_id)
                if lead is None:
                    failures += 1
                    continue
                apply_lead_status_change(
                    lead, target_status, reason=reason, actor=actor, recompute_action=True,
                )
                successes += 1
            except Exception:
                db.session.rollback()
                failures += 1
        return {
            'successes': successes,
            'failures': failures,
            'total_matched': len(lead_ids),
        }

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
        if sort_by == 'lead_score':
            query = _apply_queue_sort(query, sort_by, sort_order, Lead.review_triggered_at)
        else:
            query = query.order_by(sort_col.desc() if sort_order == 'desc' else sort_col.asc())
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_leads_to_queue_rows(leads), total]

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
        query = _apply_queue_sort(query, sort_by, sort_order)
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_leads_to_queue_rows(leads), total]

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
        query = _apply_queue_sort(query, sort_by, sort_order)
        leads = query.offset((page - 1) * per_page).limit(per_page).all()
        return [_leads_to_queue_rows(leads), total]

    def _mail_candidates_query(self, mail_user_id: str):
        """Leads with mail_ready recommendation not already in this user's mail queue."""
        already_queued = exists().where(
            and_(
                MailQueueItem.lead_id == Lead.id,
                MailQueueItem.user_id == mail_user_id,
                MailQueueItem.status == 'queued',
            )
        )
        recent_invalid = exists().where(
            and_(
                MailQueueItem.lead_id == Lead.id,
                MailQueueItem.user_id == mail_user_id,
                MailQueueItem.status == 'invalid_address',
                MailQueueItem.created_at >= datetime.utcnow() - timedelta(days=30),
            )
        )
        q = (
            Lead.query.filter(Lead.owner_user_id == mail_user_id)
            .filter(
                Lead.lead_status.in_(ACTIVE_PIPELINE_STATUSES),
                Lead.recommended_action == 'mail_ready',
                ~already_queued,
                ~recent_invalid,
            )
        )
        return q

    def get_mail_candidates(
        self,
        mail_user_id: str,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> tuple[list[dict], int]:
        """Paginated mail-ready leads not yet staged for the next batch."""
        from app.services.last_mailed_service import format_last_mailed_at, get_last_mailed_at_by_lead_ids

        query = self._mail_candidates_query(mail_user_id)
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        if sort_order == 'desc':
            order = (sort_col.desc(), Lead.motivation_score.desc())
        else:
            order = (sort_col.asc(), Lead.motivation_score.desc())
        ordered = query.order_by(*order).all()
        eligible = [
            lead for lead in ordered
            if (
                not is_recently_sold(lead)
                and is_mailable_lead(lead)
                and not is_cold_mail_blocked(lead)
            )
        ]
        total = len(eligible)
        start = (page - 1) * per_page
        leads = eligible[start:start + per_page]
        from app.services.contact_service import batch_owner_display_for_leads

        contacts = resolve_outreach_contacts_for_leads(leads)
        owner_displays = batch_owner_display_for_leads([lead.id for lead in leads])
        last_mailed = get_last_mailed_at_by_lead_ids([lead.id for lead in leads])
        return [
            _lead_to_queue_row(
                lead,
                contacts,
                last_mailed_at=format_last_mailed_at(last_mailed.get(lead.id)),
                owner_displays=owner_displays,
            )
            for lead in leads
        ], total

    def get_mail_candidate_ids(
        self,
        mail_user_id: str,
        sort_by: str = 'lead_score',
        sort_order: str = 'desc',
    ) -> list[int]:
        """All mail-ready lead IDs not yet staged, excluding recently sold."""
        query = self._mail_candidates_query(mail_user_id)
        sort_col = getattr(Lead, sort_by, Lead.lead_score)
        if sort_order == 'desc':
            order = (sort_col.desc(), Lead.motivation_score.desc())
        else:
            order = (sort_col.asc(), Lead.motivation_score.desc())
        ordered = query.order_by(*order).all()
        return [
            lead.id for lead in ordered
            if (
                not is_recently_sold(lead)
                and is_mailable_lead(lead)
                and not is_cold_mail_blocked(lead)
            )
        ]

    # Cap for prev/next neighbor lookup (same order as list endpoints).
    QUEUE_NAV_CAP = 500

    # URL kebab-key → (service method name, default sort_by, default sort_order)
    _QUEUE_NAV_CONFIG: ClassVar[dict[str, tuple[str, str, str]]] = {
        'todays-action': ('get_todays_action', 'lead_score', 'desc'),
        'previously-warm': ('get_previously_warm', 'lead_score', 'desc'),
        'follow-up-overdue': ('get_follow_up_overdue', 'last_contact_date', 'asc'),
        'no-next-action': ('get_no_next_action', 'lead_score', 'desc'),
        'needs-review': ('get_needs_review', 'review_triggered_at', 'desc'),
        'do-not-contact': ('get_do_not_contact', 'lead_score', 'desc'),
        'missing-property-match': ('get_missing_property_match', 'lead_score', 'desc'),
        'mail-candidates': ('get_mail_candidates', 'lead_score', 'desc'),
    }

    def _ordered_ids_from_query(self, query, cap: int) -> tuple[list[int], int]:
        """Count matching leads and return up to ``cap`` IDs in the query's current order."""
        total = query.count()
        rows = query.with_entities(Lead.id).limit(cap).all()
        return [row[0] for row in rows], total

    def _get_ordered_ids_for_queue(
        self,
        queue_key: str,
        sort_by: str,
        sort_order: str,
        mail_user_id: str | None,
        cap: int,
        outreach: str | None = None,
    ) -> tuple[list[int], int]:
        """Lightweight ordered ID list for navigation (no outreach row hydration)."""
        if queue_key == 'mail-candidates':
            if not mail_user_id:
                raise ValueError('mail_user_id is required for mail-candidates navigation')
            all_ids = self.get_mail_candidate_ids(mail_user_id, sort_by, sort_order)
            return all_ids[:cap], len(all_ids)

        if queue_key == 'todays-action':
            query = self._todays_action_query(outreach=outreach)
            query = _apply_queue_sort(query, sort_by, sort_order)
            return self._ordered_ids_from_query(query, cap)

        if queue_key == 'previously-warm':
            query = _apply_queue_sort(
                self._base_query().filter(Lead.is_warm.is_(True)),
                sort_by,
                sort_order,
            )
            return self._ordered_ids_from_query(query, cap)

        if queue_key == 'follow-up-overdue':
            today = date.today()
            yesterday = today - timedelta(days=1)
            seven_days_ago = today - timedelta(days=7)
            open_lead_task_overdue = _open_lead_task_overdue_excluding_mail_awaiting(today)
            hubspot_task_overdue = _hubspot_task_overdue_excluding_mail_awaiting(yesterday)
            query = self._base_query().filter(
                or_(
                    open_lead_task_overdue,
                    and_(
                        Lead.recommended_action == 'follow_up_now',
                        Lead.last_contact_date < seven_days_ago,
                        ~_lead_awaiting_mail_subquery(),
                    ),
                    hubspot_task_overdue,
                )
            )
            sort_col = getattr(Lead, sort_by, Lead.last_contact_date)
            query = query.order_by(sort_col.asc() if sort_order == 'asc' else sort_col.desc())
            return self._ordered_ids_from_query(query, cap)

        if queue_key == 'no-next-action':
            has_open_lead_task = exists().where(
                and_(LeadTask.lead_id == Lead.id, LeadTask.status == 'open')
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
                and_(Task.lead_id == Lead.id, Task.status.in_(['open', 'overdue']))
            )
            query = self._base_query().filter(
                Lead.lead_status.in_(ACTIVE_PIPELINE_STATUSES),
                or_(
                    Lead.recommended_action.is_(None),
                    Lead.recommended_action.in_(['create_task', 'ready_for_outreach', 'add_contact_info']),
                ),
                ~has_open_lead_task,
                ~has_open_hubspot_task,
                ~has_open_direct_task,
            )
            status_order = case((Lead.lead_status == 'awaiting_skip_trace', 0), else_=1)
            sort_col = getattr(Lead, sort_by, Lead.lead_score)
            if sort_by == 'lead_score':
                query = query.order_by(
                    status_order.asc(),
                    sort_col.desc() if sort_order == 'desc' else sort_col.asc(),
                    Lead.motivation_score.desc(),
                )
            else:
                query = query.order_by(
                    status_order.asc(),
                    sort_col.desc() if sort_order == 'desc' else sort_col.asc(),
                )
            return self._ordered_ids_from_query(query, cap)

        if queue_key == 'needs-review':
            query = self._base_query().filter(Lead.review_required.is_(True))
            sort_col = getattr(Lead, sort_by, Lead.review_triggered_at)
            if sort_by == 'lead_score':
                query = _apply_queue_sort(query, sort_by, sort_order, Lead.review_triggered_at)
            else:
                query = query.order_by(sort_col.desc() if sort_order == 'desc' else sort_col.asc())
            return self._ordered_ids_from_query(query, cap)

        if queue_key == 'do-not-contact':
            query = _apply_queue_sort(
                self._base_query().filter(Lead.lead_status == 'do_not_contact'),
                sort_by,
                sort_order,
            )
            return self._ordered_ids_from_query(query, cap)

        if queue_key == 'missing-property-match':
            has_research_task = exists().where(
                and_(
                    LeadTask.lead_id == Lead.id,
                    LeadTask.task_type == 'research_missing_pin',
                    LeadTask.status == 'open',
                )
            )
            query = _apply_queue_sort(
                self._base_query().filter(
                    Lead.has_property_match.is_(False),
                    ~has_research_task,
                ),
                sort_by,
                sort_order,
            )
            return self._ordered_ids_from_query(query, cap)

        raise ValueError(f'Unknown queue key: {queue_key}')

    def _navigation_cache_key(
        self,
        queue_key: str,
        sort_by: str,
        sort_order: str,
        mail_user_id: str | None,
        outreach: str | None = None,
    ) -> tuple:
        scope = self._owner_user_id or '__admin__'
        return (scope, queue_key, sort_by, sort_order, mail_user_id or '', outreach or '')

    def get_navigation(
        self,
        queue_key: str,
        lead_id: int,
        sort_by: str | None = None,
        sort_order: str | None = None,
        mail_user_id: str | None = None,
        outreach: str | None = None,
    ) -> dict:
        """Return position / neighbors for a lead within a work queue.

        Uses a cached ordered ID list (IDs only — no row hydration) so rapid
        prev/next in the command center does not re-scan the full queue.
        """
        config = self._QUEUE_NAV_CONFIG.get(queue_key)
        if config is None:
            raise ValueError(f"Unknown queue key: {queue_key}")

        _, default_sort_by, default_sort_order = config
        sort_by = sort_by or default_sort_by
        sort_order = sort_order or default_sort_order
        outreach = normalize_todays_outreach_filter(outreach) if queue_key == 'todays-action' else None

        cache_key = self._navigation_cache_key(
            queue_key, sort_by, sort_order, mail_user_id, outreach,
        )
        cached = queue_order_cache.get(cache_key)
        if cached is not None:
            ids, total = cached
        else:
            ids, total = self._get_ordered_ids_for_queue(
                queue_key, sort_by, sort_order, mail_user_id, self.QUEUE_NAV_CAP,
                outreach=outreach,
            )
            queue_order_cache.set(cache_key, ids, total)

        try:
            idx = ids.index(lead_id)
        except ValueError:
            return {
                'queue_key': queue_key,
                'lead_id': lead_id,
                'position': None,
                'total': total,
                'prev_id': None,
                'next_id': ids[0] if ids else None,
            }

        return {
            'queue_key': queue_key,
            'lead_id': lead_id,
            'position': idx + 1,
            'total': total,
            'prev_id': ids[idx - 1] if idx > 0 else None,
            'next_id': ids[idx + 1] if idx + 1 < len(ids) else None,
        }
