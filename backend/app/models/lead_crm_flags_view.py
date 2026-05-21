"""LeadCRMFlagsView — read-only SQLAlchemy model mapped to the lead_crm_flags PostgreSQL view."""
from app import db


class LeadCRMFlagsView(db.Model):
    """Read-only model backed by the lead_crm_flags view.

    The view computes has_phone, has_email, and has_property_match on the fly
    from source-of-truth tables (phone/email columns, contact_phones,
    contact_emails, hubspot_matches) rather than relying on the denormalized
    boolean flags stored on the leads table.

    Used by ActionEngineService.compute_recommended_action as the primary
    source for these three flags, with a fallback to the stored columns for
    test compatibility (SQLite in-memory tests don't have the view).
    """
    __tablename__ = 'lead_crm_flags'

    # Disable Alembic autogenerate for this view — it is managed by a raw
    # CREATE OR REPLACE VIEW migration, not by SQLAlchemy DDL.
    __table_args__ = {'info': {'is_view': True}}

    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), primary_key=True)
    has_phone_computed = db.Column(db.Boolean)
    has_email_computed = db.Column(db.Boolean)
    has_property_match_computed = db.Column(db.Boolean)

    def __repr__(self):
        return (
            f'<LeadCRMFlagsView lead_id={self.lead_id} '
            f'phone={self.has_phone_computed} '
            f'email={self.has_email_computed} '
            f'match={self.has_property_match_computed}>'
        )
