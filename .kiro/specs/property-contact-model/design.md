# Design Document — Property Contact Model

## Overview

This feature delivers three coordinated changes to the Real Estate Analysis Platform:

1. **Lead → Property rename** — The API path prefix, TypeScript types, and all UI labels are updated from "Lead/Leads" to "Property/Properties". The underlying `leads` database table is preserved to avoid a disruptive schema migration.

2. **Contact model** — A first-class `Contact` entity replaces the flat `owner_first_name`, `owner_last_name`, `phone_1`–`phone_7`, and `email_1`–`email_5` columns on the Lead/Property record. Each Contact has structured phone numbers (`contact_phones`), email addresses (`contact_emails`), a role, and a notes field.

3. **Many-to-many Property ↔ Contact relationship** — A `property_contacts` join table links properties to contacts, carrying a role and a primary-contact flag per association.

Existing data is migrated via an Alembic migration script. HubSpot contact matching is updated to target the new Contact model.

---

## Architecture

The change spans three layers:

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (React 18 / TypeScript 5)                             │
│  ┌──────────────────┐  ┌──────────────────────────────────────┐ │
│  │  Renamed types   │  │  ContactsSection component           │ │
│  │  Property*       │  │  (new, on PropertyDetailPage)        │ │
│  └──────────────────┘  └──────────────────────────────────────┘ │
│  src/services/api.ts — propertyService + contactService         │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (Axios / React Query)
┌────────────────────────────▼────────────────────────────────────┐
│  Backend (Flask 3.0)                                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  property_controller.py  (renamed from lead_controller)  │   │
│  │  Blueprint: /api/properties/                             │   │
│  │  Legacy redirect: /api/leads/* → /api/properties/*       │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  contact_controller.py  (new)                            │   │
│  │  Blueprint: /api/contacts/                               │   │
│  │  Nested:    /api/properties/<id>/contacts                │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  Marshmallow schemas (schemas.py)                        │   │
│  │  ContactCreateSchema, ContactUpdateSchema,               │   │
│  │  PropertyContactLinkSchema                               │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Services                                                │   │
│  │  contact_service.py  (new)                               │   │
│  │  hubspot_matcher_service.py  (updated)                   │   │
│  │  lead_scoring_engine.py  (updated)                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────────┘
                             │ SQLAlchemy / psycopg2
┌────────────────────────────▼────────────────────────────────────┐
│  PostgreSQL                                                     │
│  leads (unchanged)  contacts  contact_phones  contact_emails    │
│  property_contacts (join table)                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

**Preserve the `leads` table.** Renaming the table would require updating every foreign key, index, and migration in the project. The API/type/UI rename is purely cosmetic at the database layer — the ORM model class is renamed to `Property` in Python but `__tablename__` stays `'leads'`.

**Separate `contact_phones` and `contact_emails` tables.** Storing phone numbers and email addresses as child rows (rather than JSON columns) enables indexed lookups during HubSpot matching and keeps the schema normalized.

**Role on both Contact and Property_Contact.** A contact's own role (e.g., "attorney") is a property of the person. The role on the join record (e.g., "property_manager" for a specific property) can differ. Both are stored independently per Requirement 5.7.

**Idempotent migration.** The Alembic migration checks for existing Contact records before creating new ones, so it can be re-run safely on partially migrated data.

---

## Components and Interfaces

### Backend Components

#### `property_controller.py` (renamed from `lead_controller.py`)

- Blueprint name: `properties`, URL prefix: `/api/properties/`
- A second Blueprint `leads_legacy_bp` is registered at `/api/leads/` and returns HTTP 301 redirects to the corresponding `/api/properties/` path for every route.
- All serializer functions renamed: `_serialize_lead_summary` → `_serialize_property_summary`, etc.
- The `owner_name` filter is updated to join through `property_contacts` → `contacts` instead of querying flat columns.
- Deprecated flat contact columns (`owner_first_name`, `owner_last_name`, `phone_1`–`phone_7`, `email_1`–`email_5`, `owner_2_first_name`, `owner_2_last_name`) are stripped from write payloads after migration.

#### `contact_controller.py` (new)

Blueprint registered at `/api/contacts/` and nested routes under `/api/properties/<id>/contacts`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/contacts/` | Create Contact with optional phones/emails |
| GET | `/api/contacts/<id>` | Get Contact with phones, emails, linked properties |
| PUT | `/api/contacts/<id>` | Update Contact fields, phones, emails |
| DELETE | `/api/contacts/<id>` | Delete Contact and all Property_Contact associations |
| GET | `/api/properties/<id>/contacts` | List Contacts for a Property |
| POST | `/api/properties/<id>/contacts` | Link existing Contact to Property |
| DELETE | `/api/properties/<id>/contacts/<contact_id>` | Unlink Contact from Property |

#### `contact_service.py` (new)

Encapsulates all Contact business logic:

- `create_contact(data)` — validates, creates Contact + phones + emails in a single transaction
- `update_contact(contact_id, data)` — replaces phones/emails atomically (delete-then-insert)
- `delete_contact(contact_id)` — cascades to phones, emails, and property_contacts
- `link_contact_to_property(property_id, contact_id, role, is_primary)` — enforces the single-primary invariant
- `unlink_contact_from_property(property_id, contact_id)` — removes join record, leaves Contact intact
- `get_contacts_for_property(property_id)` — returns contacts with join record metadata

#### `hubspot_matcher_service.py` (updated)

`match_contact()` is rewritten to query `Contact` records instead of flat Lead columns:

1. Email match → `ContactEmail.value` (case-insensitive) → HIGH confidence
2. Phone match → `ContactPhone.value` (digits-only normalized) → HIGH confidence
3. Name + property match → `Contact.first_name` + `Contact.last_name` + `PropertyContact.property_id` → MEDIUM confidence
4. No match → create new `Contact` record + `PropertyContact` association

#### `lead_scoring_engine.py` (updated)

- `score_data_completeness()` — replaces flat phone/email field checks with a join to `contact_phones` and `contact_emails` via the property's contacts
- `score_owner_situation()` — checks for linked contacts instead of `owner_first_name`/`owner_last_name`

### Frontend Components

#### Renamed TypeScript Types (`src/types/index.ts`)

| Old Name | New Name |
|----------|----------|
| `Lead` | `Property` |
| `LeadSummary` | `PropertySummary` |
| `LeadDetail` | `PropertyDetail` |
| `LeadListResponse` | `PropertyListResponse` |
| `LeadListFilters` | `PropertyListFilters` |
| `LeadScoreRecord` | `PropertyScoreRecord` (field `lead_id` → `property_id`) |
| `LeadScoreResponse` | `PropertyScoreResponse` |
| `LeadMarketingListMembership` | `PropertyMarketingListMembership` |
| `LeadAnalysisSession` | `PropertyAnalysisSession` |

New types added:

```typescript
export type ContactRole = 'owner' | 'property_manager' | 'attorney' | 'family_member' | 'other'
export type PhoneLabel = 'mobile' | 'home' | 'work' | 'other'
export type EmailLabel = 'personal' | 'work' | 'other'

export interface ContactPhone {
  id: number
  contact_id: number
  value: string
  label: PhoneLabel
}

export interface ContactEmail {
  id: number
  contact_id: number
  value: string
  label: EmailLabel
}

export interface Contact {
  id: number
  first_name: string | null
  last_name: string | null
  role: ContactRole
  role_description: string | null   // populated when role === 'other'
  notes: string | null
  phones: ContactPhone[]
  emails: ContactEmail[]
  created_at: string | null
  updated_at: string | null
}

export interface PropertyContact extends Contact {
  // Fields from the Property_Contact join record
  property_contact_role: ContactRole
  is_primary: boolean
}

export interface PropertyContactLinkRequest {
  contact_id: number
  role: ContactRole
  is_primary: boolean
}
```

#### Renamed Page Components

| Old Filename | New Filename |
|--------------|--------------|
| `LeadListPage.tsx` | `PropertyListPage.tsx` |
| `LeadDetailPage.tsx` | `PropertyDetailPage.tsx` |

#### New Component: `ContactsSection.tsx`

Rendered inside `PropertyDetailPage`. Displays a list of linked contacts with:
- Name, role, primary-contact badge
- Phone numbers and email addresses
- Edit button (opens `ContactFormModal`)
- Remove button (calls `DELETE /api/properties/<id>/contacts/<contact_id>`)
- "Add Contact" button (opens `ContactFormModal` in create mode or link-existing mode)
- "Set as Primary" button per contact entry

#### New Component: `ContactFormModal.tsx`

Modal dialog for creating or editing a Contact. Fields:
- First name, last name (at least one required)
- Role (select), role description (shown when role = 'other')
- Notes (textarea)
- Dynamic phone list (add/remove rows, each with value + label select)
- Dynamic email list (add/remove rows, each with value + label select)

#### Updated `src/services/api.ts`

```typescript
export const propertyService = {
  listProperties: (filters: PropertyListFilters) => ...,
  getProperty: (id: number) => ...,
  // ... (renamed from leadService)
}

export const contactService = {
  createContact: (data: ContactCreatePayload) =>
    api.post<Contact>('/contacts/', data),
  getContact: (id: number) =>
    api.get<Contact>(`/contacts/${id}`),
  updateContact: (id: number, data: ContactUpdatePayload) =>
    api.put<Contact>(`/contacts/${id}`, data),
  deleteContact: (id: number) =>
    api.delete(`/contacts/${id}`),
  getPropertyContacts: (propertyId: number) =>
    api.get<PropertyContact[]>(`/properties/${propertyId}/contacts`),
  linkContactToProperty: (propertyId: number, data: PropertyContactLinkRequest) =>
    api.post<PropertyContact>(`/properties/${propertyId}/contacts`, data),
  unlinkContactFromProperty: (propertyId: number, contactId: number) =>
    api.delete(`/properties/${propertyId}/contacts/${contactId}`),
}
```

---

## Data Models

### New SQLAlchemy Models

#### `Contact` (`backend/app/models/contact.py`)

```python
class Contact(db.Model):
    __tablename__ = 'contacts'

    id            = db.Column(db.Integer, primary_key=True)
    first_name    = db.Column(db.String(128), nullable=True)
    last_name     = db.Column(db.String(128), nullable=True)
    role          = db.Column(db.Enum(
                       'owner', 'property_manager', 'attorney',
                       'family_member', 'other',
                       name='contact_role_enum'), nullable=False, default='owner')
    role_description = db.Column(db.String(255), nullable=True)
    notes         = db.Column(db.Text, nullable=True)
    created_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, nullable=False,
                              default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    phones        = db.relationship('ContactPhone', backref='contact',
                                    cascade='all, delete-orphan', lazy='select')
    emails        = db.relationship('ContactEmail', backref='contact',
                                    cascade='all, delete-orphan', lazy='select')
    property_contacts = db.relationship('PropertyContact', backref='contact',
                                        cascade='all, delete-orphan', lazy='dynamic')
```

**Constraint:** A CHECK constraint (enforced in application logic and Marshmallow) ensures that at least one of `first_name` or `last_name` is non-empty.

#### `ContactPhone` (`backend/app/models/contact_phone.py`)

```python
class ContactPhone(db.Model):
    __tablename__ = 'contact_phones'

    id         = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    value      = db.Column(db.String(50), nullable=False)
    label      = db.Column(db.Enum('mobile', 'home', 'work', 'other',
                                   name='phone_label_enum'),
                           nullable=False, default='other')
```

#### `ContactEmail` (`backend/app/models/contact_email.py`)

```python
class ContactEmail(db.Model):
    __tablename__ = 'contact_emails'

    id         = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    value      = db.Column(db.String(255), nullable=False, index=True)
    label      = db.Column(db.Enum('personal', 'work', 'other',
                                   name='email_label_enum'),
                           nullable=False, default='other')
```

#### `PropertyContact` (`backend/app/models/property_contact.py`)

```python
class PropertyContact(db.Model):
    __tablename__ = 'property_contacts'

    id          = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    contact_id  = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    role        = db.Column(db.Enum(
                     'owner', 'property_manager', 'attorney',
                     'family_member', 'other',
                     name='property_contact_role_enum'), nullable=False, default='owner')
    is_primary  = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        db.UniqueConstraint('property_id', 'contact_id', name='uq_property_contact'),
    )
```

### Updated `Lead` Model (`backend/app/models/lead.py`)

The `Lead` class is renamed to `Property` in Python (keeping `__tablename__ = 'leads'`). A new relationship is added:

```python
class Property(db.Model):
    __tablename__ = 'leads'
    # ... all existing columns unchanged ...

    # New relationship
    property_contacts = db.relationship('PropertyContact', backref='property',
                                        cascade='all, delete-orphan', lazy='dynamic')
```

### Alembic Migration

A single Alembic migration (`alembic_migrations/versions/XXXX_add_contact_model.py`) performs:

1. **Create tables**: `contacts`, `contact_phones`, `contact_emails`, `property_contacts`
2. **Migrate data**: For each row in `leads`:
   - If `owner_first_name` or `owner_last_name` is non-null: create a `Contact` (role=`owner`), migrate `phone_1`–`phone_7` as `ContactPhone` records (label=`other`, skip nulls/empty), migrate `email_1`–`email_5` as `ContactEmail` records (label=`other`, skip nulls/empty), create a `PropertyContact` with `is_primary=True`
   - If `owner_2_first_name` or `owner_2_last_name` is non-null: create a second `Contact` (role=`owner`), create a `PropertyContact` with `is_primary=False`
3. **Idempotency guard**: Before creating a Contact for a lead, check if a `PropertyContact` already exists for that `property_id`. If so, skip.
4. **Logging**: After completion, log counts of Contact, ContactPhone, ContactEmail records created and Lead records processed.

### Database Schema Diagram

```
leads (unchanged columns)
  id PK
  property_street
  ... (all existing columns)
  owner_first_name  ← deprecated (read-only after migration)
  owner_last_name   ← deprecated
  phone_1..phone_7  ← deprecated
  email_1..email_5  ← deprecated
  owner_2_first_name ← deprecated
  owner_2_last_name  ← deprecated

contacts
  id PK
  first_name
  last_name
  role          ENUM(owner, property_manager, attorney, family_member, other)
  role_description
  notes
  created_at
  updated_at

contact_phones
  id PK
  contact_id FK → contacts.id  (CASCADE DELETE)
  value
  label         ENUM(mobile, home, work, other)

contact_emails
  id PK
  contact_id FK → contacts.id  (CASCADE DELETE)
  value         (indexed for HubSpot matching)
  label         ENUM(personal, work, other)

property_contacts
  id PK
  property_id FK → leads.id    (CASCADE DELETE)
  contact_id  FK → contacts.id (CASCADE DELETE)
  role          ENUM(owner, property_manager, attorney, family_member, other)
  is_primary    BOOLEAN
  UNIQUE(property_id, contact_id)
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

This feature involves business logic (validation rules, state transitions, search filtering, HubSpot matching) that is well-suited to property-based testing with Hypothesis. The testing library is **Hypothesis** (already in the project's test suite).

### Redundancy Analysis

Before listing properties, redundancy is eliminated:

- Requirements 1.2 (redirect) and 1.5 (writes to `leads` table) are independent properties with distinct verification targets.
- Requirements 4.2 and 4.3 (phone/email round-trips) are structurally identical — they are combined into a single "Contact data round-trip" property.
- Requirements 5.4, 5.5, and 5.6 all concern the `is_primary` invariant. They are combined into a single "at most one primary contact per property" property, with sub-cases for the add and remove transitions.
- Requirements 10.1 and 10.2 are the same observable behavior (match found → link created) and are combined.
- Requirements 10.3 and 10.5 are independent (create-on-no-match vs. preserve-existing) and are kept separate.

---

### Property 1: Legacy redirect preserves path suffix

*For any* valid path suffix that exists under `/api/properties/`, a GET request to the corresponding `/api/leads/<suffix>` path SHALL return HTTP 301 with a `Location` header pointing to `/api/properties/<suffix>`.

**Validates: Requirements 1.2**

---

### Property 2: Property writes persist to the `leads` table

*For any* valid property creation payload submitted to `POST /api/properties/`, the resulting record SHALL be retrievable from the `leads` table with matching field values, and the API SHALL return HTTP 201.

**Validates: Requirements 1.5**

---

### Property 3: Contact data round-trip

*For any* valid Contact payload (with any combination of first name, last name, role, notes, zero or more phones with any labels, and zero or more emails with any labels), creating the Contact via `POST /api/contacts/` and then retrieving it via `GET /api/contacts/<id>` SHALL return a response where all submitted fields are present and equal to the submitted values.

**Validates: Requirements 4.1, 4.2, 4.3, 4.8**

---

### Property 4: Empty-name contacts are rejected

*For any* Contact payload where both `first_name` and `last_name` are absent, null, or composed entirely of whitespace characters, `POST /api/contacts/` SHALL return HTTP 400 with a descriptive error message, and no Contact record SHALL be created in the database.

**Validates: Requirements 4.5**

---

### Property 5: Property-Contact join record round-trip

*For any* valid (property_id, contact_id, role, is_primary) combination submitted to `POST /api/properties/<id>/contacts`, retrieving the contact list via `GET /api/properties/<id>/contacts` SHALL include the linked contact with the same role and is_primary values that were submitted.

**Validates: Requirements 5.3**

---

### Property 6: At most one primary contact per property

*For any* property with any number of linked contacts, the count of contacts with `is_primary = true` SHALL be 0 or 1 at all times — including immediately after adding a new primary contact (which demotes the previous primary) and immediately after removing the primary contact (which leaves all remaining contacts with `is_primary = false`).

**Validates: Requirements 5.4, 5.5, 5.6**

---

### Property 7: Non-existent IDs return 404

*For any* integer ID that does not correspond to an existing Contact or Property record, all Contact and Property-Contact endpoints that accept that ID SHALL return HTTP 404.

**Validates: Requirements 6.8**

---

### Property 8: Migration idempotency

*For any* set of Lead records in the database, running the migration script a second time SHALL produce the same total count of Contact, ContactPhone, ContactEmail, and PropertyContact records as running it once — no duplicates SHALL be created.

**Validates: Requirements 8.9**

---

### Property 9: Deprecated fields are not written after migration

*For any* `POST /api/properties/` or `PUT /api/properties/<id>` request payload that includes any subset of the deprecated flat contact fields (`owner_first_name`, `owner_last_name`, `owner_2_first_name`, `owner_2_last_name`, `phone_1`–`phone_7`, `email_1`–`email_5`), those fields SHALL NOT be written to the `leads` table row.

**Validates: Requirements 9.1**

---

### Property 10: HubSpot contact matching targets Contact records

*For any* Contact record with a non-empty email address, processing a HubSpot contact whose `email` property equals that email address SHALL produce a HubSpotMatch record with `confidence = 'HIGH'` linked to that Contact record. Similarly, *for any* Contact record with a non-empty phone number, processing a HubSpot contact whose normalized phone digits match SHALL produce a HIGH confidence match.

**Validates: Requirements 10.1, 10.2, 10.4**

---

### Property 11: Unmatched HubSpot contacts create new Contact records

*For any* HubSpot contact payload whose email, phone, and name do not match any existing Contact record, running the matcher SHALL create exactly one new Contact record and one new PropertyContact association, and the total Contact count SHALL increase by exactly one.

**Validates: Requirements 10.3**

---

### Property 12: Matching never deletes existing Contact records

*For any* set of existing Contact records, running the HubSpot matcher (regardless of the HubSpot contact payloads processed) SHALL NOT decrease the total count of Contact records in the database.

**Validates: Requirements 10.5**

---

### Property 13: Owner-name filter returns exactly matching properties

*For any* search string `q` and any set of properties with linked contacts, `GET /api/properties/?owner_name=q` SHALL return exactly those properties that have at least one linked Contact whose `first_name` or `last_name` contains `q` as a case-insensitive substring, and SHALL NOT return any property whose contacts do not contain `q`.

**Validates: Requirements 11.1, 11.2**

---

## Error Handling

### Validation Errors (HTTP 400)

- Contact submitted with both `first_name` and `last_name` empty/whitespace → `{"error": "Validation error", "message": "At least one of first_name or last_name is required"}`
- Invalid `role` value → Marshmallow `OneOf` validator returns field-level error
- Invalid `label` on phone or email → Marshmallow `OneOf` validator returns field-level error
- `is_primary` not a boolean → Marshmallow type coercion error

### Not Found Errors (HTTP 404)

All Contact and Property-Contact endpoints return `{"error": "Not found", "message": "<Entity> <id> does not exist"}` when the referenced ID does not exist. This is consistent with the existing `handle_errors` decorator pattern in `lead_controller.py`.

### Conflict Errors (HTTP 409)

- Attempting to link a Contact to a Property when the `(property_id, contact_id)` pair already exists in `property_contacts` → `{"error": "Conflict", "message": "Contact <id> is already linked to Property <id>"}`. The unique constraint on the join table enforces this at the database level; the service layer catches the `IntegrityError` and converts it to a 409.

### Database Write Failures (HTTP 500)

The existing `handle_errors` decorator catches unexpected exceptions and returns `{"error": "Internal server error", "message": "An unexpected error occurred"}`. All new controllers inherit this decorator.

### Frontend Error Display

- Contact form validation failures are displayed as inline field-level errors using MUI `FormHelperText` with `error` prop.
- API errors from contact operations are surfaced via a MUI `Snackbar` / `Alert` component (consistent with existing error handling in the app).
- React Query's `onError` callback triggers the snackbar for mutation failures.

---

## Testing Strategy

### Unit Tests (pytest)

Located in `backend/tests/test_contact_service.py` and `backend/tests/test_property_controller.py`.

Focus areas:
- `ContactService.create_contact()` with valid and invalid payloads
- `ContactService.link_contact_to_property()` — primary-contact demotion logic
- `ContactService.unlink_contact_from_property()` — primary-contact removal behavior
- `HubSpotMatcherService.match_contact()` — email match, phone match, name match, no-match paths
- `LeadScoringEngine.score_data_completeness()` — with contacts vs. without contacts
- Migration script — specific migration scenarios (owner 1 only, owner 1 + owner 2, phones/emails, null values)
- Legacy redirect — specific path examples

### Property-Based Tests (Hypothesis)

Located in `backend/tests/test_contact_properties.py`.

Each property test uses `@given` with Hypothesis strategies and is configured with `@settings(max_examples=100)`. Each test is tagged with a comment referencing the design property.

```python
# Feature: property-contact-model, Property 3: Contact data round-trip
@given(contact_payload_strategy())
@settings(max_examples=100)
def test_contact_round_trip(client, contact_payload):
    ...

# Feature: property-contact-model, Property 4: Empty-name contacts are rejected
@given(empty_name_contact_strategy())
@settings(max_examples=100)
def test_empty_name_rejected(client, payload):
    ...

# Feature: property-contact-model, Property 6: At most one primary contact per property
@given(property_with_contacts_strategy())
@settings(max_examples=100)
def test_at_most_one_primary(client, property_id, contacts):
    ...

# Feature: property-contact-model, Property 13: Owner-name filter returns exactly matching properties
@given(search_scenario_strategy())
@settings(max_examples=100)
def test_owner_name_filter(client, search_string, properties_with_contacts):
    ...
```

Hypothesis strategies to define:
- `contact_payload_strategy()` — generates `ContactCreatePayload` with random names, roles, 0–5 phones, 0–5 emails
- `empty_name_contact_strategy()` — generates payloads where both names are empty/whitespace
- `property_with_contacts_strategy()` — generates a property ID and a list of contacts to link, with random `is_primary` assignments
- `search_scenario_strategy()` — generates a search string and a set of properties with contacts, some matching and some not

### Frontend Tests (Vitest + React Testing Library)

Located in `frontend/src/components/ContactsSection.test.tsx` and `frontend/src/components/ContactFormModal.test.tsx`.

Focus areas:
- `ContactsSection` renders contact list with name, role, phones, emails
- "Set as Primary" button calls the correct API endpoint
- "Remove" button calls `DELETE /api/properties/<id>/contacts/<contact_id>`
- `ContactFormModal` validates that at least one name field is filled before submission
- `ContactFormModal` shows/hides role description field based on role selection
- Dynamic phone/email rows can be added and removed

### Integration Tests

- `GET /api/properties/` with `owner_name` filter — verifies join through `property_contacts` → `contacts`
- `POST /api/properties/<id>/contacts` with `is_primary=true` when another primary exists — verifies demotion
- `DELETE /api/properties/<id>/contacts/<contact_id>` for primary contact — verifies no auto-promotion
- HubSpot matcher end-to-end: import a HubSpot contact, verify it matches the correct Contact record

### Migration Test

A dedicated test in `backend/tests/test_migration_contact.py` seeds the `leads` table with representative rows (owner 1 only, owner 1 + owner 2, phones/emails, all-null contact fields) and verifies:
- Correct Contact count
- Correct ContactPhone and ContactEmail counts
- `is_primary` set correctly on first owner
- Idempotency: running migration logic twice produces the same counts
