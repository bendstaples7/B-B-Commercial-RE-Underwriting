# Requirements Document

## Introduction

This feature transforms the platform into a self-sufficient, property-first CRM by migrating all historical data from HubSpot and building the internal structures needed to replace it. The work is organized into six active phases: (1) internal CRM foundation, (2) HubSpot raw historical import, (3) HubSpot mapping and matching, (4) activity conversion and timeline, (5) lead scoring and signal enrichment, and (6) a deferred write-back phase. A seventh phase covers a mobile quick-add workflow as a future roadmap item.

The platform already manages residential and commercial leads, a lead scoring engine, a commercial condo filter, a property analysis workflow, and an offering memorandum analyzer. This feature extends that foundation so the platform becomes the authoritative source of truth for properties, leads, owners, organizations, contacts, interactions, tasks, valuations, and seller history — and HubSpot becomes a legacy archive.

---

## Glossary

- **Platform**: The B and B Real Estate Analyzer web application (Flask/React).
- **Property**: An internal record representing a real estate asset, identified primarily by its Parcel Identification Number (PIN) or normalized street address.
- **Lead**: An internal record linking a Property to a potential acquisition opportunity, with a computed score, status, and follow-up workflow.
- **Owner**: An individual person associated with a Property as a title holder, seller contact, or related party.
- **Organization**: A legal entity (LLC, trust, corporation, brokerage, law firm, property management company) associated with a Property or Owner.
- **Contact**: A communication record for an Owner or Organization, containing phone numbers, email addresses, and mailing addresses.
- **Interaction**: An internal record of a communication event (note, call, email, meeting) attached to a Property, Lead, Owner, Organization, or Contact.
- **Task**: An internal to-do item attached to a Property, Lead, Owner, or Organization, with a due date and completion status.
- **Timeline**: A chronologically ordered view of all Interactions and Tasks associated with a given Property, Lead, or Owner.
- **HubSpot_Deal**: A raw record imported from the HubSpot Deals API, representing a property in HubSpot.
- **HubSpot_Contact**: A raw record imported from the HubSpot Contacts API, representing a person in HubSpot.
- **HubSpot_Company**: A raw record imported from the HubSpot Companies API, representing an entity in HubSpot.
- **HubSpot_Note**: A raw engagement record of type NOTE imported from HubSpot.
- **HubSpot_Call**: A raw engagement record of type CALL imported from HubSpot.
- **HubSpot_Task**: A raw engagement record of type TASK imported from HubSpot.
- **Import_Run**: A logged execution of a HubSpot import operation, recording start time, end time, record counts, and status.
- **Match**: A confirmed or proposed link between a HubSpot raw record and an internal Platform record.
- **Match_Confidence**: A categorical rating (HIGH, MEDIUM, LOW, UNMATCHED) assigned to each proposed Match.
- **PIN**: Parcel Identification Number — the strongest property identifier, sourced from county records or HubSpot custom fields.
- **Normalized_Address**: A street address that has been standardized to uppercase, with abbreviations expanded and punctuation removed, for comparison purposes.
- **HubSpot_Signal**: A derived flag extracted from HubSpot engagement history that describes a prior seller interaction outcome (e.g., PRIOR_WARM_CONVERSATION, SELLER_NOT_INTERESTED).
- **Suppression_Flag**: A flag on a Lead or Owner indicating that outreach should be halted (e.g., DO_NOT_CONTACT, WRONG_NUMBER).
- **Import_Area**: A dedicated section of the Platform UI for configuring, running, and monitoring HubSpot imports.
- **Review_Queue**: A UI view listing Matches with LOW or UNMATCHED confidence that require manual user confirmation.
- **Celery_Worker**: The background task processor used for long-running import and matching operations.
- **Backup_Export**: A downloadable archive of all raw HubSpot data preserved in the Platform database.

---

## Requirements

### Requirement 1: Internal Organization Model

**User Story:** As a platform user, I want to record organizations (LLCs, trusts, brokerages, law firms) and link them to properties and owners, so that I can understand the full ownership and relationship structure of a deal without relying on HubSpot.

#### Acceptance Criteria

1. THE Platform SHALL store Organization records with at minimum: name, organization type (LLC, trust, corporation, brokerage, law firm, property management, unknown), status (active, inactive, unknown), and an optional notes field.
2. THE Platform SHALL allow an Organization to be linked to one or more Properties through a named relationship role (e.g., owner, property manager, broker, attorney, related party).
3. THE Platform SHALL allow an Organization to be linked to one or more Owners through a named relationship role (e.g., principal, member, attorney, broker).
4. WHEN an Organization record is created or updated, THE Platform SHALL record the timestamp and preserve prior versions in an audit log.
5. IF an Organization name is submitted as an empty string, THEN THE Platform SHALL reject the request and return a descriptive validation error; IF the error message cannot be delivered due to a system failure, THEN THE Platform SHALL treat the delivery failure as a system error and not silently succeed.
6. THE Platform SHALL allow a single Organization to be associated with multiple Properties and multiple Owners simultaneously.

---

### Requirement 2: Internal Interaction Model

**User Story:** As a platform user, I want to log notes and calls against a property, lead, owner, or organization, so that I have a complete seller interaction history inside my platform.

#### Acceptance Criteria

1. THE Platform SHALL store Interaction records with at minimum: interaction type (note, call, email, meeting, other), body text, occurred-at timestamp, source (manual, hubspot_import), and associations to one or more of: Property, Lead, Owner, Organization, Contact.
2. WHEN a user submits a new Interaction, THE Platform SHALL require at least one association target (Property, Lead, Owner, Organization, or Contact) and reject submissions with no association.
3. WHEN a user submits a new Interaction, THE Platform SHALL require a non-empty body text and reject submissions where body text is absent or whitespace-only.
4. THE Platform SHALL allow an Interaction to be associated with multiple targets simultaneously (e.g., both a Property and an Owner).
5. IF an Interaction source is hubspot_import, THEN THE Platform SHALL preserve the original HubSpot engagement ID and raw payload alongside the Interaction record.
6. THE Platform SHALL allow Interactions to be retrieved in reverse chronological order for any given association target.

---

### Requirement 3: Internal Task Model

**User Story:** As a platform user, I want to create and track tasks tied to a property, lead, owner, or organization, so that I can manage follow-up actions without relying on HubSpot tasks.

#### Acceptance Criteria

1. THE Platform SHALL store Task records with at minimum: title, body text (optional), due date (optional), status (open, completed, cancelled), priority (high, medium, low), source (manual, hubspot_import), and associations to one or more of: Property, Lead, Owner, Organization.
2. WHEN a user marks a Task as completed, THE Platform SHALL record the completion timestamp.
3. WHEN a user submits a new Task, THE Platform SHALL require a non-empty title and reject submissions where the title is absent or whitespace-only.
4. IF a Task source is hubspot_import, THEN THE Platform SHALL preserve the original HubSpot task ID and raw payload alongside the Task record.
5. THE Platform SHALL allow Tasks to be filtered by status, priority, due date range, and association target.
6. WHEN a Task due date passes and the Task status is open, THE Platform SHALL immediately mark the Task as overdue and reflect that status in all subsequent query responses.

---

### Requirement 4: Property and Lead Timeline

**User Story:** As a platform user, I want to see a unified timeline of all interactions and tasks on a property, lead, or owner detail page, so that I can quickly understand the full history of a deal.

#### Acceptance Criteria

1. THE Platform SHALL expose a Timeline endpoint for each of: Property, Lead, and Owner, returning all associated Interactions and Tasks in reverse chronological order.
2. WHEN a Timeline is requested, THE Platform SHALL include both manually created records and HubSpot-imported records in the same ordered list.
3. WHEN a Timeline is requested, THE Platform SHALL include for each entry: entry type (interaction or task), subtype (note/call/email/task), occurred-at or due date, body text or title, source (manual or hubspot_import), and the HubSpot engagement ID if applicable.
4. THE Platform SHALL allow Timeline entries to be filtered by entry type, subtype, and date range.
5. WHILE a Property has no associated Interactions or Tasks, THE Platform SHALL return an empty Timeline list rather than an error.

---

### Requirement 5: Manual Note and Task Creation UI

**User Story:** As a platform user, I want to add notes and tasks directly from a property, lead, or owner detail page, so that I can capture new activity without leaving the context of the record I am working on.

#### Acceptance Criteria

1. THE Platform SHALL provide a UI control on Property, Lead, and Owner detail pages that allows a user to create a new Interaction of type note.
2. THE Platform SHALL provide a UI control on Property, Lead, and Owner detail pages that allows a user to create a new Task.
3. WHEN a user submits a new note or task from a detail page, THE Platform SHALL automatically associate the new record with the current Property, Lead, or Owner without requiring the user to re-select it.
4. WHEN a note or task is successfully created, THE Platform SHALL display the new entry in the Timeline on the same page without a page reload, regardless of device speed.
5. IF a note submission fails validation, THEN THE Platform SHALL display an inline error message identifying the specific validation failure.

---

### Requirement 6: HubSpot API Connection Configuration

**User Story:** As a platform user, I want to configure and test my HubSpot API connection inside the platform, so that I can verify access before running an import.

#### Acceptance Criteria

1. THE Platform SHALL provide an Import_Area in the UI where a user can enter and save a HubSpot Private App API token.
2. THE Platform SHALL store the HubSpot API token in an encrypted form and SHALL NOT return the raw token value in any API response; IF token encryption fails during storage, THEN THE Platform SHALL still protect API responses by ensuring the raw token is never returned.
3. WHEN a user triggers a connection test, THE Platform SHALL call the HubSpot API and return a success or failure status; a response received after 10 seconds SHALL still be treated as a success if the API call ultimately succeeds.
4. IF the HubSpot API returns an authentication error during a connection test, THEN THE Platform SHALL display a descriptive error message indicating the token is invalid or lacks required scopes.
5. THE Platform SHALL display the currently configured HubSpot account name and portal ID after a successful connection test.

---

### Requirement 7: HubSpot Raw Data Import

**User Story:** As a platform user, I want to import all HubSpot deals, contacts, companies, notes, calls, and tasks into my platform, so that I have a complete local copy of my HubSpot history.

#### Acceptance Criteria

1. THE Platform SHALL import HubSpot_Deal records including at minimum: deal ID, deal name, pipeline, stage, close date, amount, and all custom properties including PIN and lead source.
2. THE Platform SHALL import HubSpot_Contact records including at minimum: contact ID, first name, last name, email addresses, phone numbers, and associated deal IDs.
3. THE Platform SHALL import HubSpot_Company records including at minimum: company ID, company name, company type, phone, and associated deal IDs and contact IDs.
4. THE Platform SHALL import HubSpot_Note, HubSpot_Call, and HubSpot_Task engagement records including at minimum: engagement ID, type, created-at timestamp, last-modified timestamp, body text, and all associated object IDs (deals, contacts, companies).
5. THE Platform SHALL preserve the complete raw JSON payload for every imported HubSpot record in a dedicated raw storage column.
6. WHEN an import is triggered, THE Platform SHALL create an Import_Run record capturing: start time, object type being imported, total records fetched, records created, records skipped (duplicates), and final status (success, partial, failed).
7. WHEN an import completes, THE Platform SHALL display the Import_Run summary in the Import_Area.
8. THE Platform SHALL execute imports as background Celery_Worker tasks so that the UI remains responsive during long-running imports.

---

### Requirement 8: Duplicate Prevention on Re-Import

**User Story:** As a platform user, I want to re-run imports without creating duplicate records, so that I can safely refresh my local HubSpot data at any time.

#### Acceptance Criteria

1. WHEN a HubSpot_Deal is imported and a raw record with the same HubSpot deal ID already exists, THE Platform SHALL update the existing raw record rather than creating a new one; for any given HubSpot deal ID within a single import run, THE Platform SHALL either update or create, never both.
2. WHEN a HubSpot_Contact is imported and a raw record with the same HubSpot contact ID already exists, THE Platform SHALL update the existing raw record rather than creating a new one; for any given HubSpot contact ID within a single import run, THE Platform SHALL either update or create, never both.
3. WHEN a HubSpot_Company is imported and a raw record with the same HubSpot company ID already exists, THE Platform SHALL update the existing raw record rather than creating a new one; for any given HubSpot company ID within a single import run, THE Platform SHALL either update or create, never both.
4. WHEN a HubSpot engagement (note, call, or task) is imported and a raw record with the same HubSpot engagement ID already exists, THE Platform SHALL update the existing raw record rather than creating a new one; for any given engagement ID within a single import run, THE Platform SHALL either update or create, never both.
5. THE Platform SHALL record the count of skipped (duplicate) records in the Import_Run summary for each object type, showing zero when no duplicates are encountered rather than omitting the field.
6. WHEN a re-import updates an existing raw record, THE Platform SHALL preserve the original first-imported timestamp and record the last-updated timestamp separately.

---

### Requirement 9: HubSpot Backup Export

**User Story:** As a platform user, I want to export a full backup of all imported HubSpot data, so that I have an offline archive before I stop using HubSpot.

#### Acceptance Criteria

1. THE Platform SHALL provide an export function in the Import_Area that produces a downloadable archive containing all imported raw HubSpot records.
2. THE Backup_Export SHALL include separate sections for: deals, contacts, companies, notes, calls, and tasks.
3. THE Backup_Export SHALL be produced in JSON format with each record containing its raw HubSpot payload and the Platform import metadata (import run ID, first imported at, last updated at).
4. WHEN a Backup_Export is requested, THE Platform SHALL generate the file as a background Celery_Worker task and notify the user only after the export is successfully generated; IF the background task fails, THE Platform SHALL not send a notification and SHALL display the failure status in the Import_Area.
5. THE Platform SHALL allow the user to download the most recent Backup_Export without re-generating it if no new imports have occurred since the last export.

---

### Requirement 10: HubSpot Deal-to-Property Matching

**User Story:** As a platform user, I want HubSpot deals to be automatically matched to existing properties and leads in my platform, so that imported history attaches to the right records.

#### Acceptance Criteria

1. WHEN a HubSpot_Deal is processed for matching, THE Matcher SHALL attempt matches in this priority order: (1) PIN match, (2) Normalized_Address match against the deal name field, (3) Normalized_Address match against the HubSpot address custom property if present.
2. WHEN a PIN match is found, THE Matcher SHALL assign Match_Confidence of HIGH and create the Match without requiring manual review.
3. WHEN only a Normalized_Address match is found and no PIN match exists, THE Matcher SHALL assign Match_Confidence of MEDIUM and add the Match to the Review_Queue for user confirmation.
4. WHEN no PIN or address match is found, THE Matcher SHALL assign Match_Confidence of UNMATCHED, create a placeholder Property record marked with source hubspot_import and status needs_review, and add it to the Review_Queue; IF placeholder creation fails, THE Matcher SHALL still add the item to the Review_Queue; IF adding to the Review_Queue fails, THE Matcher SHALL still create the placeholder Property record.
5. THE Matcher SHALL normalize addresses by converting to uppercase, expanding common abbreviations (ST→STREET, AVE→AVENUE, BLVD→BOULEVARD, DR→DRIVE, RD→ROAD, CT→COURT, LN→LANE, PL→PLACE), and removing punctuation before comparison.
6. THE Platform SHALL never overwrite an existing Property's PIN, address, or lead source with HubSpot data without explicit user confirmation in the Review_Queue.

---

### Requirement 11: HubSpot Contact-to-Owner Matching

**User Story:** As a platform user, I want HubSpot contacts to be matched to existing owners in my platform, so that seller contact history attaches to the right owner records.

#### Acceptance Criteria

1. WHEN a HubSpot_Contact is processed for matching, THE Matcher SHALL attempt matches in this priority order: (1) email address match, (2) phone number match (normalized to digits only), (3) full name match combined with an associated deal's property match.
2. WHEN an email or phone match is found, THE Matcher SHALL assign Match_Confidence of HIGH.
3. WHEN only a name-plus-property-association match is found, THE Matcher SHALL assign Match_Confidence of MEDIUM and add the Match to the Review_Queue regardless of the assigned confidence level.
4. WHEN no match is found, THE Matcher SHALL create a new Owner record populated from the HubSpot_Contact data, mark it with source hubspot_import, and link it to any matched Properties via the deal association.
5. THE Platform SHALL never merge two existing Owner records automatically; merges SHALL require explicit user action in the Review_Queue.

---

### Requirement 12: HubSpot Company-to-Organization Matching

**User Story:** As a platform user, I want HubSpot companies to be matched to existing organizations in my platform, so that entity relationships are preserved.

#### Acceptance Criteria

1. WHEN a HubSpot_Company is processed for matching, THE Matcher SHALL attempt matches in this priority order: (1) exact normalized name match, (2) normalized name match combined with an associated deal's property match.
2. WHEN an exact normalized name match is found, THE Matcher SHALL assign Match_Confidence of MEDIUM and add the Match to the Review_Queue, because company names are not unique identifiers.
3. WHEN no match is found, THE Matcher SHALL create a new Organization record populated from the HubSpot_Company data and mark it with source hubspot_import.
4. THE Platform SHALL link matched or created Organizations to Properties and Owners based on the HubSpot deal-company and contact-company association data.

---

### Requirement 13: Manual Review Queue

**User Story:** As a platform user, I want a review queue that shows me all uncertain or unmatched HubSpot records, so that I can confirm, correct, or dismiss each match manually.

#### Acceptance Criteria

1. THE Platform SHALL provide a Review_Queue view in the Import_Area listing all Matches with Match_Confidence of MEDIUM, LOW, or UNMATCHED.
2. WHEN a user reviews a Match in the Review_Queue, THE Platform SHALL display: the HubSpot record summary, the proposed internal record match (if any), the match confidence level, and the matching criteria that were used.
3. THE Platform SHALL allow a user to confirm a proposed Match, reject a proposed Match and link to a different internal record, or mark a Match as a new record (no match exists).
4. WHEN a user confirms a Match, THE Platform SHALL create the association and remove the item from the Review_Queue; IF association creation fails, THE Platform SHALL keep the item in the Review_Queue and display an error to the user.
5. WHEN a user rejects a Match and selects a different internal record, THE Platform SHALL create the association to the selected record and remove the item from the Review_Queue.
6. THE Platform SHALL display a count of pending Review_Queue items in the Import_Area navigation.
7. THE Platform SHALL allow Review_Queue items to be filtered by object type (deal, contact, company) and Match_Confidence level.

---

### Requirement 14: Activity Conversion — Notes and Calls to Interactions

**User Story:** As a platform user, I want imported HubSpot notes and calls to become internal Interaction records attached to the right property, lead, owner, or organization, so that my platform timeline reflects the full seller history.

#### Acceptance Criteria

1. WHEN a HubSpot_Note is converted, THE Platform SHALL create an Interaction of type note with: body text from the HubSpot note body, occurred-at from the HubSpot engagement created-at timestamp, source set to hubspot_import, and the original HubSpot engagement ID preserved.
2. WHEN a HubSpot_Call is converted, THE Platform SHALL create an Interaction of type call with: body text from the HubSpot call body or disposition, occurred-at from the HubSpot engagement created-at timestamp, source set to hubspot_import, and the original HubSpot engagement ID preserved.
3. WHEN converting a HubSpot engagement, THE Platform SHALL attach the resulting Interaction to all internal records that correspond to the HubSpot engagement's associated deal IDs, contact IDs, and company IDs; IF Interaction creation fails, THE Platform SHALL skip all attachment attempts for that engagement and log the failure.
4. IF a HubSpot engagement has no matched internal record associations, THEN THE Platform SHALL still create the Interaction and mark it as orphaned, pending manual association in the Review_Queue.
5. THE Platform SHALL not create duplicate Interactions for the same HubSpot engagement ID on re-import.
6. WHEN converting a HubSpot_Task, THE Platform SHALL attach the resulting Task to whatever internal records exist for the associated deal IDs, contact IDs, and company IDs, even if some association types are missing.

---

### Requirement 15: Activity Conversion — Tasks

**User Story:** As a platform user, I want imported HubSpot tasks to become internal Task records, so that I can see and act on historical follow-up items inside my platform.

#### Acceptance Criteria

1. WHEN a HubSpot_Task is converted, THE Platform SHALL create a Task with: title from the HubSpot task subject, body text from the HubSpot task body (if present), due date from the HubSpot task due date (if present), status mapped from HubSpot task status (COMPLETED→completed, all others→open), source set to hubspot_import, and the original HubSpot task ID preserved.
2. WHEN converting a HubSpot_Task, THE Platform SHALL attach the resulting Task to whatever internal records exist for the associated deal IDs, contact IDs, and company IDs, even if some association types are missing.
3. THE Platform SHALL not create duplicate Tasks for the same HubSpot task ID on re-import.
4. WHEN a converted Task has a due date in the past and status is open, THE Platform SHALL mark it as overdue in query responses.

---

### Requirement 16: HubSpot Signal Extraction

**User Story:** As a platform user, I want the platform to extract meaningful signals from imported HubSpot engagement history, so that lead scoring and recommended actions reflect what actually happened with each seller.

#### Acceptance Criteria

1. THE Platform SHALL extract HubSpot_Signals from the body text and metadata of imported HubSpot_Note, HubSpot_Call, and HubSpot_Task records using keyword and phrase matching against a configurable signal dictionary.
2. THE Platform SHALL recognize and assign the following HubSpot_Signal types: PRIOR_INTERACTION_EXISTS, PRIOR_RESPONSE_EXISTS, PRIOR_WARM_CONVERSATION, ASKING_PRICE_GIVEN, APPOINTMENT_OCCURRED, OFFER_PREVIOUSLY_SENT, SELLER_SAID_MAYBE_LATER, SELLER_NOT_INTERESTED, WRONG_NUMBER, DO_NOT_CONTACT, FOLLOW_UP_OVERDUE, PRIOR_LEAD_SOURCE_KNOWN.
3. WHEN a HubSpot_Signal of type DO_NOT_CONTACT or WRONG_NUMBER is extracted, THE Platform SHALL set the Suppression_Flag on the associated Lead or Owner record.
4. WHEN a HubSpot_Signal of type FOLLOW_UP_OVERDUE is assigned, THE Platform SHALL set it based on the presence of an open Task with a past due date; WHEN engagement body text contains phrases suggesting follow-up is overdue but no overdue Task exists, THE Platform SHALL flag the engagement for manual review rather than automatically assigning the FOLLOW_UP_OVERDUE signal.
5. THE Platform SHALL store extracted HubSpot_Signals as structured records linked to the Lead, with the source engagement ID and extraction timestamp preserved.
6. THE Platform SHALL allow the signal keyword dictionary to be updated without requiring a code deployment.

---

### Requirement 17: Lead Scoring Integration with HubSpot Signals

**User Story:** As a platform user, I want HubSpot-derived signals to influence lead scores and recommended actions, so that previously warm or suppressed leads are treated appropriately.

#### Acceptance Criteria

1. WHEN a Lead has a HubSpot_Signal of PRIOR_WARM_CONVERSATION or APPOINTMENT_OCCURRED, THE Lead_Scorer SHALL apply a positive score adjustment to the lead score.
2. WHEN a Lead has a HubSpot_Signal of SELLER_NOT_INTERESTED or DO_NOT_CONTACT, THE Lead_Scorer SHALL apply a negative score adjustment sufficient to move the lead below the active follow-up threshold.
3. WHEN a Lead has a HubSpot_Signal of SELLER_SAID_MAYBE_LATER, THE Lead_Scorer SHALL set the recommended action to FOLLOW_UP_LATER rather than CONTACT_NOW.
4. WHEN a Lead has a HubSpot_Signal of OFFER_PREVIOUSLY_SENT, THE Lead_Scorer SHALL set the recommended action to REVISIT_OFFER.
5. WHEN a Lead has multiple HubSpot_Signals that affect the recommended action, THE Lead_Scorer SHALL apply all applicable score adjustments and SHALL use the most recently extracted signal to determine the final recommended action.
6. WHEN a Lead has a Suppression_Flag set, THE Lead_Scorer SHALL exclude the lead from active outreach lists regardless of its numeric score; WHEN a Suppression_Flag is set on a Lead that is already part of an active campaign, THE Platform SHALL immediately remove the lead from that campaign.
7. THE Platform SHALL recalculate affected lead scores automatically after HubSpot signal extraction completes for an import run.

---

### Requirement 18: HubSpot-Derived Lead Views

**User Story:** As a platform user, I want pre-built filtered views of my leads based on HubSpot import signals, so that I can immediately act on the most valuable imported history.

#### Acceptance Criteria

1. THE Platform SHALL provide a view showing all Leads with HubSpot_Signal PRIOR_WARM_CONVERSATION or APPOINTMENT_OCCURRED, labeled "Previously Warm Leads."
2. THE Platform SHALL provide a view showing all Leads imported from HubSpot with Match_Confidence UNMATCHED or status needs_review, labeled "Needs Review."
3. THE Platform SHALL provide a view showing all Leads with an open overdue Task, labeled "Follow-Up Overdue."
4. THE Platform SHALL provide a view showing all Leads with HubSpot_Signal PRIOR_INTERACTION_EXISTS but no open Task and no future scheduled Interaction, labeled "No Current Next Action."
5. THE Platform SHALL provide a view showing all Leads or Owners with Suppression_Flag set, labeled "Do Not Contact"; THE Platform SHALL include a Lead in this view when either the Lead itself or any of its associated Owners has a Suppression_Flag set.
6. THE Platform SHALL provide a view showing all HubSpot-imported placeholder Properties with no confirmed internal Property match, labeled "Missing Property Match."
7. WHEN a Lead's signals or status change, THE Platform SHALL update its membership in these views within the same request cycle or the next background scoring cycle.

---

### Requirement 19: Read-Only HubSpot Import (No Write-Back)

**User Story:** As a platform user, I want the HubSpot import to be strictly read-only, so that I do not accidentally modify my HubSpot data during the migration.

#### Acceptance Criteria

1. THE Platform SHALL only call HubSpot API endpoints that use the HTTP GET method during import operations.
2. THE Platform SHALL not call any HubSpot API endpoint that creates, updates, or deletes HubSpot records.
3. IF a code path attempts to call a non-GET HubSpot API endpoint, THEN THE Platform SHALL raise an exception and log the attempt without executing the call.
4. THE Platform SHALL display a visible "Read-Only Mode" indicator in the Import_Area to confirm that no data is being written to HubSpot.

---

### Requirement 20: Import Progress and Error Reporting

**User Story:** As a platform user, I want to see real-time progress and error details during an import, so that I know what is happening and can diagnose problems.

#### Acceptance Criteria

1. WHEN an import is running, THE Platform SHALL display a progress indicator in the Import_Area showing the current object type being imported and the count of records processed so far.
2. WHEN an import encounters a non-fatal error for an individual record (e.g., malformed data), THE Platform SHALL log the error, skip the record, increment an error count, and continue importing remaining records.
3. WHEN an import encounters a fatal error (e.g., API authentication failure, network timeout after retries), THE Platform SHALL immediately stop the import, mark the Import_Run as failed, and record the error message without processing any further records.
4. WHEN an import completes, THE Platform SHALL update the Import_Run status from RUNNING to success or partial before displaying the Import_Run summary, and SHALL display the summary only after the status update is confirmed; THE summary SHALL include total fetched, created, updated, skipped, and errored counts per object type.
5. THE Platform SHALL retain Import_Run records indefinitely so that the user can review the history of all past imports.

---

### Requirement 21: Mobile Quick-Add Workflow (Roadmap)

**User Story:** As a platform user in the field, I want to quickly add a property I discover while walking or driving, so that I can capture it for later research without relying on HubSpot mobile.

#### Acceptance Criteria

1. WHERE the mobile quick-add feature is enabled, THE Platform SHALL allow a user to create a new Property and Lead by entering a street address from a mobile browser.
2. WHERE the mobile quick-add feature is enabled, THE Platform SHALL allow a user to attach a photo to the new Property record at creation time.
3. WHERE the mobile quick-add feature is enabled, THE Platform SHALL allow a user to add a quick note to the new Property record at creation time.
4. WHERE the mobile quick-add feature is enabled, THE Platform SHALL set the lead source to WALK_BY on records created through the quick-add workflow.
5. WHERE the mobile quick-add feature is enabled, THE Platform SHALL allow a user to set a priority level (high, medium, low) on the new Lead at creation time.
6. WHERE the mobile quick-add feature is enabled, THE Platform SHALL queue the new Property for background enrichment and research rather than blocking the creation flow on enrichment completion.
7. WHERE the mobile quick-add feature is enabled, THE Platform SHALL complete the property and lead creation within 3 seconds of form submission on a standard mobile connection.

---

### Requirement 22: Data Integrity — No Overwrite Without Review

**User Story:** As a platform user, I want imported HubSpot data to never silently overwrite better internal data, so that my platform records remain trustworthy.

#### Acceptance Criteria

1. WHEN a HubSpot import produces a Match to an existing internal Property, THE Platform SHALL not overwrite the existing Property's PIN, normalized address, lead score, or lead status without explicit user confirmation.
2. WHEN a HubSpot import produces a Match to an existing internal Owner, THE Platform SHALL not overwrite the existing Owner's name, phone numbers, or email addresses without explicit user confirmation.
3. WHEN a HubSpot import produces a Match to an existing internal Organization, THE Platform SHALL not overwrite the existing Organization's name or type without explicit user confirmation.
4. THE Platform SHALL display a side-by-side comparison of the existing internal value and the incoming HubSpot value in the Review_Queue for any field where a conflict is detected.
5. WHEN a user confirms an overwrite in the Review_Queue, THE Platform SHALL record the prior value in the audit log before applying the change.

---

### Requirement 23: HubSpot Write-Back (Deferred — Out of Scope for MVP)

**User Story:** As a platform user, I may want to push high-value leads or notes back to HubSpot in the future, so that I can use HubSpot as a secondary reference if needed.

#### Acceptance Criteria

1. WHERE the HubSpot write-back feature is enabled, THE Platform SHALL allow a user to push a selected Lead record to HubSpot as a Deal.
2. WHERE the HubSpot write-back feature is enabled, THE Platform SHALL allow a user to push a selected Interaction record to HubSpot as a Note engagement.
3. WHERE the HubSpot write-back feature is enabled, THE Platform SHALL allow a user to push a selected Task record to HubSpot as a Task engagement.
4. WHERE the HubSpot write-back feature is enabled, THE Platform SHALL require explicit user confirmation before writing any record to HubSpot; WHERE a bulk write operation is initiated, THE Platform SHALL allow a single confirmation to cover all records in the batch.
5. WHERE the HubSpot write-back feature is enabled, THE Platform SHALL log every write operation to HubSpot in an audit record.

> **Note:** This requirement is explicitly deferred and out of scope for the MVP. It is documented here to preserve the design intent for a future phase.
