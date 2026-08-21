"""Tests for joint owner heal (jammed A and B → two people)."""
from app import db
from app.models.lead import Lead
from app.models.property_contact import PropertyContact
from app.models.contact import Contact
from app.services.joint_owner_heal import ensure_coowner_on_lead, heal_joint_owner_names


def test_ensure_coowner_adds_edwin(app):
    with app.app_context():
        lead = Lead(
            property_street='915 Heal Ave',
            owner_first_name='Yoko',
            owner_last_name='Miller',
        )
        db.session.add(lead)
        db.session.commit()
        changed = ensure_coowner_on_lead(lead.id, 'Edwin', 'Miller', commit=True)
        assert changed is True
        db.session.refresh(lead)
        assert (lead.owner_2_first_name or '').lower() == 'edwin'
        owners = PropertyContact.query.filter_by(property_id=lead.id, role='owner').all()
        names = {
            f'{(db.session.get(Contact, link.contact_id).first_name or "")}'.lower()
            for link in owners
        }
        assert 'edwin' in names
        assert 'yoko' in names or any('yoko' in n for n in names)


def test_heal_splits_live_jammed_name(app):
    with app.app_context():
        lead = Lead(
            property_street='100 Joint St',
            owner_first_name='TOMAS & RITA',
            owner_last_name='RYAN',
        )
        db.session.add(lead)
        db.session.commit()
        stats = heal_joint_owner_names(
            lead_ids=[lead.id],
            include_known_missing=False,
            commit=True,
        )
        assert stats['leads_split'] >= 1
        db.session.refresh(lead)
        # Primary flat stays jammed (unique-index safe); owner_2 + contacts filled.
        assert '&' in (lead.owner_first_name or '') or 'and' in (lead.owner_first_name or '').lower()
        assert (lead.owner_2_first_name or '').upper() == 'RITA'
        owners = PropertyContact.query.filter_by(property_id=lead.id, role='owner').all()
        assert len(owners) >= 2
