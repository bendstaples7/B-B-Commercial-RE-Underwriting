"""InteractionAssociation model."""
from app import db


class InteractionAssociation(db.Model):
    """Association table linking an Interaction to a target record (lead, organization, contact)."""
    __tablename__ = 'interaction_associations'

    id = db.Column(db.Integer, primary_key=True)
    interaction_id = db.Column(db.Integer,
                               db.ForeignKey('interactions.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    target_type = db.Column(db.Enum(
        'lead', 'organization', 'contact',
        name='interaction_target_type_enum'
    ), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.Index('ix_interaction_assoc_target', 'target_type', 'target_id'),
    )

    def __repr__(self):
        return f'<InteractionAssociation interaction_id={self.interaction_id} target={self.target_type}:{self.target_id}>'
