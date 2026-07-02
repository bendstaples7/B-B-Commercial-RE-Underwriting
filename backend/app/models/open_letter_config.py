"""Open Letter Connect configuration — encrypted API token and mail defaults."""
from datetime import datetime

from app import db


class OpenLetterConfig(db.Model):
    """Stores OLC API credentials and default mail settings (single-row config)."""
    __tablename__ = 'open_letter_config'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    encrypted_api_token = db.Column(db.Text, nullable=False)
    use_demo_api = db.Column(db.Boolean, nullable=False, default=False)
    default_product_id = db.Column(db.Integer, nullable=True)
    default_template_id = db.Column(db.Integer, nullable=True)
    default_template_name = db.Column(db.String(255), nullable=True)
    batch_minimum = db.Column(db.Integer, nullable=False, default=50)
    allow_send_below_minimum = db.Column(db.Boolean, nullable=False, default=False)
    return_address = db.Column(db.JSON, nullable=True)
    estimated_cost_per_piece = db.Column(db.Numeric(10, 4), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f'<OpenLetterConfig user_id={self.user_id} demo={self.use_demo_api}>'
