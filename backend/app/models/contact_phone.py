"""ContactPhone model — a phone number belonging to a Contact."""
from app import db


class ContactPhone(db.Model):
    """A phone number associated with a Contact record."""
    __tablename__ = 'contact_phones'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(
        db.Integer,
        db.ForeignKey('contacts.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    value = db.Column(db.String(50), nullable=False)
    label = db.Column(
        db.Enum(
            'mobile', 'home', 'work', 'other',
            name='phone_label_enum'
        ),
        nullable=False,
        default='other'
    )

    def __repr__(self):
        return f'<ContactPhone {self.label}: {self.value}>'
