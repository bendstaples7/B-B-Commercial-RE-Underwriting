"""ContactService upsert routes LLC owners to Organizations, not Contacts."""
from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.property_contact import PropertyContact
from app.models.property_organization_link import PropertyOrganizationLink
from app.services.contact_service import ContactService


def _make_property(**kwargs) -> Lead:
    prop = Lead(property_street=kwargs.pop("property_street", "3508 N Sacramento Ave"), **kwargs)
    db.session.add(prop)
    db.session.commit()
    return prop


def test_upsert_owners_promotes_llc_to_organization(app, monkeypatch):
    """Owner 1 person + Owner 2 LLC → Contact for person, Organization for LLC."""
    calls: list[tuple] = []

    def _fake_ensure(self, lead_id, *, actor="owner_import", sync=False):
        calls.append((lead_id, actor, sync))
        return {"queued": False, "skipped": True, "reason": "patched"}

    monkeypatch.setattr(
        "app.services.entity_resolution_service.EntityResolutionService.ensure_researched",
        _fake_ensure,
    )

    with app.app_context():
        lead = _make_property(
            owner_first_name="Joseph",
            owner_last_name="Kiferbaum",
            owner_2_first_name="Kdg Avondale LLC",
            owner_2_last_name=None,
        )

        results = ContactService().upsert_owners_from_lead(lead, commit=True)

        assert len(results) == 1
        contact, link = results[0]
        assert contact.first_name == "Joseph"
        assert contact.last_name == "Kiferbaum"
        assert link.is_primary is True

        org = (
            Organization.query
            .filter(db.func.lower(Organization.name) == "kdg avondale llc")
            .first()
        )
        assert org is not None
        assert org.org_type == "llc"
        assert PropertyOrganizationLink.query.filter_by(
            property_id=lead.id, organization_id=org.id, role="owner"
        ).first() is not None

        linked = (
            db.session.query(Contact)
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == lead.id)
            .all()
        )
        assert len(linked) == 1
        assert "LLC" not in f"{linked[0].first_name} {linked[0].last_name}"
        assert calls == [(lead.id, "owner_import", False)]


def test_upsert_named_owner_fuzzy_reuses_existing(app):
    """SOS-style JOSEPH A should reuse import Joseph on the same property."""
    with app.app_context():
        lead = _make_property()
        svc = ContactService()
        first, _ = svc._upsert_named_owner(lead.id, "Joseph", "Kiferbaum", is_primary=True)
        db.session.commit()
        second, link = svc._upsert_named_owner(
            lead.id, "JOSEPH A", "KIFERBAUM", is_primary=True,
        )
        db.session.commit()
        assert second.id == first.id
        assert second.first_name == "JOSEPH A"
        assert link.is_primary is True
        assert PropertyContact.query.filter_by(property_id=lead.id).count() == 1


def test_unlink_duplicate_person_owners(app):
    with app.app_context():
        lead = _make_property()
        svc = ContactService()
        svc._upsert_named_owner(lead.id, "Joseph", "Kiferbaum", is_primary=False)
        # Force a true duplicate bypassing fuzzy match by inserting raw
        dup = Contact(first_name="JOSEPH A", last_name="KIFERBAUM", role="owner")
        db.session.add(dup)
        db.session.flush()
        db.session.add(PropertyContact(
            property_id=lead.id, contact_id=dup.id, role="owner", is_primary=True,
        ))
        db.session.commit()
        assert PropertyContact.query.filter_by(property_id=lead.id).count() == 2
        removed = svc.unlink_duplicate_person_owners(lead.id)
        db.session.commit()
        assert removed == 1
        remaining = (
            db.session.query(Contact, PropertyContact)
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == lead.id)
            .all()
        )
        assert len(remaining) == 1
        assert remaining[0][0].id == dup.id
        assert remaining[0][1].is_primary is True


def test_upsert_owners_keeps_address_like_as_contact(app):
    with app.app_context():
        lead = _make_property(
            owner_first_name="3508SACRAMENTO",
            owner_last_name="MAYNARD",
            owner_2_first_name=None,
            owner_2_last_name=None,
        )

        results = ContactService().upsert_owners_from_lead(lead, commit=True)
        assert len(results) == 1
        assert results[0][0].first_name == "3508SACRAMENTO"
        assert Organization.query.count() == 0
