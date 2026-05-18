# Implementation Plan: Property Contact Model

## Overview

Three coordinated changes: (1) rename Lead → Property in API, types, and UI; (2) introduce a Contact model with structured phones/emails and a many-to-many Property ↔ Contact relationship; (3) migrate existing flat contact columns to the new Contact model.

Execution order: database/models → backend services → backend API → frontend types → frontend UI → tests.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "title": "Database & Model Layer",
      "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5"]
    },
    {
      "wave": 2,
      "title": "Alembic Migration",
      "tasks": ["1.6"]
    },
    {
      "wave": 3,
      "title": "Backend Service Layer",
      "tasks": ["2.1", "2.3"]
    },
    {
      "wave": 4,
      "title": "HubSpot Matcher Update",
      "tasks": ["2.2"]
    },
    {
      "wave": 5,
      "title": "Backend API Layer",
      "tasks": ["3.1", "3.2", "3.3"]
    },
    {
      "wave": 6,
      "title": "Frontend Types",
      "tasks": ["4.1", "4.2", "4.3"]
    },
    {
      "wave": 7,
      "title": "Frontend UI Components",
      "tasks": ["5.1", "5.2", "5.3", "5.4"]
    },
    {
      "wave": 8,
      "title": "Tests",
      "tasks": ["6.1", "6.2", "6.3", "6.4", "6.4.1", "6.4.2", "6.4.3", "6.4.4", "6.4.5", "6.4.6", "6.4.7", "6.4.8", "6.4.9", "6.4.10", "6.4.11", "6.4.12", "6.4.13", "6.5", "6.6", "6.7"]
    }
  ]
}
```

## Tasks

### Phase 1: Database & Model Layer

- [x] 1.1 Create SQLAlchemy model `Contact` in `backend/app/models/contact.py`
  - Class `Contact` with `__tablename__ = 'contacts'`
  - Columns: `id`, `first_name` (nullable String 128), `last_name` (nullable String 128), `role` (Enum: owner/property_manager/attorney/family_member/other, default owner), `role_description` (nullable String 255), `notes` (nullable Text), `created_at`, `updated_at`
  - Relationships: `phones` (ContactPhone, cascade all/delete-orphan), `emails` (ContactEmail, cascade all/delete-orphan), `property_contacts` (PropertyContact, cascade all/delete-orphan, lazy=dynamic)
  - Re-export from `backend/app/models/__init__.py`

- [x] 1.2 Create SQLAlchemy model `ContactPhone` in `backend/app/models/contact_phone.py`
  - Class `ContactPhone` with `__tablename__ = 'contact_phones'`
  - Columns: `id`, `contact_id` (FK → contacts.id, CASCADE DELETE, indexed), `value` (String 50, not null), `label` (Enum: mobile/home/work/other, default other)
  - Re-export from `backend/app/models/__init__.py`

- [x] 1.3 Create SQLAlchemy model `ContactEmail` in `backend/app/models/contact_email.py`
  - Class `ContactEmail` with `__tablename__ = 'contact_emails'`
  - Columns: `id`, `contact_id` (FK → contacts.id, CASCADE DELETE, indexed), `value` (String 255, not null, indexed), `label` (Enum: personal/work/other, default other)
  - Re-export from `backend/app/models/__init__.py`

- [x] 1.4 Create SQLAlchemy model `PropertyContact` in `backend/app/models/property_contact.py`
  - Class `PropertyContact` with `__tablename__ = 'property_contacts'`
  - Columns: `id`, `property_id` (FK → leads.id, CASCADE DELETE, indexed), `contact_id` (FK → contacts.id, CASCADE DELETE, indexed), `role` (Enum: owner/property_manager/attorney/family_member/other, default owner), `is_primary` (Boolean, not null, default False)
  - UniqueConstraint on `(property_id, contact_id)` named `uq_property_contact`
  - Re-export from `backend/app/models/__init__.py`

- [x] 1.5 Rename `Lead` model class to `Property` in `backend/app/models/lead.py`
  - Rename class from `Lead` to `Property`; keep `__tablename__ = 'leads'` unchanged
  - Add relationship: `property_contacts` (PropertyContact, backref='property', cascade all/delete-orphan, lazy=dynamic)
  - Update re-export in `backend/app/models/__init__.py` to export `Property` (keep `Lead` as an alias for backward compatibility during transition)

- [x] 1.6 Write Alembic migration `backend/alembic_migrations/versions/XXXX_add_contact_model.py`
  - Upgrade: create tables `contacts`, `contact_phones`, `contact_emails`, `property_contacts` with all columns, indexes, foreign keys, and unique constraints as defined in the models
  - Data migration (upgrade only): for each row in `leads`, if `owner_first_name` or `owner_last_name` is non-null and no `PropertyContact` already exists for that `property_id` (idempotency guard): create `Contact` (role=owner), migrate `phone_1`–`phone_7` as `ContactPhone` records (label=other, skip null/empty), migrate `email_1`–`email_5` as `ContactEmail` records (label=other, skip null/empty), create `PropertyContact` with `is_primary=True`; if `owner_2_first_name` or `owner_2_last_name` is non-null: create second `Contact` (role=owner), create `PropertyContact` with `is_primary=False`
  - After data migration: log counts of Contact, ContactPhone, ContactEmail records created and Lead records processed
  - Downgrade: drop tables `property_contacts`, `contact_emails`, `contact_phones`, `contacts` in dependency order

### Phase 2: Backend Service Layer

- [x] 2.1 Create `backend/app/services/contact_service.py`
  - `create_contact(data)` — validates at least one of first_name/last_name is non-empty/non-whitespace; creates Contact + ContactPhone records + ContactEmail records in a single transaction; returns created Contact
  - `update_contact(contact_id, data)` — updates Contact fields; replaces phones atomically (delete-then-insert); replaces emails atomically (delete-then-insert); returns updated Contact; raises 404 if not found
  - `delete_contact(contact_id)` — deletes Contact (cascades to phones, emails, property_contacts); raises 404 if not found
  - `link_contact_to_property(property_id, contact_id, role, is_primary)` — if `is_primary=True`, first sets all existing PropertyContact records for that property to `is_primary=False`; creates PropertyContact; raises 404 if property or contact not found; raises 409 on duplicate (property_id, contact_id)
  - `unlink_contact_from_property(property_id, contact_id)` — removes PropertyContact record; does NOT delete Contact; raises 404 if link not found
  - `get_contacts_for_property(property_id)` — returns list of Contact objects with join record metadata (role, is_primary); raises 404 if property not found
  - Re-export from `backend/app/services/__init__.py`

- [x] 2.2 Update `backend/app/services/hubspot_matcher_service.py`
  - Rewrite `match_contact()` to query `Contact` records instead of flat Lead columns
  - Email match: query `ContactEmail.value` (case-insensitive) → HIGH confidence; link HubSpot contact to matched Contact and through PropertyContact to the Property
  - Phone match: query `ContactPhone.value` (digits-only normalized) → HIGH confidence
  - Name + property match: query `Contact.first_name` + `Contact.last_name` + `PropertyContact.property_id` → MEDIUM confidence; link to existing Contact rather than creating new one
  - No match: create new Contact record from HubSpot data + PropertyContact with role=owner
  - Preserve all existing Match_Confidence rules (HIGH/MEDIUM)
  - Do NOT delete any existing Contact records during matching; log corrections if data conflict detected

- [x] 2.3 Update `backend/app/services/lead_scoring_engine.py`
  - `score_data_completeness()` — replace flat phone/email field checks with a join to `contact_phones` and `contact_emails` via the property's contacts (through `property_contacts`)
  - `score_owner_situation()` — replace `owner_first_name`/`owner_last_name` checks with a check for linked contacts via `property_contacts`

### Phase 3: Backend API Layer

- [x] 3.1 Rename `backend/app/controllers/lead_controller.py` to `backend/app/controllers/property_controller.py`
  - Rename Blueprint from `leads_bp` to `properties_bp` with URL prefix `/api/properties/`
  - Add a second Blueprint `leads_legacy_bp` at `/api/leads/` that returns HTTP 301 redirects to the corresponding `/api/properties/` path for every route
  - Rename all internal serializer functions: `_serialize_lead_summary` → `_serialize_property_summary`, etc.
  - Update `owner_name` filter to join through `property_contacts` → `contacts` (first_name/last_name contains, case-insensitive) instead of querying flat columns
  - Strip deprecated flat contact columns (`owner_first_name`, `owner_last_name`, `owner_2_first_name`, `owner_2_last_name`, `phone_1`–`phone_7`, `email_1`–`email_5`) from write payloads (POST/PUT) — do not write them to the database
  - Update registration in `backend/app/__init__.py`: register `properties_bp` at `/api/properties/` and `leads_legacy_bp` at `/api/leads/`
  - Update all internal service calls and imports that referenced `lead_controller` or `leads_bp`

- [x] 3.2 Create `backend/app/controllers/contact_controller.py`
  - Blueprint `contacts_bp` registered at `/api/contacts/`
  - `POST /api/contacts/` — call `contact_service.create_contact()`; return 201 with serialized Contact
  - `GET /api/contacts/<id>` — return Contact with phones, emails, linked properties; return 404 if not found
  - `PUT /api/contacts/<id>` — call `contact_service.update_contact()`; return updated Contact; return 404 if not found
  - `DELETE /api/contacts/<id>` — call `contact_service.delete_contact()`; return 204; return 404 if not found
  - `GET /api/properties/<id>/contacts` — call `contact_service.get_contacts_for_property()`; return list with role and is_primary from join record
  - `POST /api/properties/<id>/contacts` — call `contact_service.link_contact_to_property()`; return 201; return 404 if property/contact not found; return 409 on duplicate
  - `DELETE /api/properties/<id>/contacts/<contact_id>` — call `contact_service.unlink_contact_from_property()`; return 204; return 404 if link not found
  - All routes use `@handle_errors` decorator for consistent JSON error responses
  - Register `contacts_bp` in `backend/app/__init__.py`

- [x] 3.3 Add Marshmallow schemas to `backend/app/schemas.py`
  - `ContactPhoneSchema` — fields: `id` (dump only), `contact_id` (dump only), `value` (required, String), `label` (required, OneOf mobile/home/work/other)
  - `ContactEmailSchema` — fields: `id` (dump only), `contact_id` (dump only), `value` (required, String), `label` (required, OneOf personal/work/other)
  - `ContactCreateSchema` — fields: `first_name` (String, allow_none), `last_name` (String, allow_none), `role` (OneOf owner/property_manager/attorney/family_member/other, default owner), `role_description` (String, allow_none), `notes` (String, allow_none), `phones` (List of ContactPhoneSchema, load_default=[]), `emails` (List of ContactEmailSchema, load_default=[]); validator: at least one of first_name/last_name must be non-empty/non-whitespace
  - `ContactUpdateSchema` — same fields as ContactCreateSchema, all optional
  - `ContactResponseSchema` — all fields including `id`, `created_at`, `updated_at`, nested `phones` and `emails`
  - `PropertyContactLinkSchema` — fields: `contact_id` (required, Integer), `role` (required, OneOf), `is_primary` (required, Boolean)
  - `PropertyContactResponseSchema` — extends ContactResponseSchema with `property_contact_role` and `is_primary` from join record

### Phase 4: Frontend Types

- [x] 4.1 Rename TypeScript interfaces in `frontend/src/types/index.ts`
  - `Lead` → `Property`
  - `LeadSummary` → `PropertySummary`
  - `LeadDetail` → `PropertyDetail`
  - `LeadListResponse` → `PropertyListResponse`
  - `LeadListFilters` → `PropertyListFilters`
  - `LeadScoreRecord` → `PropertyScoreRecord` (also rename field `lead_id` → `property_id`)
  - `LeadScoreResponse` → `PropertyScoreResponse`
  - `LeadMarketingListMembership` → `PropertyMarketingListMembership`
  - `LeadAnalysisSession` → `PropertyAnalysisSession`
  - Update all import statements and usages across all `.tsx` and `.ts` files in `frontend/src/` so the TypeScript compiler reports zero type errors

- [x] 4.2 Add new Contact-related TypeScript types to `frontend/src/types/index.ts`
  - `ContactRole` type alias: `'owner' | 'property_manager' | 'attorney' | 'family_member' | 'other'`
  - `PhoneLabel` type alias: `'mobile' | 'home' | 'work' | 'other'`
  - `EmailLabel` type alias: `'personal' | 'work' | 'other'`
  - `ContactPhone` interface: `id`, `contact_id`, `value`, `label: PhoneLabel`
  - `ContactEmail` interface: `id`, `contact_id`, `value`, `label: EmailLabel`
  - `Contact` interface: `id`, `first_name`, `last_name`, `role: ContactRole`, `role_description`, `notes`, `phones: ContactPhone[]`, `emails: ContactEmail[]`, `created_at`, `updated_at`
  - `PropertyContact` interface: extends `Contact` with `property_contact_role: ContactRole` and `is_primary: boolean`
  - `PropertyContactLinkRequest` interface: `contact_id`, `role: ContactRole`, `is_primary: boolean`
  - `ContactCreatePayload` and `ContactUpdatePayload` interfaces for API calls

- [x] 4.3 Update `frontend/src/services/api.ts`
  - Rename `leadService` to `propertyService`; update all method names and URL paths from `/leads/` to `/properties/`
  - Add `contactService` with methods: `createContact`, `getContact`, `updateContact`, `deleteContact`, `getPropertyContacts`, `linkContactToProperty`, `unlinkContactFromProperty` — all using correct URL paths and TypeScript types from task 4.2
  - Update all components that import `leadService` to import `propertyService`

### Phase 5: Frontend UI Components

- [x] 5.1 Rename page component files
  - Rename `frontend/src/components/LeadListPage.tsx` → `frontend/src/components/PropertyListPage.tsx`
  - Rename `frontend/src/components/LeadDetailPage.tsx` → `frontend/src/components/PropertyDetailPage.tsx`
  - Update all imports in `App.tsx` and any other files that reference the old filenames
  - Update the frontend route from `/leads` to `/properties` in `App.tsx`; add a redirect from `/leads` to `/properties` for the legacy route

- [x] 5.2 Update all UI labels from "Lead/Leads" to "Property/Properties"
  - Sidebar navigation item: "Leads" → "Properties"
  - Page title on list view: "Leads" → "Properties"
  - All table column headers referencing "Lead" → "Property"
  - All button labels, empty-state messages, and confirmation dialogs containing "lead"/"leads" → "property"/"properties"
  - Work queue section labels: "Lead Score" → "Property Score", "Lead Category" → "Property Category"
  - Update `PropertyListPage.tsx` and `PropertyDetailPage.tsx` to read contact information from the Contacts section rather than flat columns

- [x] 5.3 Create `frontend/src/components/ContactsSection.tsx`
  - Accepts props: `propertyId: number`
  - Uses React Query to fetch contacts via `contactService.getPropertyContacts(propertyId)`
  - Renders a list of linked contacts, each showing: full name, role, primary-contact badge (MUI Chip), phone numbers, email addresses
  - "Set as Primary" button per contact entry — calls `contactService.linkContactToProperty` with `is_primary: true`; invalidates query on success
  - "Edit" button per contact entry — opens `ContactFormModal` in edit mode
  - "Remove" button per contact entry — calls `contactService.unlinkContactFromProperty`; shows MUI confirmation dialog before removing; invalidates query on success
  - "Add Contact" button — opens `ContactFormModal` in create mode
  - API errors surfaced via MUI `Snackbar` / `Alert`
  - Integrate `ContactsSection` into `PropertyDetailPage.tsx`

- [x] 5.4 Create `frontend/src/components/ContactFormModal.tsx`
  - Accepts props: `open: boolean`, `onClose: () => void`, `propertyId: number`, `contact?: PropertyContact` (undefined = create mode, defined = edit mode)
  - Fields: first name (TextField), last name (TextField), role (Select with ContactRole options), role description (TextField, shown only when role = 'other'), notes (TextField multiline)
  - Dynamic phone list: add/remove rows, each row has value (TextField) + label (Select with PhoneLabel options)
  - Dynamic email list: add/remove rows, each row has value (TextField) + label (Select with EmailLabel options)
  - Validation: at least one of first name / last name must be non-empty before submission; display inline MUI `FormHelperText` with `error` prop on failure
  - On submit (create mode): calls `contactService.createContact()` then `contactService.linkContactToProperty()`; on success closes modal and invalidates property contacts query
  - On submit (edit mode): calls `contactService.updateContact()`; on success closes modal and invalidates property contacts query
  - API errors surfaced via MUI `Snackbar` / `Alert`

### Phase 6: Tests

- [x] 6.1 Write unit tests in `backend/tests/test_contact_service.py`
  - `ContactService.create_contact()` with valid payload (name + phones + emails)
  - `ContactService.create_contact()` with both names empty → raises validation error
  - `ContactService.create_contact()` with only first_name set → succeeds
  - `ContactService.create_contact()` with only last_name set → succeeds
  - `ContactService.update_contact()` — phones and emails replaced atomically
  - `ContactService.update_contact()` with non-existent ID → raises 404
  - `ContactService.delete_contact()` — cascades to phones, emails, property_contacts
  - `ContactService.link_contact_to_property()` — primary-contact demotion: adding a new primary demotes the previous primary
  - `ContactService.link_contact_to_property()` — duplicate link → raises 409
  - `ContactService.unlink_contact_from_property()` — primary contact removed, no auto-promotion of remaining contacts
  - `ContactService.get_contacts_for_property()` — returns contacts with join record metadata

- [x] 6.2 Write unit tests in `backend/tests/test_property_controller.py`
  - Legacy redirect: `GET /api/leads/` → 301 to `/api/properties/`
  - Legacy redirect: `GET /api/leads/<id>` → 301 to `/api/properties/<id>`
  - `POST /api/properties/` with deprecated flat contact fields → fields are NOT written to the database
  - `GET /api/properties/?owner_name=<q>` → returns only properties with matching contact names
  - `GET /api/properties/?owner_name=<q>` → case-insensitive match
  - `GET /api/properties/?owner_name=<q>` → does not return properties with no matching contacts
  - All existing filter parameters continue to work alongside `owner_name`

- [x] 6.3 Write unit tests in `backend/tests/test_migration_contact.py`
  - Seed `leads` table with representative rows: owner 1 only, owner 1 + owner 2, phones/emails, all-null contact fields
  - Verify correct Contact count after migration
  - Verify correct ContactPhone and ContactEmail counts
  - Verify `is_primary=True` on first owner's PropertyContact, `is_primary=False` on second owner's
  - Verify null/empty phone and email values are skipped
  - Idempotency: running migration logic twice produces the same counts (no duplicates)
  - Verify migration log output contains counts of records created

- [x] 6.4 Write property-based tests in `backend/tests/test_contact_properties.py` using Hypothesis

  - [x] 6.4.1 Write property test for Property 1: Legacy redirect preserves path suffix
    - Strategy: generate valid path suffixes that exist under `/api/properties/`
    - Assert: `GET /api/leads/<suffix>` returns HTTP 301 with `Location` header pointing to `/api/properties/<suffix>`
    - `@settings(max_examples=50)`
    - **Validates: Requirements 1.2**

  - [x] 6.4.2 Write property test for Property 2: Property writes persist to the `leads` table
    - Strategy: generate valid property creation payloads
    - Assert: `POST /api/properties/` returns 201; record is retrievable from `leads` table with matching field values
    - `@settings(max_examples=50)`
    - **Validates: Requirements 1.5**

  - [x] 6.4.3 Write property test for Property 3: Contact data round-trip
    - Strategy: `contact_payload_strategy()` — generates ContactCreatePayload with random names, roles, 0–5 phones with any labels, 0–5 emails with any labels
    - Assert: `POST /api/contacts/` then `GET /api/contacts/<id>` returns all submitted fields equal to submitted values
    - `@settings(max_examples=100)`
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.8**

  - [x] 6.4.4 Write property test for Property 4: Empty-name contacts are rejected
    - Strategy: `empty_name_contact_strategy()` — generates payloads where both first_name and last_name are absent, null, or whitespace-only
    - Assert: `POST /api/contacts/` returns HTTP 400 with descriptive error; no Contact record created in database
    - `@settings(max_examples=100)`
    - **Validates: Requirements 4.5**

  - [x] 6.4.5 Write property test for Property 5: Property-Contact join record round-trip
    - Strategy: generate valid (property_id, contact_id, role, is_primary) combinations
    - Assert: `POST /api/properties/<id>/contacts` then `GET /api/properties/<id>/contacts` includes the linked contact with same role and is_primary values
    - `@settings(max_examples=100)`
    - **Validates: Requirements 5.3**

  - [x] 6.4.6 Write property test for Property 6: At most one primary contact per property
    - Strategy: `property_with_contacts_strategy()` — generates a property and a list of contacts to link with random is_primary assignments
    - Assert: count of contacts with `is_primary=True` is 0 or 1 at all times; adding a new primary demotes the previous; removing the primary leaves all remaining with `is_primary=False`
    - `@settings(max_examples=100)`
    - **Validates: Requirements 5.4, 5.5, 5.6**

  - [x] 6.4.7 Write property test for Property 7: Non-existent IDs return 404
    - Strategy: generate integer IDs that do not correspond to existing Contact or Property records
    - Assert: all Contact and Property-Contact endpoints that accept that ID return HTTP 404
    - `@settings(max_examples=100)`
    - **Validates: Requirements 6.8**

  - [x] 6.4.8 Write property test for Property 8: Migration idempotency
    - Strategy: generate sets of Lead records with varying contact field combinations
    - Assert: running migration logic twice produces the same total counts of Contact, ContactPhone, ContactEmail, and PropertyContact records as running it once
    - `@settings(max_examples=50)`
    - **Validates: Requirements 8.9**

  - [x] 6.4.9 Write property test for Property 9: Deprecated fields are not written after migration
    - Strategy: generate POST/PUT payloads that include any subset of deprecated flat contact fields
    - Assert: those fields are NOT written to the `leads` table row
    - `@settings(max_examples=100)`
    - **Validates: Requirements 9.1**

  - [x] 6.4.10 Write property test for Property 10: HubSpot contact matching targets Contact records
    - Strategy: generate Contact records with non-empty emails and phones; generate matching HubSpot contact payloads
    - Assert: email match → HubSpotMatch with confidence=HIGH linked to that Contact; phone match (digits-only normalized) → HIGH confidence match
    - `@settings(max_examples=100)`
    - **Validates: Requirements 10.1, 10.2, 10.4**

  - [x] 6.4.11 Write property test for Property 11: Unmatched HubSpot contacts create new Contact records
    - Strategy: generate HubSpot contact payloads whose email, phone, and name do not match any existing Contact
    - Assert: matcher creates exactly one new Contact record and one new PropertyContact; total Contact count increases by exactly one
    - `@settings(max_examples=50)`
    - **Validates: Requirements 10.3**

  - [x] 6.4.12 Write property test for Property 12: Matching never deletes existing Contact records
    - Strategy: generate sets of existing Contact records and arbitrary HubSpot contact payloads
    - Assert: running the HubSpot matcher does NOT decrease the total count of Contact records
    - `@settings(max_examples=50)`
    - **Validates: Requirements 10.5**

  - [x] 6.4.13 Write property test for Property 13: Owner-name filter returns exactly matching properties
    - Strategy: `search_scenario_strategy()` — generates a search string and a set of properties with contacts, some matching and some not
    - Assert: `GET /api/properties/?owner_name=q` returns exactly those properties with at least one linked Contact whose first_name or last_name contains q (case-insensitive); does NOT return properties whose contacts do not contain q
    - `@settings(max_examples=100)`
    - **Validates: Requirements 11.1, 11.2**

- [x] 6.5 Write frontend component tests in `frontend/src/components/ContactsSection.test.tsx`
  - Renders contact list with name, role, phones, emails for each linked contact
  - Renders primary-contact badge on the primary contact
  - "Set as Primary" button calls `contactService.linkContactToProperty` with correct arguments
  - "Remove" button calls `contactService.unlinkContactFromProperty` with correct property and contact IDs
  - "Add Contact" button opens `ContactFormModal`
  - API error from contacts fetch is surfaced via Snackbar

- [x] 6.6 Write frontend component tests in `frontend/src/components/ContactFormModal.test.tsx`
  - Renders in create mode when no `contact` prop is provided
  - Renders in edit mode with pre-filled fields when `contact` prop is provided
  - Submitting with both first name and last name empty shows inline validation error and does not call API
  - Submitting with only first name filled succeeds (no validation error)
  - Role description field is hidden when role is not 'other'; shown when role is 'other'
  - "Add phone" button adds a new phone row; remove button removes it
  - "Add email" button adds a new email row; remove button removes it
  - Successful create submission calls `createContact` then `linkContactToProperty` and closes modal
  - Successful edit submission calls `updateContact` and closes modal
  - API error is surfaced via Snackbar

- [x] 6.7 Write integration tests in `backend/tests/test_contact_integration.py`
  - `GET /api/properties/?owner_name=<q>` — verifies join through `property_contacts` → `contacts`
  - `POST /api/properties/<id>/contacts` with `is_primary=true` when another primary exists — verifies previous primary is demoted to `is_primary=False`
  - `DELETE /api/properties/<id>/contacts/<contact_id>` for primary contact — verifies no auto-promotion of remaining contacts
  - HubSpot matcher end-to-end: import a HubSpot contact, verify it matches the correct Contact record by email, by phone, and by name+property

## Notes

- The `leads` database table is intentionally preserved throughout this feature. The ORM class is renamed to `Property` in Python but `__tablename__` stays `'leads'`. This avoids cascading foreign key and migration changes across the entire project.
- Deprecated flat contact columns (`owner_first_name`, `owner_last_name`, `phone_1`–`phone_7`, etc.) remain in the `leads` table and are still returned in GET responses during the transition period, but are stripped from write payloads after the migration runs.
- The Alembic migration must be idempotent. The idempotency guard checks for an existing `PropertyContact` record for each `property_id` before creating new Contact records.
- All 13 Hypothesis property tests in task 6.4 use `@settings(max_examples=100)` (or 50 for heavier tests) and are tagged with a comment referencing the design property number and the requirements it validates.
- Frontend route `/leads` must redirect to `/properties` (React Router v6 `<Navigate>` component in `App.tsx`).
- The `leads_legacy_bp` Blueprint at `/api/leads/` must cover every route defined in `properties_bp` and return HTTP 301 (not 302) to ensure clients update their bookmarked URLs.
