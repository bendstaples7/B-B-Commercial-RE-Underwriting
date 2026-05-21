"""Contact model — represents a person associated with one or more properties."""
from app import db
from datetime import datetime


class Contact(db.Model):
    """A contact (owner, attorney, property manager, etc.) linked to properties via PropertyContact."""
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(128), nullable=True)
    last_name = db.Column(db.String(128), nullable=True)
    role = db.Column(
        db.Enum(
            'owner', 'property_manager', 'attorney', 'family_member', 'other',
            name='contact_role_enum'
        ),
        nullable=False,
        default='owner'
    )
    role_description = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    phones = db.relationship(
        'ContactPhone', backref='contact',
        cascade='all, delete-orphan', lazy='select'
    )
    emails = db.relationship(
        'ContactEmail', backref='contact',
        cascade='all, delete-orphan', lazy='select'
    )
    property_contacts = db.relationship(
        'PropertyContact', backref='contact',
        cascade='all, delete-orphan', lazy='dynamic'
    )

    def __repr__(self):
        return f'<Contact {self.first_name} {self.last_name}>'
