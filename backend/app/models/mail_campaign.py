"""Mail campaign — one submitted Open Letter Connect order."""
from datetime import datetime

from app import db


class MailCampaign(db.Model):
    """Tracks a batch mail send placed through Open Letter Connect."""
    __tablename__ = 'mail_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    olc_order_id = db.Column(db.String(50), nullable=True, index=True)
    status = db.Column(
        db.Enum(
            'pending', 'submitted', 'processing', 'mailed', 'failed', 'cancelled',
            name='mail_campaign_status_enum',
        ),
        nullable=False,
        default='pending',
        index=True,
    )
    lead_count = db.Column(db.Integer, nullable=False, default=0)
    # Submit reconciliation — staged vs POSTed vs dropped at local validation
    staged_count = db.Column(db.Integer, nullable=True)
    submitted_count = db.Column(db.Integer, nullable=True)
    invalid_at_submit_count = db.Column(db.Integer, nullable=True)
    submit_drop_summary = db.Column(db.JSON, nullable=True)
    address_feedback_summary = db.Column(db.JSON, nullable=True)
    # Lead ids present on the OLC order after analytics sync (gap drill-down).
    olc_tracked_lead_ids = db.Column(db.JSON, nullable=True)
    # Lead ids submitted locally but absent from OLC (persists after requeue).
    olc_omitted_lead_ids = db.Column(db.JSON, nullable=True)
    cost = db.Column(db.Numeric(12, 4), nullable=True)
    cost_per_piece = db.Column(db.Numeric(10, 4), nullable=True)
    product_id = db.Column(db.Integer, nullable=True)
    template_id = db.Column(db.Integer, nullable=True)
    template_name = db.Column(db.String(255), nullable=True)
    creative = db.Column(db.JSON, nullable=True)
    delivery_stats = db.Column(db.JSON, nullable=True)
    scan_stats = db.Column(db.JSON, nullable=True)
    response_count = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.String(100), nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    analytics_synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f'<MailCampaign id={self.id} olc_order_id={self.olc_order_id} status={self.status}>'
