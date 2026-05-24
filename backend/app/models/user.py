"""User model for credential-based authentication."""
from app import db
from datetime import datetime


class User(db.Model):
    """User account model. user_id is a UUID string consistent with the existing
    string user_id pattern used throughout import_jobs, marketing_lists, etc."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), unique=True, nullable=False, index=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    # email_lower stores email.lower() for case-insensitive uniqueness enforcement.
    # The email column retains the original case for display purposes.
    email_lower = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.email}>'
