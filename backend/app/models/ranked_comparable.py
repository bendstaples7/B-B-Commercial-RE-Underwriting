"""RankedComparable model."""
from app import db

class RankedComparable(db.Model):
    """Ranked comparable with weighted scoring results."""
    __tablename__ = 'ranked_comparables'
    
    id = db.Column(db.Integer, primary_key=True)
    comparable_id = db.Column(db.Integer, db.ForeignKey('comparable_sales.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('analysis_sessions.id'), nullable=False, index=True)
    
    # Ranking
    rank = db.Column(db.Integer, nullable=False)
    total_score = db.Column(db.Float, nullable=False)
    
    # Score breakdown (7 weighted criteria)
    recency_score = db.Column(db.Float, nullable=False)
    proximity_score = db.Column(db.Float, nullable=False)
    units_score = db.Column(db.Float, nullable=False)
    beds_baths_score = db.Column(db.Float, nullable=False)
    sqft_score = db.Column(db.Float, nullable=False)
    construction_score = db.Column(db.Float, nullable=False)
    interior_score = db.Column(db.Float, nullable=False)
    
    # Relationship
    comparable = db.relationship('ComparableSale', backref='rankings')
    
    def __repr__(self):
        return f'<RankedComparable Rank {self.rank} - Score {self.total_score:.2f}>'
