"""HubSpotSignalDictionary model for storing keyword lists used in signal detection."""
from app import db
from datetime import datetime


class HubSpotSignalDictionary(db.Model):
    """Stores keyword lists for each signal type used to detect seller motivation signals."""
    __tablename__ = 'hubspot_signal_dictionary'

    id = db.Column(db.Integer, primary_key=True)
    signal_type = db.Column(db.String(50), nullable=False, unique=True)
    keywords = db.Column(db.JSON, nullable=False)
    # keywords format: ["phrase one", "phrase two", ...]
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<HubSpotSignalDictionary {self.id} signal_type={self.signal_type!r}>'
