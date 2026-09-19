"""Owner gates on tasks, interactions, and organizations."""
from datetime import datetime, timezone

from app import db
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.property_organization_link import PropertyOrganizationLink
from app.services.interaction_service import InteractionService
from app.services.task_service import TaskService
from tests.conftest import wrap_test_client_with_user


def _lead(owner: str, street: str) -> Lead:
    lead = Lead(property_street=street, owner_user_id=owner)
    db.session.add(lead)
    db.session.flush()
    return lead


class TestTaskInteractionOrgIdor:
    def test_cannot_read_or_mutate_another_users_task(self, app, client):
        with app.app_context():
            mine = _lead('test-user', '10 Mine St')
            theirs = _lead('other-user', '20 Theirs St')
            mine_task = TaskService().create({
                'title': 'Mine task',
                'associations': [{'target_type': 'lead', 'target_id': mine.id}],
            })
            their_task = TaskService().create({
                'title': 'Secret task',
                'associations': [{'target_type': 'lead', 'target_id': theirs.id}],
            })
            mine_id = mine_task.id
            their_id = their_task.id
            their_lead_id = theirs.id
            db.session.commit()

        listed = client.get('/api/tasks/')
        assert listed.status_code == 200
        ids = {row['id'] for row in listed.get_json()['tasks']}
        assert mine_id in ids
        assert their_id not in ids

        assert client.get(f'/api/tasks/{their_id}').status_code == 404
        assert client.put(
            f'/api/tasks/{their_id}',
            json={'title': 'hijack'},
        ).status_code == 404
        assert client.delete(f'/api/tasks/{their_id}').status_code == 404
        assert client.get(f'/api/tasks/{mine_id}').status_code == 200
        create_foreign = client.post(
            '/api/tasks/',
            json={
                'title': 'On their lead',
                'associations': [{'target_type': 'lead', 'target_id': their_lead_id}],
            },
        )
        assert create_foreign.status_code == 404

    def test_cannot_read_another_users_interaction_or_timeline(self, app, client):
        with app.app_context():
            mine = _lead('test-user', '11 Mine St')
            theirs = _lead('other-user', '21 Theirs St')
            mine_note = InteractionService().create({
                'body': 'mine note',
                'interaction_type': 'note',
                'occurred_at': datetime.now(timezone.utc),
                'associations': [{'target_type': 'lead', 'target_id': mine.id}],
            })
            their_note = InteractionService().create({
                'body': 'secret note',
                'interaction_type': 'note',
                'occurred_at': datetime.now(timezone.utc),
                'associations': [{'target_type': 'lead', 'target_id': theirs.id}],
            })
            mine_id = mine_note.id
            their_id = their_note.id
            their_lead_id = theirs.id
            db.session.commit()

        listed = client.get('/api/interactions/')
        assert listed.status_code == 200
        ids = {row['id'] for row in listed.get_json()['interactions']}
        assert mine_id in ids
        assert their_id not in ids

        assert client.get(f'/api/interactions/{their_id}').status_code == 404
        assert client.get(f'/api/interactions/{mine_id}').status_code == 200
        assert client.get(
            f'/api/leads/{their_lead_id}/interaction-timeline',
        ).status_code == 404

    def test_cannot_read_org_linked_only_to_another_users_lead(self, app, client):
        with app.app_context():
            mine = _lead('test-user', '12 Mine St')
            theirs = _lead('other-user', '22 Theirs St')
            mine_org = Organization(name='Mine LLC')
            their_org = Organization(name='Secret LLC')
            db.session.add_all([mine_org, their_org])
            db.session.flush()
            db.session.add_all([
                PropertyOrganizationLink(
                    property_id=mine.id, organization_id=mine_org.id, role='owner',
                ),
                PropertyOrganizationLink(
                    property_id=theirs.id, organization_id=their_org.id, role='owner',
                ),
            ])
            mine_org_id = mine_org.id
            their_org_id = their_org.id
            db.session.commit()

        listed = client.get('/api/organizations/')
        assert listed.status_code == 200
        ids = {row['id'] for row in listed.get_json()['organizations']}
        assert mine_org_id in ids
        assert their_org_id not in ids
        assert client.get(f'/api/organizations/{their_org_id}').status_code == 404
        assert client.get(f'/api/organizations/{mine_org_id}').status_code == 200
        assert client.get(f'/api/organizations/{their_org_id}/timeline').status_code == 404

    def test_cannot_attach_note_or_task_to_foreign_org_or_contact(self, app, client):
        from app.models.contact import Contact
        from app.models.interaction import Interaction
        from app.models.property_contact import PropertyContact
        from app.models.task import Task

        with app.app_context():
            mine = _lead('test-user', '13 Mine St')
            theirs = _lead('other-user', '23 Theirs St')
            mine_org = Organization(name='Mine Attach LLC')
            their_org = Organization(name='Secret Attach LLC')
            their_contact = Contact(first_name='Secret', last_name='Person')
            db.session.add_all([mine_org, their_org, their_contact])
            db.session.flush()
            db.session.add_all([
                PropertyOrganizationLink(
                    property_id=mine.id, organization_id=mine_org.id, role='owner',
                ),
                PropertyOrganizationLink(
                    property_id=theirs.id, organization_id=their_org.id, role='owner',
                ),
                PropertyContact(
                    property_id=theirs.id, contact_id=their_contact.id,
                    role='owner', is_primary=True,
                ),
            ])
            db.session.commit()
            mine_lead_id = mine.id
            mine_org_id = mine_org.id
            their_org_id = their_org.id
            their_contact_id = their_contact.id

        occurred = datetime.now(timezone.utc).isoformat()
        planted_note = client.post(
            '/api/interactions/',
            json={
                'body': 'planted on their company',
                'interaction_type': 'note',
                'occurred_at': occurred,
                'associations': [
                    {'target_type': 'organization', 'target_id': their_org_id},
                ],
            },
        )
        assert planted_note.status_code == 404
        mixed = client.post(
            '/api/interactions/',
            json={
                'body': 'own lead plus their company',
                'interaction_type': 'note',
                'occurred_at': occurred,
                'associations': [
                    {'target_type': 'lead', 'target_id': mine_lead_id},
                    {'target_type': 'organization', 'target_id': their_org_id},
                ],
            },
        )
        assert mixed.status_code == 404
        planted_person = client.post(
            '/api/interactions/',
            json={
                'body': 'planted on their person',
                'interaction_type': 'note',
                'occurred_at': occurred,
                'associations': [
                    {'target_type': 'contact', 'target_id': their_contact_id},
                ],
            },
        )
        assert planted_person.status_code == 404
        planted_task = client.post(
            '/api/tasks/',
            json={
                'title': 'On their company',
                'associations': [
                    {'target_type': 'organization', 'target_id': their_org_id},
                ],
            },
        )
        assert planted_task.status_code == 404

        other = wrap_test_client_with_user(app.test_client(), user_id='other-user')
        their_timeline = other.get(f'/api/organizations/{their_org_id}/timeline')
        assert their_timeline.status_code == 200
        titles = {
            row.get('body_or_title')
            for row in their_timeline.get_json().get('timeline', [])
        }
        assert 'planted on their company' not in titles
        assert 'own lead plus their company' not in titles
        listed_foreign = client.get(
            '/api/interactions/',
            query_string={'target_type': 'organization', 'target_id': their_org_id},
        )
        assert listed_foreign.status_code == 200
        assert listed_foreign.get_json()['interactions'] == []

        own_note = client.post(
            '/api/interactions/',
            json={
                'body': 'note on my company',
                'interaction_type': 'note',
                'occurred_at': occurred,
                'associations': [
                    {'target_type': 'organization', 'target_id': mine_org_id},
                ],
            },
        )
        assert own_note.status_code == 201
        own_id = own_note.get_json()['id']
        assert client.get(f'/api/interactions/{own_id}').status_code == 200
        mine_timeline = client.get(f'/api/organizations/{mine_org_id}/timeline')
        assert mine_timeline.status_code == 200
        mine_titles = {
            row.get('body_or_title')
            for row in mine_timeline.get_json().get('timeline', [])
        }
        assert 'note on my company' in mine_titles
        assert own_note.get_json()['body'] == 'note on my company'
        own_task = client.post(
            '/api/tasks/',
            json={
                'title': 'On my company',
                'associations': [
                    {'target_type': 'organization', 'target_id': mine_org_id},
                ],
            },
        )
        assert own_task.status_code == 201
        own_task_id = own_task.get_json()['id']
        assert client.get(f'/api/tasks/{own_task_id}').status_code == 200

        with app.app_context():
            planted_bodies = {
                row.body
                for row in Interaction.query.filter(
                    Interaction.body.in_([
                        'planted on their company',
                        'own lead plus their company',
                        'planted on their person',
                    ])
                ).all()
            }
            assert planted_bodies == set()
            assert Task.query.filter_by(title='On their company').first() is None

    def test_cannot_read_another_users_condo_group_or_linked_contact(self, app, client):
        from app.models.address_group_analysis import AddressGroupAnalysis
        from app.models.contact import Contact
        from app.models.property_contact import PropertyContact

        with app.app_context():
            theirs = _lead('other-user', '200 Theirs St')
            theirs.owner_first_name = 'Secret'
            theirs.owner_last_name = 'Owner'
            theirs.county_assessor_pin = 'PIN-SECRET'
            analysis = AddressGroupAnalysis(
                normalized_address='200 theirs st',
                property_count=1,
                pin_count=1,
                owner_count=1,
                has_unit_number=False,
                has_condo_language=False,
                missing_pin_count=0,
                missing_owner_count=0,
                condo_risk_status='likely_condo',
                building_sale_possible='no',
            )
            db.session.add(analysis)
            db.session.flush()
            theirs.condo_analysis_id = analysis.id
            their_contact = Contact(first_name='Secret', last_name='Person')
            db.session.add(their_contact)
            db.session.flush()
            db.session.add(PropertyContact(
                property_id=theirs.id,
                contact_id=their_contact.id,
                role='owner',
                is_primary=True,
            ))
            analysis_id = analysis.id
            contact_id = their_contact.id
            db.session.commit()

        listed = client.get('/api/condo-filter/results')
        assert listed.status_code == 200
        ids = {row['id'] for row in listed.get_json()['results']}
        assert analysis_id not in ids
        assert client.get(f'/api/condo-filter/results/{analysis_id}').status_code == 404
        assert client.put(
            f'/api/condo-filter/results/{analysis_id}/override',
            json={
                'condo_risk_status': 'likely_not_condo',
                'building_sale_possible': 'yes',
                'reason': 'hijack',
            },
        ).status_code == 404

        search = client.get('/api/contacts/search', query_string={'q': 'Secret'})
        assert search.status_code == 200
        search_ids = {row['id'] for row in search.get_json()['results']}
        assert contact_id not in search_ids
        assert client.get(f'/api/contacts/{contact_id}').status_code == 404

    def test_cannot_list_foreign_marketing_list_or_confirm_foreign_hubspot_lead(self, app, client):
        from app.models.hubspot_match import HubSpotMatch
        from app.models.marketing import MarketingList

        with app.app_context():
            theirs = _lead('other-user', '300 Theirs St')
            their_list = MarketingList(name='Secret List', user_id='other-user')
            mine_list = MarketingList(name='Mine List', user_id='test-user')
            match = HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='hs-idor-1',
                internal_record_type='lead',
                internal_record_id=theirs.id,
                confidence='MEDIUM',
                status='pending',
            )
            db.session.add_all([their_list, mine_list, match])
            db.session.commit()
            their_list_id = their_list.id
            mine_list_id = mine_list.id
            match_id = match.id
            their_lead_id = theirs.id

        listed = client.get('/api/leads/marketing/lists')
        assert listed.status_code == 200
        ids = {row['id'] for row in listed.get_json()['lists']}
        assert mine_list_id in ids
        assert their_list_id not in ids
        assert client.post(
            f'/api/hubspot/review-queue/{match_id}/confirm',
            json={},
        ).status_code == 404
        assert client.post(
            f'/api/hubspot/review-queue/{match_id}/confirm',
            json={'internal_record_id': their_lead_id},
        ).status_code == 404
        # Unique-PIN pending often points at another owner's lead. Reviewers
        # must still reject or mark new-record without confirming onto it.
        created = client.post(
            f'/api/hubspot/review-queue/{match_id}/new-record',
            json={},
        )
        assert created.status_code == 200
        created_body = created.get_json()['match']
        assert created_body['internal_record_id'] is None
        assert created_body['status'] == 'confirmed'

        with app.app_context():
            leftover = HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='hs-idor-reject',
                internal_record_type='lead',
                internal_record_id=their_lead_id,
                confidence='HIGH',
                status='pending',
            )
            db.session.add(leftover)
            db.session.commit()
            leftover_id = leftover.id

        rejected = client.post(
            f'/api/hubspot/review-queue/{leftover_id}/reject',
            json={},
        )
        assert rejected.status_code == 200
        rejected_body = rejected.get_json()['match']
        assert rejected_body['status'] == 'rejected'
        assert rejected_body['internal_record_id'] is None

    def test_cannot_confirm_hubspot_match_pointing_at_foreign_contact(self, app, client):
        from app.models.contact import Contact
        from app.models.hubspot_match import HubSpotMatch
        from app.models.property_contact import PropertyContact

        with app.app_context():
            mine = _lead('test-user', '310 Mine St')
            theirs = _lead('other-user', '311 Theirs St')
            their_contact = Contact(first_name='Secret', last_name='Owner')
            db.session.add(their_contact)
            db.session.flush()
            db.session.add(PropertyContact(
                property_id=theirs.id,
                contact_id=their_contact.id,
                role='owner',
                is_primary=True,
            ))
            match = HubSpotMatch(
                hubspot_record_type='contact',
                hubspot_id='hs-contact-idor',
                internal_record_type='contact',
                internal_record_id=their_contact.id,
                confidence='HIGH',
                status='pending',
            )
            db.session.add(match)
            db.session.commit()
            match_id = match.id
            contact_id = their_contact.id

        assert client.post(
            f'/api/hubspot/review-queue/{match_id}/confirm',
            json={},
        ).status_code == 404
        assert client.post(
            f'/api/hubspot/review-queue/{match_id}/confirm',
            json={'internal_record_id': contact_id},
        ).status_code == 404

    def test_kanban_cannot_move_foreign_lead_and_writes_timeline_for_own(self, app, client):
        from app.models.lead_timeline_entry import LeadTimelineEntry

        with app.app_context():
            mine = _lead('test-user', '40 Mine St')
            theirs = _lead('other-user', '41 Theirs St')
            mine.lead_status = 'mailing_no_contact_made'
            theirs.lead_status = 'mailing_no_contact_made'
            db.session.commit()
            mine_id = mine.id
            their_id = theirs.id

        assert client.patch(
            f'/api/kanban/leads/{their_id}/move',
            json={'target_action': 'deal_won'},
        ).status_code == 400
        moved = client.patch(
            f'/api/kanban/leads/{mine_id}/move',
            json={'target_action': 'deal_won'},
        )
        assert moved.status_code == 200
        assert moved.get_json()['lead']['lead_status'] == 'deal_won'
        with app.app_context():
            entries = LeadTimelineEntry.query.filter_by(
                lead_id=mine_id, event_type='status_changed',
            ).all()
            assert entries
            their_entries = LeadTimelineEntry.query.filter_by(
                lead_id=their_id, event_type='status_changed',
            ).all()
            assert not their_entries

    def test_cannot_link_or_delete_foreign_contact(self, app, client):
        from app.models.contact import Contact
        from app.models.property_contact import PropertyContact

        with app.app_context():
            mine = _lead('test-user', '50 Mine St')
            theirs = _lead('other-user', '51 Theirs St')
            their_contact = Contact(first_name='Stolen', last_name='Person')
            db.session.add(their_contact)
            db.session.flush()
            db.session.add(PropertyContact(
                property_id=theirs.id,
                contact_id=their_contact.id,
                role='owner',
                is_primary=True,
            ))
            db.session.commit()
            mine_id = mine.id
            contact_id = their_contact.id

        assert client.post(
            f'/api/properties/{mine_id}/contacts',
            json={'contact_id': contact_id, 'role': 'owner', 'is_primary': True},
        ).status_code == 404
        assert client.get(f'/api/contacts/{contact_id}').status_code == 404
        assert client.put(
            f'/api/contacts/{contact_id}',
            json={'notes': 'hijack'},
        ).status_code == 404
        assert client.delete(f'/api/contacts/{contact_id}').status_code == 404

    def test_cannot_rewrite_contact_shared_with_foreign_lead(self, app, client):
        from app.models.contact import Contact
        from app.models.property_contact import PropertyContact

        with app.app_context():
            mine = _lead('test-user', '52 Mine St')
            theirs = _lead('other-user', '53 Theirs St')
            shared = Contact(first_name='Shared', last_name='Owner')
            db.session.add(shared)
            db.session.flush()
            db.session.add_all([
                PropertyContact(
                    property_id=mine.id, contact_id=shared.id,
                    role='owner', is_primary=True,
                ),
                PropertyContact(
                    property_id=theirs.id, contact_id=shared.id,
                    role='owner', is_primary=True,
                ),
            ])
            db.session.commit()
            contact_id = shared.id

        assert client.get(f'/api/contacts/{contact_id}').status_code == 200
        assert client.put(
            f'/api/contacts/{contact_id}',
            json={'notes': 'rewrite shared'},
        ).status_code == 404
        assert client.delete(f'/api/contacts/{contact_id}').status_code == 404

    def test_unlinked_contact_is_only_visible_to_creator(self, app, client):
        from app.models.contact import Contact

        created = client.post(
            '/api/contacts/',
            json={'first_name': 'Greg', 'last_name': 'Shek', 'phones': [{'value': '3125550100', 'label': 'mobile'}]},
        )
        assert created.status_code == 201
        contact_id = created.get_json()['id']
        assert client.get(f'/api/contacts/{contact_id}').status_code == 200

        other = wrap_test_client_with_user(app.test_client(), user_id='other-user')
        assert other.get(f'/api/contacts/{contact_id}').status_code == 404
        assert other.put(
            f'/api/contacts/{contact_id}',
            json={'notes': 'steal'},
        ).status_code == 404
        assert other.delete(f'/api/contacts/{contact_id}').status_code == 404
        other_search = other.get('/api/contacts/search', query_string={'q': 'Greg'})
        assert other_search.status_code == 200
        assert contact_id not in {row['id'] for row in other_search.get_json()['results']}
        mine_search = client.get('/api/contacts/search', query_string={'q': 'Greg'})
        assert mine_search.status_code == 200
        assert contact_id in {row['id'] for row in mine_search.get_json()['results']}

        with app.app_context():
            orphan = Contact(first_name='Legacy', last_name='Orphan')
            db.session.add(orphan)
            db.session.commit()
            orphan_id = orphan.id
        assert client.get(f'/api/contacts/{orphan_id}').status_code == 404

    def test_cannot_unlink_foreign_org_property_link(self, app, client):
        with app.app_context():
            mine = _lead('test-user', '54 Mine St')
            theirs = _lead('other-user', '55 Theirs St')
            mine_org = Organization(name='Mine Unlink LLC')
            their_org = Organization(name='Their Unlink LLC')
            db.session.add_all([mine_org, their_org])
            db.session.flush()
            mine_link = PropertyOrganizationLink(
                property_id=mine.id, organization_id=mine_org.id, role='owner',
            )
            their_link = PropertyOrganizationLink(
                property_id=theirs.id, organization_id=their_org.id, role='owner',
            )
            db.session.add_all([mine_link, their_link])
            db.session.commit()
            mine_org_id = mine_org.id
            their_link_id = their_link.id

        assert client.delete(
            f'/api/organizations/{mine_org_id}/links/properties/{their_link_id}',
        ).status_code == 404
        with app.app_context():
            assert db.session.get(PropertyOrganizationLink, their_link_id) is not None

    def test_cannot_rewrite_or_deactivate_org_shared_with_foreign_lead(self, app, client):
        with app.app_context():
            mine = _lead('test-user', '58 Mine St')
            theirs = _lead('other-user', '59 Theirs St')
            org = Organization(name='Shared Building LLC', status='active')
            db.session.add(org)
            db.session.flush()
            db.session.add_all([
                PropertyOrganizationLink(
                    property_id=mine.id, organization_id=org.id, role='owner',
                ),
                PropertyOrganizationLink(
                    property_id=theirs.id, organization_id=org.id, role='owner',
                ),
            ])
            db.session.commit()
            org_id = org.id

        assert client.get(f'/api/organizations/{org_id}').status_code == 200
        assert client.put(
            f'/api/organizations/{org_id}',
            json={'name': 'Stolen LLC'},
        ).status_code == 404
        assert client.delete(f'/api/organizations/{org_id}').status_code == 404
        with app.app_context():
            refreshed = db.session.get(Organization, org_id)
            assert refreshed.name == 'Shared Building LLC'
            assert refreshed.status == 'active'

    def test_building_ownership_hides_foreign_units_and_blocks_shared_override(
        self, app, client,
    ):
        from app.models.address_group_analysis import AddressGroupAnalysis

        with app.app_context():
            analysis = AddressGroupAnalysis(
                normalized_address='60 shared building st',
                property_count=2,
                pin_count=2,
                owner_count=2,
                condo_risk_status='needs_review',
                building_sale_possible='unknown',
            )
            db.session.add(analysis)
            db.session.flush()
            mine = _lead('test-user', '60 Shared Building St Unit 1')
            theirs = _lead('other-user', '60 Shared Building St Unit 2')
            mine.owner_first_name = 'MineOwner'
            theirs.owner_first_name = 'TheirOwner'
            mine.county_assessor_pin = 'PIN-MINE'
            theirs.county_assessor_pin = 'PIN-THEIRS'
            mine.condo_analysis_id = analysis.id
            theirs.condo_analysis_id = analysis.id
            mine.condo_risk_status = 'needs_review'
            theirs.condo_risk_status = 'needs_review'
            mine.building_sale_possible = 'unknown'
            theirs.building_sale_possible = 'unknown'
            db.session.commit()
            mine_id = mine.id
            their_id = theirs.id

        shown = client.get(f'/api/leads/{mine_id}/building-ownership')
        assert shown.status_code == 200
        payload = shown.get_json()
        linked_ids = {row['id'] for row in (payload.get('leads') or [])}
        assert mine_id in linked_ids
        assert their_id not in linked_ids
        names = {row.get('owner_first_name') for row in (payload.get('leads') or [])}
        assert 'TheirOwner' not in names
        pins = {row.get('county_assessor_pin') for row in (payload.get('leads') or [])}
        assert 'PIN-THEIRS' not in pins

        blocked = client.put(
            f'/api/leads/{mine_id}/building-ownership/override',
            json={
                'condo_risk_status': 'likely_not_condo',
                'building_sale_possible': 'yes',
                'reason': 'hijack shared building',
            },
        )
        assert blocked.status_code == 404
        with app.app_context():
            theirs = db.session.get(Lead, their_id)
            assert theirs.condo_risk_status == 'needs_review'
            assert theirs.building_sale_possible == 'unknown'

    def test_analyze_lead_does_not_overwrite_shared_building_analysis(self, app):
        from unittest.mock import patch

        from app.models.address_group_analysis import AddressGroupAnalysis
        from app.services.building_ownership_service import BuildingOwnershipService
        from app.services.helpers.address_normalizer import normalize_address
        from app.services.helpers.classification_engine import ClassificationResult

        with app.app_context():
            street = '61 Shared Analyze St Unit 1'
            analysis = AddressGroupAnalysis(
                normalized_address=normalize_address(street),
                property_count=2,
                pin_count=2,
                owner_count=2,
                condo_risk_status='likely_condo',
                building_sale_possible='no',
                analysis_details={'reason': 'theirs'},
            )
            db.session.add(analysis)
            db.session.flush()
            mine = _lead('test-user', street)
            theirs = _lead('other-user', '61 Shared Analyze St Unit 2')
            mine.condo_analysis_id = analysis.id
            theirs.condo_analysis_id = analysis.id
            mine.condo_risk_status = 'likely_condo'
            theirs.condo_risk_status = 'likely_condo'
            mine.building_sale_possible = 'no'
            theirs.building_sale_possible = 'no'
            db.session.commit()
            mine_id = mine.id
            their_id = theirs.id
            analysis_id = analysis.id

            hijack = ClassificationResult(
                condo_risk_status='likely_not_condo',
                building_sale_possible='yes',
                triggered_rules=['hijack'],
                reason='attacker',
                confidence='high',
            )
            with patch(
                'app.services.building_ownership_backfill.lead_needs_building_ownership_analysis',
                return_value=True,
            ), patch.object(
                BuildingOwnershipService, '_collect_assessor_pins', return_value=[],
            ), patch(
                'app.services.building_ownership_service.classify', return_value=hijack,
            ), patch(
                'app.services.building_ownership_service.refresh_lead_scoring',
            ):
                BuildingOwnershipService().analyze_lead(mine_id, force=True)

            analysis = db.session.get(AddressGroupAnalysis, analysis_id)
            theirs = db.session.get(Lead, their_id)
            assert analysis.condo_risk_status == 'likely_condo'
            assert analysis.building_sale_possible == 'no'
            assert analysis.analysis_details == {'reason': 'theirs'}
            assert theirs.condo_risk_status == 'likely_condo'
            assert theirs.building_sale_possible == 'no'

    def test_cannot_access_deal_via_foreign_lead_link(self, app):
        from decimal import Decimal

        from app.exceptions import ValidationException
        from app.models.deal import Deal
        from app.models.lead_deal_link import LeadDealLink
        from app.services.multifamily.deal_service import DealService

        with app.app_context():
            mine = _lead('test-user', '56 Mine St')
            theirs = _lead('other-user', '57 Theirs St')
            their_deal = Deal(
                created_by_user_id='other-user',
                property_address='57 Theirs St',
                unit_count=5,
                purchase_price=Decimal('100000.00'),
                closing_costs=Decimal('0'),
                status='draft',
            )
            mine_deal = Deal(
                created_by_user_id='test-user',
                property_address='56 Mine St',
                unit_count=5,
                purchase_price=Decimal('100000.00'),
                closing_costs=Decimal('0'),
                status='draft',
            )
            db.session.add_all([their_deal, mine_deal])
            db.session.flush()
            db.session.add(LeadDealLink(lead_id=theirs.id, deal_id=their_deal.id))
            db.session.commit()
            svc = DealService()
            assert svc.user_has_access('test-user', their_deal.id) is False
            try:
                svc.link_to_lead('test-user', mine_deal.id, theirs.id)
                assert False, 'link_to_lead should reject a foreign lead'
            except ValidationException:
                pass
            svc.link_to_lead('test-user', mine_deal.id, mine.id)
            assert svc.user_has_access('test-user', mine_deal.id) is True

    def test_cannot_set_hubspot_company_id_via_org_api(self, app, client):
        created = client.post(
            '/api/organizations/',
            json={'name': 'API Org LLC', 'hubspot_company_id': 'stolen-hs-id'},
        )
        assert created.status_code == 201
        body = created.get_json()
        assert body.get('hubspot_company_id') in (None, '')
        org_id = body['id']

        with app.app_context():
            mine = _lead('test-user', '61 Mine St')
            db.session.add(PropertyOrganizationLink(
                property_id=mine.id, organization_id=org_id, role='owner',
            ))
            db.session.commit()

        updated = client.put(
            f'/api/organizations/{org_id}',
            json={'hubspot_company_id': 'stolen-hs-id'},
        )
        assert updated.status_code == 200
        assert updated.get_json().get('hubspot_company_id') in (None, '')
        with app.app_context():
            assert db.session.get(Organization, org_id).hubspot_company_id is None

    def test_cannot_set_hubspot_identity_via_task_or_interaction_api(self, app, client):
        with app.app_context():
            mine = _lead('test-user', '62 Mine St')
            lead_id = mine.id
            db.session.commit()

        occurred = datetime.now(timezone.utc).isoformat()
        note = client.post(
            '/api/interactions/',
            json={
                'body': 'manual note',
                'interaction_type': 'note',
                'occurred_at': occurred,
                'source': 'hubspot_import',
                'hubspot_engagement_id': 'stolen-eng',
                'raw_payload': {'secret': True},
                'is_orphaned': True,
                'associations': [{'target_type': 'lead', 'target_id': lead_id}],
            },
        )
        assert note.status_code == 201
        note_body = note.get_json()
        assert note_body.get('hubspot_engagement_id') in (None, '')
        assert note_body.get('source') == 'manual'
        assert note_body.get('is_orphaned') in (False, None)

        task = client.post(
            '/api/tasks/',
            json={
                'title': 'manual task',
                'source': 'hubspot_import',
                'hubspot_task_id': 'stolen-task',
                'raw_payload': {'secret': True},
                'associations': [{'target_type': 'lead', 'target_id': lead_id}],
            },
        )
        assert task.status_code == 201
        task_body = task.get_json()
        assert task_body.get('hubspot_task_id') in (None, '')
        assert task_body.get('source') == 'manual'
        task_id = task_body['id']
        hijack = client.put(
            f'/api/tasks/{task_id}',
            json={'hubspot_task_id': 'stolen-task'},
        )
        assert hijack.status_code == 200
        assert hijack.get_json().get('hubspot_task_id') in (None, '')


