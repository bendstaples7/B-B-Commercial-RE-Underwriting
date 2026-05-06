"""Deal model for multifamily underwriting."""
from app import db
from datetime import datetime


class Deal(db.Model):
    """Multifamily underwriting Deal record for a single property."""
    __tablename__ = 'deals'

    id = db.Column(db.Integer, primary_key=True)
    created_by_user_id = db.Column(db.String(255), nullable=False, index=True)

    # Property details
    property_address = db.Column(db.String(500), nullable=False, index=True)
    property_city = db.Column(db.String(100), nullable=True)
    property_state = db.Column(db.String(50), nullable=True)
    property_zip = db.Column(db.String(20), nullable=True)

    # Deal fundamentals
    unit_count = db.Column(db.Integer, nullable=False)
    purchase_price = db.Column(db.Numeric(14, 2), nullable=False)
    closing_costs = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    close_date = db.Column(db.Date, nullable=True)

    # Assumptions
    vacancy_rate = db.Column(db.Numeric(8, 6), nullable=False, default=0.05)
    other_income_monthly = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    management_fee_rate = db.Column(db.Numeric(8, 6), nullable=False, default=0.08)
    reserve_per_unit_per_year = db.Column(db.Numeric(14, 2), nullable=False, default=250)

    # Operating expenses (annual)
    property_taxes_annual = db.Column(db.Numeric(14, 2), nullable=True)
    insurance_annual = db.Column(db.Numeric(14, 2), nullable=True)
    utilities_annual = db.Column(db.Numeric(14, 2), nullable=True)
    repairs_and_maintenance_annual = db.Column(db.Numeric(14, 2), nullable=True)
    admin_and_marketing_annual = db.Column(db.Numeric(14, 2), nullable=True)
    payroll_annual = db.Column(db.Numeric(14, 2), nullable=True)
    other_opex_annual = db.Column(db.Numeric(14, 2), nullable=True)

    # Funding / valuation
    interest_reserve_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    custom_cap_rate = db.Column(db.Numeric(8, 6), nullable=True)

    # Status
    status = db.Column(db.String(50), nullable=False, default='draft')

    # Timestamps and soft-delete
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    units = db.relationship('Unit', backref='deal', lazy='dynamic', cascade='all, delete-orphan')
    rent_comps = db.relationship('RentComp', backref='deal', lazy='dynamic', cascade='all, delete-orphan')
    sale_comps = db.relationship('SaleComp', backref='deal', lazy='dynamic', cascade='all, delete-orphan')
    market_rent_assumptions = db.relationship('MarketRentAssumption', backref='deal', lazy='dynamic', cascade='all, delete-orphan')
    funding_sources = db.relationship('FundingSource', backref='deal', lazy='dynamic', cascade='all, delete-orphan')
    lender_selections = db.relationship('DealLenderSelection', backref='deal', lazy='dynamic', cascade='all, delete-orphan')
    pro_forma_result = db.relationship('ProFormaResult', backref='deal', uselist=False, cascade='all, delete-orphan')
    lead_links = db.relationship('LeadDealLink', backref='deal', lazy='dynamic', cascade='all, delete-orphan')
    audit_trail = db.relationship('DealAuditTrail', backref='deal', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.CheckConstraint('unit_count >= 5', name='ck_deals_unit_count_min'),
        db.CheckConstraint('purchase_price > 0', name='ck_deals_purchase_price_positive'),
    )

    def __repr__(self):
        return f'<Deal {self.id} {self.property_address}>'
