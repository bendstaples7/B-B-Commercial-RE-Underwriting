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
    value = db.Column(db.String(255), nullable=False, index=True)
    label = db.Column(
        db.Enum(
            'personal', 'work', 'other',
            name='email_label_enum'
        ),
        nullable=False,
        default='other'
    )

    def __repr__(self):
        return f'<ContactEmail {self.label}: {self.value}>'
