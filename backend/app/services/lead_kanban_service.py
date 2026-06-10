"""LeadKanbanService — provides kanban board data from the leads table.

Groups leads by lead_status (pipeline stages) for the current authenticated user,
returning columns with status names, counts, and lead summaries.
"""

from app import db
from app.api_utils import get_current_user_id
from typing import Any, Dict, List, Optional
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Column definitions: lead_status → label, icon, sort_order
# All 13 pipeline stages from the Lead model.
# ---------------------------------------------------------------------------
COLUMN_DEFS: List[Dict[str, Any]] = [
    {"id": "skip_trace",                  "label": "Skip Trace",                    "icon": "\U0001f50d", "sort_order": 0},
    {"id": "awaiting_skip_trace",         "label": "Awaiting Skip Trace",           "icon": "\u23f3",     "sort_order": 1},
    {"id": "mailing_no_contact_made",     "label": "Mailing, No Contact Made",      "icon": "\U0001f4ec", "sort_order": 2},
    {"id": "mailing_contacted_no_interest","label": "Mailing, Contacted, No Interest","icon": "\U0001f4ed", "sort_order": 3},
    {"id": "mailing_contacted_interested", "label": "Mailing, Contacted, Interested","icon": "\U0001f4e8", "sort_order": 4},
    {"id": "negotiating_remote",          "label": "Negotiating Remote",             "icon": "\U0001f91d", "sort_order": 5},
    {"id": "in_person_appointment",       "label": "In Person Appointment",         "icon": "\U0001f4c5", "sort_order": 6},
    {"id": "offer_delivered",             "label": "Offer Delivered",               "icon": "\U0001f4c4", "sort_order": 7},
    {"id": "deprioritize",                "label": "Deprioritize",                  "icon": "\u23f8\ufe0f", "sort_order": 8},
    {"id": "deal_won",                    "label": "Deal Won",                      "icon": "\U0001f389", "sort_order": 9},
    {"id": "deal_lost",                   "label": "Deal Lost",                     "icon": "\u274c",     "sort_order": 10},
    {"id": "suppressed",                  "label": "Suppressed",                    "icon": "\U0001f6ab", "sort_order": 11},
    {"id": "do_not_contact",              "label": "Do Not Contact",                "icon": "\u26d4",     "sort_order": 12},
]

# Map column IDs (lead_status values) to themselves — each column maps 1:1.
_STATUS_MAP: Dict[str, Optional[str]] = {
    "skip_trace":                   "skip_trace",
    "awaiting_skip_trace":          "awaiting_skip_trace",
    "mailing_no_contact_made":      "mailing_no_contact_made",
    "mailing_contacted_no_interest":"mailing_contacted_no_interest",
    "mailing_contacted_interested": "mailing_contacted_interested",
    "negotiating_remote":           "negotiating_remote",
    "in_person_appointment":        "in_person_appointment",
    "offer_delivered":              "offer_delivered",
    "deprioritize":                 "deprioritize",
    "deal_won":                     "deal_won",
    "deal_lost":                    "deal_lost",
    "suppressed":                   "suppressed",
    "do_not_contact":               "do_not_contact",
}

# Valid lead_status values derived from column definitions
_VALID_STATUSES: set = {col["id"] for col in COLUMN_DEFS}


def _lead_to_summary(row: db.Row) -> Dict[str, Any]:
    """Convert a raw lead DB row to a lead summary dict."""
    return {
        "id": row.id,
        "property_address": row.property_street or "",
        "owner_name": " ".join(
            filter(None, [row.owner_first_name or "", row.owner_last_name or ""])
        ),
        "lead_status": row.lead_status,
        "recommended_action": row.recommended_action,
        "lead_score": row.lead_score if row.lead_score is not None else 0,
        "lead_category": row.lead_category or "",
        "source_type": row.source_type or "",
        "last_contact_date": (
            row.last_contact_date.isoformat() if row.last_contact_date else None
        ),
        "analysis_complete": bool(row.analysis_complete),
        "is_warm": bool(row.is_warm),
        "has_phone": bool(row.has_phone),
        "has_email": bool(row.has_email),
        "has_property_match": bool(row.has_property_match),
    }


class LeadKanbanService:
    """Service for lead-based kanban board operations."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_columns(
        self,
        limit: int = 50,
        column_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return all kanban columns with leads grouped by lead_status.

        Returns ALL column definitions — even columns with zero leads.

        Parameters
        ----------
        limit : int
            Max leads per column (default 50). Set to 0 for no limit.
        column_id : str or None
            If provided, return ALL leads for the matching column (no slicing).
        """
        user_id = get_current_user_id()
        # Query leads owned by this user, grouped by lead_status
        rows = self._query_leads_by_status(user_id)
        # Build a map: lead_status → list of lead summaries
        status_map: Dict[Optional[str], List[Dict[str, Any]]] = {}
        for row in rows:
            status = row.lead_status
            if status not in status_map:
                status_map[status] = []
            status_map[status].append(_lead_to_summary(row))

        # Build the ordered column list — also include null/empty leads
        columns: List[Dict[str, Any]] = []
        total_counts: Dict[str, int] = {}

        for col_def in COLUMN_DEFS:
            col_status = col_def["id"]
            leads_for_col = status_map.get(col_status, [])
            full_count = len(leads_for_col)
            total_counts[col_status] = full_count

            # When column_id matches, return ALL leads for that column (no slicing)
            if column_id and column_id == col_status:
                columns.append({
                    "id": col_status,
                    "label": col_def["label"],
                    "icon": col_def["icon"],
                    "leads": leads_for_col,
                    "count": full_count,
                    "sort_order": col_def["sort_order"],
                })
            else:
                # Otherwise, slice to limit (limit=0 means no limit)
                sliced = leads_for_col[:limit] if limit > 0 else leads_for_col
                columns.append({
                    "id": col_status,
                    "label": col_def["label"],
                    "icon": col_def["icon"],
                    "leads": sliced,
                    "count": full_count,
                    "sort_order": col_def["sort_order"],
                })

        # Handle any leads with NULL lead_status — attach them to the first
        # appropriate column (skip_trace) as an inbox
        null_leads = status_map.get(None, [])
        if null_leads:
            null_count = len(null_leads)
            for col in columns:
                if col["id"] == "skip_trace":
                    sliced_nulls = null_leads if (col["id"] == column_id or limit == 0) else null_leads[:limit]
                    col["leads"].extend(sliced_nulls)
                    col["count"] += null_count
                    total_counts["skip_trace"] = total_counts.get("skip_trace", 0) + null_count
                    break

        return {
            "columns": columns,
            "total_counts": total_counts,
        }

    def move_lead(self, lead_id: int, target_status: str) -> Dict[str, Any]:
        """Move a lead to a new lead_status (pipeline stage).

        Updates lead_status to the target value. The recommended_action is kept
        as-is since it is computed by the action engine, not user-driven.

        Returns the updated lead summary.
        """
        user_id = get_current_user_id()
        from app.models.lead import Lead

        lead = Lead.query.filter_by(id=lead_id, owner_user_id=user_id).first()
        if not lead:
            raise ValueError(f"Lead {lead_id} not found or not owned by current user.")

        # Validate target_status against known column IDs
        if target_status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid target_status '{target_status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
            )

        # Update lead_status
        lead.lead_status = target_status

        db.session.commit()

        # Re-fetch to get updated values
        db.session.refresh(lead)
        return _lead_to_summary(lead)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _query_leads_by_status(self, user_id: str) -> List[db.Row]:
        """Query all leads for a user, ordered by lead_status, then score desc.

        Uses a CASE expression to sort pipeline stages in the canonical order.
        """
        sql = text("""
            SELECT
                id,
                property_street,
                owner_first_name,
                owner_last_name,
                lead_status,
                recommended_action,
                lead_score,
                lead_category,
                source_type,
                last_contact_date,
                analysis_complete,
                is_warm,
                has_phone,
                has_email,
                has_property_match
            FROM leads
            WHERE owner_user_id = :user_id
            ORDER BY
                CASE lead_status
                    WHEN 'skip_trace'                    THEN 0
                    WHEN 'awaiting_skip_trace'           THEN 1
                    WHEN 'mailing_no_contact_made'       THEN 2
                    WHEN 'mailing_contacted_no_interest' THEN 3
                    WHEN 'mailing_contacted_interested'  THEN 4
                    WHEN 'negotiating_remote'            THEN 5
                    WHEN 'in_person_appointment'         THEN 6
                    WHEN 'offer_delivered'               THEN 7
                    WHEN 'deprioritize'                  THEN 8
                    WHEN 'deal_won'                      THEN 9
                    WHEN 'deal_lost'                     THEN 10
                    WHEN 'suppressed'                    THEN 11
                    WHEN 'do_not_contact'                THEN 12
                    ELSE 99
                END,
                lead_score DESC NULLS LAST
        """)
        result = db.session.execute(sql, {"user_id": user_id})
        return list(result)