"""HubSpotSignal model for storing extracted signals from HubSpot engagement history."""
from app import db
from datetime import datetime


class HubSpotSignal(db.Model):
    """Stores derived signals extracted from HubSpot engagement history, linked to a Lead."""
    __tablename__ = 'hubspot_signals'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    signal_type = db.Column(db.Enum(
        'PRIOR_INTERACTION_EXISTS', 'PRIOR_RESPONSE_EXISTS', 'PRIOR_WARM_CONVERSATION',
        'ASKING_PRICE_GIVEN', 'APPOINTMENT_OCCURRED', 'OFFER_PREVIOUSLY_SENT',
        'SELLER_SAID_MAYBE_LATER', 'SELLER_NOT_INTERESTED', 'WRONG_NUMBER',
        'DO_NOT_CONTACT', 'FOLLOW_UP_OVERDUE', 'PRIOR_LEAD_SOURCE_KNOWN',
        name='hubspot_signal_type_enum'
    ), nullable=False)
    source_engagement_id = db.Column(db.String(50), nullable=True)
    extracted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    raw_evidence = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<HubSpotSignal {self.id} lead_id={self.lead_id} type={self.signal_type}>'
