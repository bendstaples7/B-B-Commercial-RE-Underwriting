"""Marketing Manager service for lead marketing list management.

Provides CRUD operations for marketing lists, membership management,
outreach status tracking, and filter-based list creation.  Leads with
"opted_out" outreach status in any marketing list are automatically
excluded from filter-based list creation.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_

from app import db
from app.models.lead import Lead
from app.models.marketing import MarketingList, MarketingListMember

logger = logging.getLogger(__name__)

# Valid outreach statuses in order of progression
VALID_OUTREACH_STATUSES = [
    "not_contacted",
    "contacted",
    "responded",
    "converted",
    "opted_out",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PaginatedResult:
    """Container for paginated query results."""

    items: list
    total: int
    page: int
    per_page: int
    pages: int


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class MarketingManager:
    """Manages marketing lists, membership, and outreach status tracking.

    Usage::

        manager = MarketingManager()
        ml = manager.create_list("Hot Leads Q1", user_id="user_1")
        manager.add_leads(ml.id, [1, 2, 3])
        manager.update_outreach_status(ml.id, lead_id=1, status="contacted")
    """

    # ------------------------------------------------------------------
    # List CRUD
    # ------------------------------------------------------------------

    def create_list(
        self,
        name: str,
        user_id: str,
        filter_criteria: Optional[dict] = None,
    ) -> MarketingList:
        """Create a new marketing list.

        Parameters
        ----------
        name : str
            Display name for the list.
        user_id : str
            Owner of the list.
        filter_criteria : dict or None
            Optional saved filter criteria used to create the list.

        Returns
        -------
        MarketingList
            The newly created list.

        Raises
        ------
        ValueError
            If *name* is empty.
        """
        if not name or not name.strip():
            raise ValueError("Marketing list name cannot be empty")

        ml = MarketingList(
            name=name.strip(),
            user_id=user_id,
            filter_criteria=filter_criteria,
        )
        db.session.add(ml)
        db.session.commit()

        logger.info(
            "Created marketing list '%s' (id=%d) for user '%s'",
            ml.name, ml.id, user_id,
        )
        return ml

    def rename_list(self, list_id: int, name: str) -> MarketingList:
        """Rename an existing marketing list.

        Parameters
        ----------
        list_id : int
            ID of the list to rename.
        name : str
            New name for the list.

        Returns
        -------
        MarketingList
            The updated list.

        Raises
        ------
        ValueError
            If the list is not found or *name* is empty.
        """
        ml = self._get_list_or_raise(list_id)

        if not name or not name.strip():
            raise ValueError("Marketing list name cannot be empty")

        old_name = ml.name
        ml.name = name.strip()
        ml.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(
            "Renamed marketing list %d from '%s' to '%s'",
            list_id, old_name, ml.name,
        )
        return ml

    def delete_list(self, list_id: int) -> None:
        """Delete a marketing list and all its memberships.

        Parameters
        ----------
        list_id : int
            ID of the list to delete.

        Raises
        ------
        ValueError
            If the list is not found.
        """
        ml = self._get_list_or_raise(list_id)

        db.session.delete(ml)
        db.session.commit()

        logger.info("Deleted marketing list %d ('%s')", list_id, ml.name)

    # ------------------------------------------------------------------
    # Membership management
    # ------------------------------------------------------------------

    def add_leads(self, list_id: int, lead_ids: list[int]) -> int:
        """Add leads to a marketing list.

        Leads that are already members of the list are silently skipped.

        Parameters
        ----------
        list_id : int
            ID of the marketing list.
        lead_ids : list[int]
            IDs of leads to add.

        Returns
        -------
        int
            Number of leads actually added (excluding duplicates).

        Raises
        ------
        ValueError
            If the list is not found.
        """
        ml = self._get_list_or_raise(list_id)

        # Find leads that already belong to this list
        existing = set(
            row[0]
            for row in db.session.query(MarketingListMember.lead_id)
            .filter(
                MarketingListMember.marketing_list_id == list_id,
                MarketingListMember.lead_id.in_(lead_ids),
            )
            .all()
        )

        added = 0
        for lead_id in lead_ids:
            if lead_id in existing:
                continue

            # Verify lead exists
            lead = Lead.query.get(lead_id)
            if lead is None:
                logger.warning(
                    "Skipping non-existent lead %d when adding to list %d",
                    lead_id, list_id,
                )
                continue

            member = MarketingListMember(
                marketing_list_id=list_id,
                lead_id=lead_id,
                outreach_status="not_contacted",
            )
            db.session.add(member)
            added += 1

        if added:
            db.session.commit()
            logger.info(
                "Added %d leads to marketing list %d ('%s')",
                added, list_id, ml.name,
            )

        return added

    def remove_leads(self, list_id: int, lead_ids: list[int]) -> int:
        """Remove leads from a marketing list.

        Parameters
        ----------
        list_id : int
            ID of the marketing list.
        lead_ids : list[int]
            IDs of leads to remove.

        Returns
        -------
        int
            Number of leads actually removed.

        Raises
        ------
        ValueError
            If the list is not found.
        """
        self._get_list_or_raise(list_id)

        removed = MarketingListMember.query.filter(
            MarketingListMember.marketing_list_id == list_id,
            MarketingListMember.lead_id.in_(lead_ids),
        ).delete(synchronize_session="fetch")

        db.session.commit()

        logger.info(
            "Removed %d leads from marketing list %d", removed, list_id,
        )
        return removed

    def get_list_members(
        self,
        list_id: int,
        page: int = 1,
        per_page: int = 25,
    ) -> PaginatedResult:
        """Get paginated members of a marketing list.

        Parameters
        ----------
        list_id : int
            ID of the marketing list.
        page : int
            Page number (1-indexed).
        per_page : int
            Number of items per page.

        Returns
        -------
        PaginatedResult
            Paginated list of ``MarketingListMember`` objects with their
            associated ``Lead`` data accessible via the ``lead`` backref.

        Raises
        ------
        ValueError
            If the list is not found or pagination parameters are invalid.
        """
        self._get_list_or_raise(list_id)

        if page < 1:
            raise ValueError("Page number must be >= 1")
        if per_page < 1:
            raise ValueError("Per-page must be >= 1")

        query = (
            MarketingListMember.query
            .filter(MarketingListMember.marketing_list_id == list_id)
            .order_by(MarketingListMember.added_at.desc())
        )

        total = query.count()
        pages = max(1, (total + per_page - 1) // per_page)
        items = query.offset((page - 1) * per_page).limit(per_page).all()

        return PaginatedResult(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
        )

    # ------------------------------------------------------------------
    # Outreach status
    # ------------------------------------------------------------------

    def update_outreach_status(
        self,
        list_id: int,
        lead_id: int,
        status: str,
    ) -> MarketingListMember:
        """Update the outreach status for a lead within a marketing list.

        Parameters
        ----------
        list_id : int
            ID of the marketing list.
        lead_id : int
            ID of the lead.
        status : str
            New outreach status.  Must be one of: ``"not_contacted"``,
            ``"contacted"``, ``"responded"``, ``"converted"``,
            ``"opted_out"``.

        Returns
        -------
        MarketingListMember
            The updated membership record.

        Raises
        ------
        ValueError
            If the list, lead membership, or status is invalid.
        """
        if status not in VALID_OUTREACH_STATUSES:
            raise ValueError(
                f"Invalid outreach status '{status}'. "
                f"Must be one of: {VALID_OUTREACH_STATUSES}"
            )

        member = MarketingListMember.query.filter_by(
            marketing_list_id=list_id,
            lead_id=lead_id,
        ).first()

        if member is None:
            raise ValueError(
                f"Lead {lead_id} is not a member of marketing list {list_id}"
            )

        member.outreach_status = status
        member.status_updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(
            "Updated outreach status for lead %d in list %d to '%s'",
            lead_id, list_id, status,
        )
        return member

    # ------------------------------------------------------------------
    # Filter-based list creation
    # ------------------------------------------------------------------

    def create_list_from_filters(
        self,
        name: str,
        user_id: str,
        filters: dict,
    ) -> MarketingList:
        """Create a marketing list populated with leads matching filters.

        Leads that have an ``"opted_out"`` outreach status in **any**
        marketing list are automatically excluded.

        Supported filter keys:

        - ``property_type`` (str) – exact match
        - ``city`` (str) – exact match on ``mailing_city``
        - ``state`` (str) – exact match on ``mailing_state``
        - ``zip`` (str) – exact match on ``mailing_zip``
        - ``owner_name`` (str) – case-insensitive partial match
        - ``score_min`` (float) – minimum ``lead_score`` (inclusive)
        - ``score_max`` (float) – maximum ``lead_score`` (inclusive)

        Parameters
        ----------
        name : str
            Display name for the new list.
        user_id : str
            Owner of the list.
        filters : dict
            Filter criteria (see above).

        Returns
        -------
        MarketingList
            The newly created and populated list.

        Raises
        ------
        ValueError
            If *name* is empty.
        """
        # Create the list first (stores filter_criteria for reference)
        ml = self.create_list(name, user_id, filter_criteria=filters)

        # Build lead query with filters
        query = Lead.query

        if filters.get("property_type"):
            query = query.filter(Lead.property_type == filters["property_type"])

        if filters.get("city"):
            query = query.filter(Lead.mailing_city == filters["city"])

        if filters.get("state"):
            query = query.filter(Lead.mailing_state == filters["state"])

        if filters.get("zip"):
            query = query.filter(Lead.mailing_zip == filters["zip"])

        if filters.get("owner_name"):
            query = query.filter(
                or_(
                    Lead.owner_first_name.ilike(f"%{filters['owner_name']}%"),
                    Lead.owner_last_name.ilike(f"%{filters['owner_name']}%"),
                )
            )

        if filters.get("score_min") is not None:
            query = query.filter(Lead.lead_score >= filters["score_min"])

        if filters.get("score_max") is not None:
            query = query.filter(Lead.lead_score <= filters["score_max"])

        # Exclude leads that have opted out of any marketing list
        opted_out_lead_ids = (
            db.session.query(MarketingListMember.lead_id)
            .filter(MarketingListMember.outreach_status == "opted_out")
            .distinct()
            .subquery()
        )
        query = query.filter(~Lead.id.in_(opted_out_lead_ids))

        # Add matching leads to the new list
        matching_leads = query.all()
        added = 0
        for lead in matching_leads:
            member = MarketingListMember(
                marketing_list_id=ml.id,
                lead_id=lead.id,
                outreach_status="not_contacted",
            )
            db.session.add(member)
            added += 1

        if added:
            db.session.commit()

        logger.info(
            "Created marketing list '%s' (id=%d) from filters with %d leads",
            ml.name, ml.id, added,
        )
        return ml

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_list_or_raise(self, list_id: int) -> MarketingList:
        """Retrieve a marketing list by ID or raise ValueError.

        Parameters
        ----------
        list_id : int

        Returns
        -------
        MarketingList

        Raises
        ------
        ValueError
            If the list does not exist.
        """
        ml = MarketingList.query.get(list_id)
        if ml is None:
            raise ValueError(f"Marketing list {list_id} not found")
        return ml
