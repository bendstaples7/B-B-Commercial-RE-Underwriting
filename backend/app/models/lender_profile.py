"""LenderProfile model for reusable lender assumption profiles."""
from app import db
from datetime import datetime
from decimal import Decimal


class LenderProfile(db.Model):
    """Reusable lender record containing default terms for Scenario A or B."""
    __tablename__ = 'lender_profiles'

    id = db.Column(db.Integer, primary_key=True)
    created_by_user_id = db.Column(db.String(255), nullable=False, index=True)
    company = db.Column(db.String(200), nullable=False)
    lender_type = db.Column(db.String(30), nullable=False)
    origination_fee_rate = db.Column(db.Numeric(8, 6), nullable=False)
    prepay_penalty_description = db.Column(db.Text, nullable=True)

    # Construction_To_Perm fields (nullable when type = Self_Funded_Reno)
    ltv_total_cost = db.Column(db.Numeric(8, 6), nullable=True)
    construction_rate = db.Column(db.Numeric(8, 6), nullable=True)
    construction_io_months = db.Column(db.Integer, nullable=True)
    construction_term_months = db.Column(db.Integer, nullable=True)
    perm_rate = db.Column(db.Numeric(8, 6), nullable=True)
    perm_amort_years = db.Column(db.Integer, nullable=True)
    min_interest_or_yield = db.Column(db.Numeric(14, 2), nullable=True)

    # Self_Funded_Reno fields (nullable when type = Construction_To_Perm)
    max_purchase_ltv = db.Column(db.Numeric(8, 6), nullable=True)
    treasury_5y_rate = db.Column(db.Numeric(8, 6), nullable=True)
    spread_bps = db.Column(db.Integer, nullable=True)
    term_years = db.Column(db.Integer, nullable=True)
    amort_years = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    deal_selections = db.relationship('DealLenderSelection', backref='lender_profile', lazy='dynamic')

    __table_args__ = (
        db.CheckConstraint(
            "lender_type IN ('Construction_To_Perm', 'Self_Funded_Reno')",
            name='ck_lender_profiles_lender_type',
        ),
    )

    @property
    def all_in_rate(self):
        """Computed all-in rate for Self_Funded_Reno lenders.

        Returns treasury_5y_rate + spread_bps / 10000, or None if not applicable.
        """
        if self.lender_type != 'Self_Funded_Reno':
            return None
        if self.treasury_5y_rate is None or self.spread_bps is None:
            return None
        return self.treasury_5y_rate + Decimal(self.spread_bps) / Decimal(10000)

    def __repr__(self):
        return f'<LenderProfile {self.company} type={self.lender_type}>'
