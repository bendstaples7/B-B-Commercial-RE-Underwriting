from app.extensions import db
from datetime import datetime

class PipelineStageConfig(db.Model):
    __tablename__ = 'pipeline_stage_config'

    id = db.Column(db.Integer, primary_key=True)
    stage_name = db.Column(db.String(80), unique=True, nullable=False)
    order = db.Column(db.Integer, unique=True, nullable=False)
    weight = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<PipelineStageConfig {self.stage_name}>'
