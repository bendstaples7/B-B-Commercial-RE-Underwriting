"""LeadKanbanService — provides kanban board data from the leads table.

Groups leads by recommended_action for the current authenticated user,
returning columns with action names, counts, and lead summaries.
"""

from app import db
from app.api_utils import get_current_user_id
from typing import Any, Dict, List, Optional
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Column definitions: recommended_action → label, icon, sort_order
# ---------------------------------------------------------------------------
COLUMN_DEFS: List[Dict[str, Any]] = [
    {"id": "add_contact_info",   "label": "Inbox",             "icon": "\U0001f4e5", "sort_order": 0},
    {"id": "resolve_match",      "label": "Resolve Match",     "icon": "\U0001f50d", "sort_order": 1},
    {"id": "enrich_data",        "label": "Enrich Data",       "icon": "\U0001f4cb", "sort_order": 2},
    {"id": "analyze_property",   "label": "Analyze",           "icon": "\U0001f4ca", "sort_order": 3},
    {"id": "ready_for_outreach", "label": "Ready for Outreach","icon": "\U0001f4ec", "sort_order": 4},
    {"id": "follow_up_now",      "label": "Follow Up",         "icon": "\U0001f4de", "sort_order": 5},
    {"id": "create_task",        "label": "Needs Task",        "icon": "\U0001f4dd", "sort_order": 6},
    {"id": "nurture",            "label": "Nurture",           "icon": "\U0001f331", "sort_order": 7},
    {"id": "suppress",           "label": "Suppressed",        "icon": "\U0001f6ab", "sort_order": 8},
]

# Map column IDs to the lead_status values appropriate for drag-updates
_STATUS_MAP: Dict[str, Optional[str]] = {
    "add_contact_info":   None,       # keep existing status
    "resolve_match":      "new",
    "enrich_data":        "new",
    "analyze_property":   "new",
    "ready_for_outreach": "active",
    "follow_up_now":      "follow_up",
    "create_task":        "active",
    "nurture":            "nurture",
    "suppress":           "suppressed",
}


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
        """Return all kanban columns with leads grouped by recommended_action.

        Returns ALL column definitions — even columns with zero leads.

        Parameters
        ----------
        limit : int
            Max leads per column (default 50). Set to 0 for no limit.
        column_id : str or None
            If provided, return ALL leads for the matching column (no slicing).
        """
        user_id = get_current_user_id()
        # Query leads owned by this user, grouped by recommended_action
        rows = self._query_leads_by_action(user_id)
        # Build a map: recommended_action → list of lead summaries
        action_map: Dict[Optional[str], List[Dict[str, Any]]] = {}
        for row in rows:
            action = row.recommended_action
            if action not in action_map:
                action_map[action] = []
            action_map[action].append(_lead_to_summary(row))

        # Build the ordered column list — also include null/empty (→ Inbox)
        columns: List[Dict[str, Any]] = []
        seen_actions: set = set()
        # Track full counts before slicing
        total_counts: Dict[str, int] = {}

        for col_def in COLUMN_DEFS:
            action_id = col_def["id"]
            seen_actions.add(action_id)
            leads_for_col = action_map.get(action_id, [])
            full_count = len(leads_for_col)
            total_counts[action_id] = full_count

            # When column_id matches, return ALL leads for that column (no slicing)
            if column_id and column_id == action_id:
                columns.append({
                    "id": action_id,
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
                    "id": action_id,
                    "label": col_def["label"],
                    "icon": col_def["icon"],
                    "leads": sliced,
                    "count": full_count,
                    "sort_order": col_def["sort_order"],
                })

        # Handle any leads with NULL recommended_action → inbox column
        null_leads = action_map.get(None, [])
        if null_leads:
            null_count = len(null_leads)
            for col in columns:
                if col["id"] == "add_contact_info":
                    col["leads"].extend(null_leads[:limit] if limit > 0 and col["id"] != column_id else null_leads)
                    col["count"] += null_count
                    total_counts["add_contact_info"] = total_counts.get("add_contact_info", 0) + null_count
                    break

        return {
            "columns": columns,
            "total_counts": total_counts,
        }

    def move_lead(self, lead_id: int, target_action: str) -> Dict[str, Any]:
        """Move a lead to a new recommended_action, updating lead_status too.

        Returns the updated lead summary.
        """
        user_id = get_current_user_id()
        from app.models.lead import Lead

        lead = Lead.query.filter_by(id=lead_id, owner_user_id=user_id).first()
        if not lead:
            raise ValueError(f"Lead {lead_id} not found or not owned by current user.")

        # Update recommended_action
        lead.recommended_action = target_action

        # Update lead_status based on target action
        new_status = _STATUS_MAP.get(target_action)
        if new_status is not None:
            lead.lead_status = new_status

        db.session.commit()

        # Re-fetch to get updated values
        db.session.refresh(lead)
        return _lead_to_summary(lead)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _query_leads_by_action(self, user_id: str) -> List[db.Row]:
        """Query all leads for a user, ordered by recommended_action then score desc."""
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
              AND recommended_action IS NOT NULL
            ORDER BY recommended_action, lead_score DESC NULLS LAST
        """)
        result = db.session.execute(sql, {"user_id": user_id})
        return list(result)