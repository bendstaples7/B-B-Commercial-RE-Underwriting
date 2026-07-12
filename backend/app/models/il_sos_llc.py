"""Illinois SOS LLC bulk dump models (Transparency Act free data)."""
from datetime import datetime

from app import db
from app.models.json_types import JSONBCompatible


class IlSosLlcEntity(db.Model):
    """One Illinois LLC from the SOS name + master dump."""

    __tablename__ = 'il_sos_llc_entities'

    file_number = db.Column(db.String(8), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    normalized_name = db.Column(db.String(200), nullable=False, index=True)
    status_code = db.Column(db.String(2), nullable=True)
    management_type = db.Column(db.String(1), nullable=True)
    juris_organized = db.Column(db.String(2), nullable=True)
    imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    managers = db.relationship(
        'IlSosLlcManager',
        back_populates='entity',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )
    agent = db.relationship(
        'IlSosLlcAgent',
        back_populates='entity',
        uselist=False,
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<IlSosLlcEntity {self.file_number} {self.name!r}>'


class IlSosLlcManager(db.Model):
    """Manager/member row from llcallmgr."""

    __tablename__ = 'il_sos_llc_managers'

    id = db.Column(db.Integer, primary_key=True)
    file_number = db.Column(
        db.String(8),
        db.ForeignKey('il_sos_llc_entities.file_number', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    mm_name = db.Column(db.String(120), nullable=False)
    mm_street = db.Column(db.String(60), nullable=True)
    mm_city = db.Column(db.String(40), nullable=True)
    mm_juris = db.Column(db.String(2), nullable=True)
    mm_zip = db.Column(db.String(10), nullable=True)
    mm_file_date = db.Column(db.String(20), nullable=True)
    mm_type_code = db.Column(db.String(1), nullable=True)
    is_company = db.Column(db.Boolean, nullable=False, default=False)

    entity = db.relationship('IlSosLlcEntity', back_populates='managers')

    def __repr__(self):
        return f'<IlSosLlcManager {self.file_number} {self.mm_name!r}>'


class IlSosLlcAgent(db.Model):
    """Registered agent row from llcallagt."""

    __tablename__ = 'il_sos_llc_agents'

    file_number = db.Column(
        db.String(8),
        db.ForeignKey('il_sos_llc_entities.file_number', ondelete='CASCADE'),
        primary_key=True,
    )
    agent_name = db.Column(db.String(120), nullable=False)
    agent_street = db.Column(db.String(60), nullable=True)
    agent_city = db.Column(db.String(40), nullable=True)
    agent_zip = db.Column(db.String(10), nullable=True)
    agent_code = db.Column(db.String(1), nullable=True)

    entity = db.relationship('IlSosLlcEntity', back_populates='agent')

    def __repr__(self):
        return f'<IlSosLlcAgent {self.file_number} {self.agent_name!r}>'


class IlSosImportRun(db.Model):
    """Audit row for each bulk import attempt."""

    __tablename__ = 'il_sos_import_runs'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    row_counts = db.Column(JSONBCompatible, nullable=True)
    error = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<IlSosImportRun id={self.id} status={self.status}>'
