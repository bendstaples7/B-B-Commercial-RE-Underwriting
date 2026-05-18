# Requirements Document

## Introduction

This feature refactors the core data model of the Real Estate Analysis Platform in three coordinated changes:

1. **Rename Lead → Property** — The "Lead" record represents a property acquisition opportunity. All user-facing labels, navigation items, API endpoint paths, and TypeScript types are renamed to "Property". The underlying database table (`leads`) is preserved to avoid a disruptive migration at this stage.

2. **Introduce a Contact model** — Owner contact information currently embedded in the Lead/Property record (flat phone and email columns, two owner name pairs) is extracted into a first-class `Contact` model with structured phone numbers, email addresses, a role field, and a notes field.

3. **Many-to-many Property ↔ Contact relationship** — A property can have multiple contacts; a contact can be linked to multiple properties. The join record carries a role and a primary-contact flag.

Existing data is migrated: the flat `owner_first_name`, `owner_last_name`, `phone_1`–`phone_7`, `email_1`–`email_5`, `owner_2_first_name`, and `owner_2_last_name` columns are converted into Contact records linked to the corresponding Property.

HubSpot contact matching is updated to target Contact records rather than the flat Lead columns.

> **Relationship to the HubSpot CRM Migration spec**: That spec defines a separate `Owner` model for HubSpot-imported owner records and a separate `Contact` model for communication records. The `Contact` model introduced here is the primary contact management workflow for manually managed properties and is distinct from those HubSpot-specific models. The HubSpot matching requirement in this spec (Requirement 7) describes how HubSpot contacts should map to this new Contact model after the refactor.

---

## Glossary

- **Platform**: The B and B Real Estate Analyzer web application (Flask/React).
- **Property**: A record representing a real estate asset and acquisition opportunity, previously called "Lead". Stored in the `leads` database table.
- **Property_API**: The Flask Blueprint that handles Property CRUD and scoring, exposed at `/api/properties/`.
- **Contact**: A person associated with one or more Properties, with structured name, role, phone numbers, email addresses, and notes.
- **Contact_Role**: The role a Contact plays in relation to a Property — one of: `owner`, `property_manager`, `attorney`, `family_member`, `other`.
- **Property_Contact**: The join record linking a Property to a Contact, carrying a Contact_Role and a primary-contact flag.
- **Phone_Label**: A label categorizing a phone number — one of: `mobile`, `home`, `work`, `other`.
- **Email_Label**: A label categorizing an email address — one of: `personal`, `work`, `other`.
- **Primary_Contact**: The single Contact on a Property designated as the main point of contact.
- **Migration_Script**: An Alembic migration that creates the `contacts`, `contact_phones`, `contact_emails`, and `property_contacts` tables and populates them from existing Lead columns.
- **Lead_Score**: The computed 0–100 score on a Property record (column name unchanged in the database).
- **HubSpot_Contact**: A raw record imported from the HubSpot Contacts API.

---

## Requirements

### Requirement 1: Rename Lead to Property in API Endpoints

**User Story:** As a developer integrating with the platform API, I want all endpoints to use `/api/properties/` instead of `/api/leads/`, so that the API surface reflects the domain language of the application.

#### Acceptance Criteria

1. THE Property_API SHALL expose all Property CRUD endpoints under the path prefix `/api/properties/`.
2. WHEN a request is made to a legacy `/api/leads/` path, THE Property_API SHALL return an HTTP 301 redirect to the corresponding `/api/properties/` path.
3. THE Property_API SHALL accept and return JSON payloads using the field names defined in the Property schema; field names that were previously prefixed or labeled as "lead" SHALL be updated to use "property" where applicable.
4. THE Platform SHALL update all internal service calls, Celery task references, and import controller references to use the `/api/properties/` prefix.
5. WHEN the Property_API writes to the database during record creation or update, THE Platform SHALL write to the `leads` table and SHALL return an HTTP 500 error if the write to the `leads` table fails; background processes and health checks SHALL also continue to use the `leads` table as the authoritative storage target.

---

### Requirement 2: Rename Lead to Property in TypeScript Types

**User Story:** As a frontend developer, I want all TypeScript interfaces and enums to use "Property" terminology, so that the frontend codebase is consistent with the domain language.

#### Acceptance Criteria

1. THE Platform SHALL rename the `Lead` TypeScript interface to `Property` in `frontend/src/types/index.ts`.
2. THE Platform SHALL rename the `LeadSummary` TypeScript interface to `PropertySummary`.
3. THE Platform SHALL rename the `LeadDetail` TypeScript interface to `PropertyDetail`.
4. THE Platform SHALL rename the `LeadListResponse` TypeScript interface to `PropertyListResponse`.
5. THE Platform SHALL rename the `LeadListFilters` TypeScript interface to `PropertyListFilters`.
6. THE Platform SHALL rename the `LeadScoreRecord` TypeScript interface to `PropertyScoreRecord` and update the `lead_id` field to `property_id`.
7. THE Platform SHALL rename the `LeadScoreResponse` TypeScript interface to `PropertyScoreResponse`.
8. THE Platform SHALL rename the `LeadMarketingListMembership` TypeScript interface to `PropertyMarketingListMembership`.
9. THE Platform SHALL rename the `LeadAnalysisSession` TypeScript interface to `PropertyAnalysisSession`.
10. WHEN TypeScript interfaces are renamed, THE Platform SHALL update all import statements and usages across all `.tsx` and `.ts` files in `frontend/src/`; the rename SHALL be treated as an atomic operation and SHALL NOT be considered complete until all import statements referencing the old interface names have been updated and the TypeScript compiler reports no type errors.

---

### Requirement 3: Rename Lead to Property in UI Labels

**User Story:** As a platform user, I want every visible label, page title, navigation item, table header, and work queue name to say "Property" or "Properties" instead of "Lead" or "Leads", so that the application uses consistent domain language.

#### Acceptance Criteria

1. THE Platform SHALL update the sidebar navigation item from "Leads" to "Properties".
2. THE Platform SHALL update the page title of the list view from "Leads" to "Properties".
3. THE Platform SHALL update all table column headers that reference "Lead" to reference "Property".
4. THE Platform SHALL update all button labels, empty-state messages, and confirmation dialogs that contain the word "lead" or "leads" to use "property" or "properties".
5. THE Platform SHALL update the work queue section labels (e.g., "Lead Score", "Lead Category") to use "Property Score" and "Property Category".
6. THE Platform SHALL update the `LeadListPage` component filename to `PropertyListPage` and the `LeadDetailPage` component filename to `PropertyDetailPage`.
7. WHEN a user navigates to the legacy `/leads` frontend route, THE Platform SHALL redirect to `/properties`.

---

### Requirement 4: Contact Model

**User Story:** As a platform user, I want to store structured contact records for property owners and related parties, so that I can manage multiple contacts per property with full name, role, phone numbers, email addresses, and notes.

#### Acceptance Criteria

1. THE Platform SHALL store Contact records with at minimum: first name, last name, Contact_Role, and a notes field (optional).
2. THE Platform SHALL store one or more phone numbers per Contact, each with a value and a Phone_Label.
3. THE Platform SHALL store one or more email addresses per Contact, each with a value and an Email_Label.
4. WHEN a Contact_Role of `other` is selected, THE Platform SHALL accept and store a free-text description of the role.
5. IF a Contact is submitted with both first name and last name empty, THEN THE Platform SHALL reject the request and return a descriptive validation error.
6. THE Platform SHALL allow a Contact to exist with no phone numbers and no email addresses.
7. THE Platform SHALL allow a Contact to be linked to zero or more Properties.
8. WHEN a Contact record is created or updated, THE Platform SHALL record the `created_at` and `updated_at` timestamps.

---

### Requirement 5: Property ↔ Contact Relationship

**User Story:** As a platform user, I want to link multiple contacts to a property and link a single contact to multiple properties, so that I can model shared ownership and complex contact networks.

#### Acceptance Criteria

1. THE Platform SHALL allow a Property to be linked to zero or more Contacts through a Property_Contact join record.
2. THE Platform SHALL allow a Contact to be linked to zero or more Properties through a Property_Contact join record.
3. THE Property_Contact join record SHALL carry a Contact_Role field and a boolean `is_primary` flag.
4. WHEN a Property has at least one Contact, THE Platform SHALL allow exactly one Contact per Property to have `is_primary` set to `true`; all other Contacts on that Property SHALL have `is_primary` set to `false`.
5. WHEN a new Contact is added to a Property with `is_primary` set to `true` and another Contact on that Property already has `is_primary` set to `true`, THE Platform SHALL automatically set the previous primary Contact's `is_primary` flag to `false`.
6. WHEN a Contact is removed from a Property and that Contact was the primary contact, THE Platform SHALL leave the `is_primary` flag unset on all remaining Contacts rather than automatically promoting another Contact.
7. THE Platform SHALL allow the Contact_Role on a Property_Contact record to differ from the Contact's own Contact_Role field.

---

### Requirement 6: Contact API Endpoints

**User Story:** As a developer, I want REST endpoints for creating, reading, updating, and deleting contacts and their property associations, so that the frontend can manage the full contact lifecycle.

#### Acceptance Criteria

1. THE Platform SHALL expose a `POST /api/contacts/` endpoint that creates a new Contact record with optional phone numbers and email addresses in a single request.
2. THE Platform SHALL expose a `GET /api/contacts/<id>` endpoint that returns a Contact record including all associated phone numbers, email addresses, and linked Properties.
3. THE Platform SHALL expose a `PUT /api/contacts/<id>` endpoint that updates a Contact record's fields, phone numbers, and email addresses.
4. THE Platform SHALL expose a `DELETE /api/contacts/<id>` endpoint that removes a Contact record and all its Property_Contact associations.
5. THE Platform SHALL expose a `GET /api/properties/<id>/contacts` endpoint that returns all Contacts linked to a given Property, including the Contact_Role and `is_primary` flag from the Property_Contact record.
6. THE Platform SHALL expose a `POST /api/properties/<id>/contacts` endpoint that links an existing Contact to a Property with a specified Contact_Role and `is_primary` flag.
7. THE Platform SHALL expose a `DELETE /api/properties/<id>/contacts/<contact_id>` endpoint that removes the link between a Property and a Contact without deleting the Contact record.
8. IF a request references a Contact ID or Property ID that does not exist, THEN THE Platform SHALL return an HTTP 404 response with a descriptive error message.

---

### Requirement 7: Contact UI on Property Detail Page

**User Story:** As a platform user, I want to view, add, edit, and remove contacts directly from the property detail page, so that I can manage all contact information in one place.

#### Acceptance Criteria

1. THE Platform SHALL display a Contacts section on the Property detail page listing all linked Contacts with their name, role, phone numbers, email addresses, and primary-contact indicator.
2. THE Platform SHALL provide a UI control on the Property detail page to add a new Contact or link an existing Contact to the Property.
3. THE Platform SHALL provide a UI control on each Contact entry to edit the Contact's fields inline or in a modal.
4. THE Platform SHALL provide a UI control on each Contact entry to remove the Contact from the Property without deleting the Contact record.
5. THE Platform SHALL provide a UI control to designate a Contact as the primary contact for the Property.
6. WHEN a Contact is added or updated, THE Platform SHALL refresh the Contacts section without a full page reload.
7. IF a contact form submission fails validation, THEN THE Platform SHALL display an inline error message identifying the specific validation failure.

---

### Requirement 8: Data Migration — Existing Lead Records

**User Story:** As a platform operator, I want existing Lead records to be migrated so that their embedded owner and contact fields are converted into Contact records linked to the corresponding Property, so that no historical contact data is lost.

#### Acceptance Criteria

1. THE Migration_Script SHALL create a Contact record for each unique owner represented by `owner_first_name` and `owner_last_name` on each Lead record, with Contact_Role set to `owner`.
2. THE Migration_Script SHALL create a second Contact record for each Lead record where `owner_2_first_name` or `owner_2_last_name` is non-null, with Contact_Role set to `owner`.
3. THE Migration_Script SHALL migrate `phone_1` through `phone_7` from each Lead record to ContactPhone records linked to the first owner Contact, using Phone_Label `other` for all migrated numbers.
4. THE Migration_Script SHALL migrate `email_1` through `email_5` from each Lead record to ContactEmail records linked to the first owner Contact, using Email_Label `other` for all migrated emails.
5. THE Migration_Script SHALL set `is_primary` to `true` on the Property_Contact record for the first owner Contact on each Property.
6. WHEN a Lead record has both `owner_first_name`/`owner_last_name` and `owner_2_first_name`/`owner_2_last_name`, THE Migration_Script SHALL create two separate Contact records and two separate Property_Contact records for that Property.
7. THE Migration_Script SHALL skip phone and email values that are null or empty strings rather than creating blank ContactPhone or ContactEmail records.
8. WHEN the Migration_Script completes, THE Platform SHALL log the total count of Contact records created, ContactPhone records created, ContactEmail records created, and Lead records processed.
9. THE Migration_Script SHALL be idempotent: running it a second time on already-migrated data SHALL not create duplicate Contact records.

---

### Requirement 9: Deprecate Flat Contact Columns on Property

**User Story:** As a developer, I want the flat owner and contact columns on the Property record to be deprecated after migration, so that the Contact model becomes the single source of truth for contact information.

#### Acceptance Criteria

1. AFTER the Migration_Script has run, THE Property_API SHALL no longer accept `owner_first_name`, `owner_last_name`, `owner_2_first_name`, `owner_2_last_name`, `phone_1`–`phone_7`, or `email_1`–`email_5` as writable fields in create or update requests.
2. THE Property_API SHALL continue to return the flat columns in GET responses during a transition period to avoid breaking existing consumers, but SHALL mark them as deprecated in the API schema documentation.
3. THE Platform SHALL update the Property list and detail UI components to read contact information from the Contacts section rather than from the flat columns.
4. THE Platform SHALL update the lead scoring service to read contact completeness signals from the Contact model rather than from the flat columns.
5. THE Platform SHALL update the Google Sheets import controller to map imported phone and email columns to Contact records rather than to flat Lead columns.

---

### Requirement 10: Update HubSpot Contact Matching

**User Story:** As a platform user, I want HubSpot contacts to be matched to Contact records rather than to flat Lead fields, so that the HubSpot integration remains accurate after the data model change.

#### Acceptance Criteria

1. WHEN a HubSpot_Contact is processed for matching, THE Matcher SHALL search Contact records by email address, phone number (normalized to digits only), and full name rather than searching the flat `owner_first_name`, `owner_last_name`, `phone_1`–`phone_7`, and `email_1`–`email_5` columns on the Lead/Property record.
2. WHEN a HubSpot_Contact match is found against a Contact record, THE Matcher SHALL link the HubSpot_Contact to the matched Contact record and, through the Property_Contact association, to the corresponding Property.
3. WHEN no matching Contact record is found by email, phone, or name-plus-property, THE Matcher SHALL create a new Contact record populated from the HubSpot_Contact data and link it to the matched Property via a Property_Contact record with Contact_Role set to `owner`; WHEN a name-plus-property match is found, THE Matcher SHALL link the HubSpot_Contact to the existing matched Contact record rather than creating a new one.
4. THE Platform SHALL preserve all existing Match_Confidence rules (HIGH for email/phone match, MEDIUM for name-plus-property match) when matching against Contact records.
5. WHEN the HubSpot matching logic is updated, THE Platform SHALL not delete any existing Contact records that were created by the Migration_Script; IF the HubSpot matching process detects a data conflict or corruption in a migrated Contact record, THE Matcher SHALL apply corrections to the Contact record and log the change rather than preserving the corrupted data.

---

### Requirement 11: Property List and Search

**User Story:** As a platform user, I want to search and filter the Properties list by contact name, so that I can find a property by the name of its owner or associated contact.

#### Acceptance Criteria

1. THE Property_API SHALL accept an `owner_name` filter parameter on the `GET /api/properties/` endpoint that searches across the first name and last name of all Contacts linked to each Property.
2. WHEN an `owner_name` filter is applied, THE Property_API SHALL return all Properties that have at least one linked Contact whose first name or last name contains the search string (case-insensitive); THE Property_API SHALL match only against the Contact's first name and last name fields and SHALL NOT apply fuzzy or phonetic matching against other Contact fields.
3. THE Platform SHALL update the frontend property list filter UI to use the Contact-based `owner_name` search rather than the flat column search.
4. THE Property_API SHALL continue to support all existing filter parameters (property type, category, city, state, zip, score range, marketing list) alongside the updated `owner_name` filter.
