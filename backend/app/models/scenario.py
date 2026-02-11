"""Scenario models for investment analysis."""
from app import db
from sqlalchemy import JSON
import enum

class ScenarioType(enum.Enum):
    """Scenario type enumeration."""
    WHOLESALE = 'wholesale'
    FIX_FLIP = 'fix_flip'
    BUY_HOLD = 'buy_hold'

class Scenario(db.Model):
    """Base scenario model for investment strategies."""
    __tablename__ = 'scenarios'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('analysis_sessions.id'), nullable=False, index=True)
    scenario_type = db.Column(db.Enum(ScenarioType), nullable=False)
    purchase_price = db.Column(db.Float, nullable=False)
    
    # Summary data (stored as JSON for flexibility)
    summary = db.Column(JSON, nullable=False)
    
    # Polymorphic discrimination
    type = db.Column(db.String(50))
    
    __mapper_args__ = {
        'polymorphic_identity': 'scenario',
        'polymorphic_on': type
    }
    
    def __repr__(self):
        return f'<Scenario {self.scenario_type.value} - ${self.purchase_price:.0f}>'

class WholesaleScenario(Scenario):
    """Wholesale investment scenario."""
    __tablename__ = 'wholesale_scenarios'
    
    id = db.Column(db.Integer, db.ForeignKey('scenarios.id'), primary_key=True)
    
    # Wholesale-specific fields
    mao = db.Column(db.Float, nullable=False)  # Maximum Allowable Offer
    contract_price = db.Column(db.Float, nullable=False)
    assignment_fee_low = db.Column(db.Float, nullable=False)
    assignment_fee_high = db.Column(db.Float, nullable=False)
    estimated_repairs = db.Column(db.Float, nullable=False)
    
    __mapper_args__ = {
        'polymorphic_identity': 'wholesale',
    }
    
    def __repr__(self):
        return f'<WholesaleScenario MAO: ${self.mao:.0f}>'

class FixFlipScenario(Scenario):
    """Fix and flip investment scenario."""
    __tablename__ = 'fix_flip_scenarios'
    
    id = db.Column(db.Integer, db.ForeignKey('scenarios.id'), primary_key=True)
    
    # Fix and flip specific fields
    acquisition_cost = db.Column(db.Float, nullable=False)
    renovation_cost = db.Column(db.Float, nullable=False)
    holding_costs = db.Column(db.Float, nullable=False)
    financing_costs = db.Column(db.Float, nullable=False)
    closing_costs = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    exit_value = db.Column(db.Float, nullable=False)
    net_profit = db.Column(db.Float, nullable=False)
    roi = db.Column(db.Float, nullable=False)
    months_to_flip = db.Column(db.Integer, nullable=False)
    
    __mapper_args__ = {
        'polymorphic_identity': 'fix_flip',
    }
    
    def __repr__(self):
        return f'<FixFlipScenario Profit: ${self.net_profit:.0f} ROI: {self.roi:.1f}%>'

class BuyHoldScenario(Scenario):
    """Buy and hold investment scenario."""
    __tablename__ = 'buy_hold_scenarios'
    
    id = db.Column(db.Integer, db.ForeignKey('scenarios.id'), primary_key=True)
    
    # Buy and hold specific fields
    market_rent = db.Column(db.Float, nullable=False)
    
    # Capital structures and price points (stored as JSON)
    capital_structures = db.Column(JSON, nullable=False)
    price_points = db.Column(JSON, nullable=False)
    
    __mapper_args__ = {
        'polymorphic_identity': 'buy_hold',
    }
    
    def __repr__(self):
        return f'<BuyHoldScenario Rent: ${self.market_rent:.0f}/mo>'
