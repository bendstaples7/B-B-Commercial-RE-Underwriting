"""AnalysisSession model."""
from app import db
from datetime import datetime
import enum
from sqlalchemy import JSON

class WorkflowStep(enum.Enum):
    """Workflow step enumeration."""
    PROPERTY_FACTS = 1
    COMPARABLE_SEARCH = 2
    COMPARABLE_REVIEW = 3
    WEIGHTED_SCORING = 4
    VALUATION_MODELS = 5
    REPORT_GENERATION = 6

class AnalysisSession(db.Model):
    """Analysis session model with workflow state tracking."""
    __tablename__ = 'analysis_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    current_step = db.Column(db.Enum(WorkflowStep), nullable=False, default=WorkflowStep.PROPERTY_FACTS)

    # Explicit audit trail of which steps have been fully executed.
    # Stored as a JSON array of step name strings, e.g.:
    #   ["PROPERTY_FACTS", "COMPARABLE_SEARCH", "WEIGHTED_SCORING"]
    # More reliable than inferring completion from child-record presence alone.
    completed_steps = db.Column(JSON, nullable=False, default=lambda: [])

    # Full result dict from each _execute_step call, keyed by step name, e.g.:
    #   {"COMPARABLE_SEARCH": {"comparable_count": 8, "status": "complete"}, ...}
    # Makes the workflow history self-contained in the session record.
    step_results = db.Column(JSON, nullable=False, default=lambda: {})

    # True while a background Celery task (e.g. comparable search) is running.
    # Allows the frontend polling hook to distinguish "task enqueued, not yet
    # complete" from "task complete" without inferring state from step numbers.
    loading = db.Column(db.Boolean, nullable=False, default=False)
    
    # Relationships
    subject_property = db.relationship('PropertyFacts', backref='analysis_session', uselist=False, foreign_keys='PropertyFacts.session_id')
    comparables = db.relationship('ComparableSale', backref='analysis_session', lazy='dynamic')
    ranked_comparables = db.relationship('RankedComparable', backref='analysis_session', lazy='dynamic')
    valuation_result = db.relationship('ValuationResult', backref='analysis_session', uselist=False)
    scenarios = db.relationship('Scenario', backref='analysis_session', lazy='dynamic')
    
    def __repr__(self):
        return f'<AnalysisSession {self.session_id} - Step {self.current_step.value}>'
