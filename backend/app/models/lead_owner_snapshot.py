"""Snapshot of owner / contact / mailing state for past-owner history."""
from datetime import datetime, timezone

from app import db


def _utc_now():
    return datetime.now(timezone.utc)


class LeadOwnerSnapshot(db.Model):
    """Point-in-time owner contact + mailing payload for a lead.

    Used when contacts are marked likely-prior-owner after a sale, and again
    when active owners are replaced so mailing (still flat on the lead) is not lost.
    """

    __tablename__ = 'lead_owner_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer,
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    captured_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    reason = db.Column(db.String(40), nullable=False)
    sale_date = db.Column(db.Date, nullable=True)
    payload = db.Column(db.JSON, nullable=False, default=dict)

    def __repr__(self):
        return (
            f'<LeadOwnerSnapshot id={self.id} lead_id={self.lead_id} '
            f'reason={self.reason!r}>'
        )
