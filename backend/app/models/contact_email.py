"""ContactEmail model — an email address belonging to a Contact."""
from app import db


class ContactEmail(db.Model):
    """An email address associated with a Contact record."""
    __tablename__ = 'contact_emails'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(
        db.Integer,
        db.ForeignKey('contacts.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    value = db.Column(db.String(255), nullable=False)
    label = db.Column(
        db.Enum(
            'personal', 'work', 'other',
            name='email_label_enum'
        ),
        nullable=False,
        default='other'
    )

    # Functional index on lower(value) to support case-insensitive email lookups
    # used by the HubSpot matcher: filter(lower(ContactEmail.value) == email)
    __table_args__ = (
        db.Index('ix_contact_emails_value_lower',
                 db.text('lower(value)')),
    )

    def __repr__(self):
        return f'<ContactEmail {self.label}: {self.value}>'
