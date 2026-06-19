# Requirements Document

## Introduction

The platform currently has two separate detail views for the same lead/property record:

1. **PropertyDetailPage** — reached from the Properties list (`/properties`) via a side drawer "Full Profile" button, at the route `/properties/:leadId`. Provides a tabbed view with Activity, Info, Score, Enrichment, Marketing, Analysis, and Contacts tabs, plus a sticky task sidebar.

2. **LeadCommandCenter** — reached from all Work Queue tables by clicking a lead name, at the route `/leads/:id/command-center`. Provides a CRM-focused two-column layout with queue context banners, recommended action panel, tasks, log note/call forms, and a compact property sidebar.

This feature consolidates the two views into a single **Unified Lead Command Center** that serves every entry point in the application. The unified page must combine the richest capabilities of both existing views — the full tabbed property data from `PropertyDetailPage` and the CRM workflow features from `LeadCommandCenter` — so that agents always work in one consistent place regardless of how they navigated there.

---

## Glossary

- **Lead**: A property owner record stored in the `leads` table, identified by a numeric ID. Contains property details, owner contact info, and CRM tracking fields.
- **Unified_Command_Center**: The single consolidated detail page for a lead, located at `/leads/:id`. The canonical destination for all lead navigation throughout the app.
- **Entry_Point**: Any UI element that navigates to a lead detail view — including the Properties list row click, Work Queue row clicks, Work Queue "Open lead detail" icon buttons, and the Global Search Bar lead results.
- **PropertyDetailPage**: The existing tabbed detail component at `/properties/:leadId` — to be retired once the Unified_Command_Center is in place.
- **LeadCommandCenter**: The existing CRM-focused detail component at `/leads/:id/command-center` — to be merged into the Unified_Command_Center.
- **Queue_Context_Banner**: The alert strip that shows which work queue(s) a lead belongs to and why, including a link back to that queue.
- **Activity_Panel**: The main scrollable left-column content area showing the log note form, log call form, and chronological timeline of all interactions.
- **Property_Sidebar**: The sticky right-column panel showing condensed property details, contact info, owner info, skip trace, mailer history, marketing lists, source metadata, and scores.
- **Tab_Panel**: A secondary tabbed section within the Unified_Command_Center giving access to deeper data: Info, Score, Enrichment, Marketing, Analysis, and Contacts.
- **Canonical_Route**: The single authoritative URL pattern `/leads/:id` that all entry points must navigate to after this feature is implemented.
- **Legacy_Route**: An older URL pattern (`/properties/:leadId`, `/leads/:id/command-center`) that must redirect to the Canonical_Route without breaking bookmarks or external links.

---

## Requirements

### Requirement 1: Canonical Route

**User Story:** As an agent, I want every lead detail link to go to the same URL, so that I can bookmark, share, and navigate back to lead records consistently.

#### Acceptance Criteria

1. THE Unified_Command_Center SHALL be served at the route `/leads/:id`, where `:id` is a positive integer.
2. WHEN a user navigates to `/properties/:leadId` where `:leadId` is a positive integer, THE Router SHALL replace the history entry with a redirect to `/leads/:leadId`.
3. WHEN a user navigates to `/leads/:id/command-center` where `:id` is a positive integer, THE Router SHALL replace the history entry with a redirect to `/leads/:id`.
4. IF the `:id` segment in the URL is not a positive integer, THEN THE Unified_Command_Center SHALL display an error message stating the ID is invalid and SHALL render a link back to `/properties`.
5. IF the `:id` is a valid positive integer but no matching lead record exists, THEN THE Unified_Command_Center SHALL display a "Lead not found" error message and SHALL render a link back to `/properties`.

---

### Requirement 2: Entry Point Consolidation — Properties List

**User Story:** As an agent browsing the Properties list, I want a single click to open the full lead detail, so that I don't have to use a two-step drawer then "Full Profile" flow.

#### Acceptance Criteria

1. WHEN a user clicks a row in the Properties list grid and the row data contains a valid lead id, THE Properties_List SHALL navigate to `/leads/:id` for that lead.
2. THE Properties_List SHALL NOT render the side drawer component in the DOM.
3. IF a row in the Properties list grid does not contain a valid lead id, THEN THE Properties_List SHALL NOT navigate and SHALL display no error to the user.

---

### Requirement 3: Entry Point Consolidation — Work Queues

**User Story:** As an agent working a queue, I want clicking a lead name or the open-detail icon to take me to the Unified_Command_Center, so that I have access to all property and CRM data without switching contexts.

#### Acceptance Criteria

1. WHEN a user clicks a lead name link in any Work Queue table, THE Queue_Table SHALL navigate to `/leads/:id` for that lead.
2. WHEN a user clicks the "Open lead detail" icon button in any Work Queue table, THE Queue_Table SHALL navigate to `/leads/:id` for that lead.
3. WHEN a user clicks anywhere on a Work Queue table row outside of the lead name link, the open-detail icon button, checkbox inputs, and any other registered action buttons, THE Queue_Table SHALL navigate to `/leads/:id` for that lead.

---

### Requirement 4: Entry Point Consolidation — Global Search

**User Story:** As an agent using global search, I want lead results to open the Unified_Command_Center, so that I land in the same place as all other navigation paths.

#### Acceptance Criteria

1. WHEN a user selects a lead result from the Global Search Bar dropdown, THE Global_Search_Bar SHALL navigate to `/leads/:id` for the selected lead.
2. THE Backend_Search_Service SHALL return `nav_path` values in the format `/leads/{id}` for all lead search results; IF a `nav_path` value is absent or does not match the `/leads/{id}` pattern, THE Global_Search_Bar SHALL fall back to constructing the path as `/leads/{id}` using the result's id field.
3. WHEN a user presses Enter while a lead result is keyboard-focused in the dropdown, THE Global_Search_Bar SHALL navigate to `/leads/:id` for the focused lead; IF no result is focused when Enter is pressed, THE Global_Search_Bar SHALL take no navigation action.

---

### Requirement 5: Unified Page Layout

**User Story:** As an agent, I want the Unified_Command_Center to show me both CRM workflow tools and full property data in one view, so that I never have to navigate between two different pages for the same record.

#### Acceptance Criteria

1. THE Unified_Command_Center SHALL display the lead owner name, property address, lead score, and lead status in a header section that remains fixed at the top of the viewport regardless of scroll position.
2. THE Unified_Command_Center SHALL display a Queue_Context_Banner for each work queue the lead currently belongs to, including the queue name (maximum 200 characters), the reason for membership, and a link to that queue; IF the lead belongs to no queues, THE Unified_Command_Center SHALL display no Queue_Context_Banner.
3. WHEN a user submits an action via the Recommended_Action_Panel, THE Unified_Command_Center SHALL record the action against the lead and update the Recommended_Action_Panel to display the next recommended action.
4. THE Unified_Command_Center SHALL display an Activity_Panel containing a Log Note form, a Log Call form, and a timeline of logged interactions paginated at 20 entries per page with navigation controls.
5. THE Unified_Command_Center SHALL display a Tab_Panel with the following tabs in order: Info, Score, Enrichment, Marketing, Analysis, and Contacts.
6. THE Unified_Command_Center SHALL display a Property_Sidebar that is sticky and remains visible while the agent scrolls through main content.
7. THE Unified_Command_Center SHALL display a Tasks panel showing all open tasks for the lead, allowing the agent to add new tasks and mark existing tasks as complete.
8. WHILE the lead data is loading, THE Unified_Command_Center SHALL display a loading indicator and SHALL NOT render any lead data panels; THE Unified_Command_Center SHALL dismiss the loading indicator only after all data panels have rendered their received data and no panel is in a pending state.
9. IF the lead data fetch fails, THEN THE Unified_Command_Center SHALL display an error message indicating the nature of the failure and a link to return to `/properties`.

---

### Requirement 6: Lead Status Management

**User Story:** As an agent, I want to update a lead's CRM status from the detail page with an optional reason, so that the record reflects the current state of my outreach.

#### Acceptance Criteria

1. THE Unified_Command_Center SHALL display a status selector showing the lead's current status; the selector SHALL NOT include the lead's current status as a selectable option.
2. WHEN a user selects a new status from the selector, THE Unified_Command_Center SHALL display a confirmation panel with an optional free-text reason field (maximum 500 characters) before persisting the change.
3. WHILE a status-change submission is in progress, THE Unified_Command_Center SHALL disable the confirmation panel's submit control to prevent duplicate submissions.
4. WHEN a user confirms a status change and the backend call succeeds, THE Unified_Command_Center SHALL close the confirmation panel and refresh the lead data without a full page reload.
5. IF the status-update API call fails, THEN THE Unified_Command_Center SHALL display an inline error message within the confirmation panel and SHALL re-enable the submit control so the user can retry or cancel.
6. WHEN a user cancels a pending status change, THE Unified_Command_Center SHALL dismiss the confirmation panel and restore the status selector to the lead's current persisted status.

---

### Requirement 7: Task Management

**User Story:** As an agent, I want to create and complete tasks for a lead from the detail page, so that I can track follow-up actions without leaving the lead record.

#### Acceptance Criteria

1. THE Unified_Command_Center SHALL display all open tasks for the lead when the page loads.
2. WHEN a user creates a new task, THE Unified_Command_Center SHALL add the task to the open tasks list immediately and SHALL persist it via the backend task-creation endpoint.
3. WHEN a user marks a task as complete, THE Unified_Command_Center SHALL remove it from the open tasks list immediately and SHALL persist the completion via the backend task-completion endpoint.
4. IF the task-completion API call fails, THEN THE Unified_Command_Center SHALL restore the task to the open tasks list and log the error to the console.

---

### Requirement 8: Activity Logging

**User Story:** As an agent, I want to log notes and calls for a lead from the detail page, so that a complete interaction history is maintained.

#### Acceptance Criteria

1. WHEN a user submits a note via the Log Note form, THE Unified_Command_Center SHALL add the new timeline entry to the top of the Activity_Panel timeline and SHALL persist it via the backend timeline endpoint.
2. WHEN a user submits a call log via the Log Call form, THE Unified_Command_Center SHALL add the new timeline entry to the top of the Activity_Panel timeline and SHALL persist it via the backend timeline endpoint.
3. WHEN a user requests to load more timeline entries, THE Unified_Command_Center SHALL fetch the next page from the backend timeline endpoint and append the entries to the existing list.

---

### Requirement 9: Property Data Tabs

**User Story:** As an agent, I want to access full property data, scores, enrichment records, and marketing history from the lead detail page, so that I have complete context when making outreach decisions.

#### Acceptance Criteria

1. WHEN a user selects the Info tab, THE Tab_Panel SHALL display all property detail fields grouped by category: Property Details, Contacts, Contact Information, Mailing Information, Research & Tracking, Mailing Campaigns, and Metadata.
2. WHEN a user selects the Score tab, THE Tab_Panel SHALL display the latest score breakdown and score history timeline; IF no score exists, THE Tab_Panel SHALL display a prompt to generate the first score.
3. WHEN a user selects the Enrichment tab, THE Tab_Panel SHALL display a table of all enrichment records with source, status, date, and details columns.
4. WHEN a user selects the Marketing tab, THE Tab_Panel SHALL display a table of all marketing list memberships with list name, outreach status, and added date columns.
5. WHEN a user selects the Analysis tab, THE Tab_Panel SHALL display a linked analysis session summary if one exists, or buttons to start a Single-Family or Multifamily analysis if none exists.
6. WHEN a user selects the Contacts tab, THE Tab_Panel SHALL display the ContactsSection component allowing the user to view and manage linked contacts for the property.

---

### Requirement 10: Back Navigation

**User Story:** As an agent, I want a back button that returns me to the page I came from, so that I can continue working my queue without losing context.

#### Acceptance Criteria

1. THE Unified_Command_Center SHALL display a back button in the header area.
2. WHEN a user clicks the back button, THE Unified_Command_Center SHALL navigate to the previous location in the browser history using `navigate(-1)`.

---

### Requirement 11: Property Sidebar Content

**User Story:** As an agent, I want key contact info and property details always visible on the side, so that I can reference them while logging notes or managing tasks without scrolling.

#### Acceptance Criteria

1. THE Property_Sidebar SHALL display the primary owner name, all available phone numbers with click-to-call `tel:` links and one-click copy buttons, and all available email addresses with click-to-email `mailto:` links and one-click copy buttons.
2. THE Property_Sidebar SHALL display property details including address, property type, beds/baths, square footage, year built, lot size, units, zoning, assessor PIN, tax bill, and last sale date.
3. THE Property_Sidebar SHALL display source and metadata fields including source, lead category, data source, date identified, date added to HubSpot, last HubSpot sync date, last contact date, and follow-up date.
4. THE Property_Sidebar SHALL display the lead score and data completeness score.
5. WHEN the screen width is below the large (lg) breakpoint, THE Property_Sidebar SHALL be hidden to preserve space for the main content area.

---

### Requirement 12: Data Loading Strategy

**User Story:** As an agent, I want the page to load quickly and avoid redundant network requests, so that I can move efficiently between leads.

#### Acceptance Criteria

1. THE Unified_Command_Center SHALL fetch command center data from the `/api/leads/:id/command-center` endpoint once per mount and share the result across the Activity_Panel, Tasks panel, and Property_Sidebar.
2. THE Unified_Command_Center SHALL fetch full property detail data from the `/api/leads/:id` endpoint once per mount and share the result across all Tab_Panel tabs.
3. WHEN command center data or property detail data is already in the React Query cache and is not stale, THE Unified_Command_Center SHALL use the cached data without issuing a new network request.
4. WHEN a task is completed or a status is changed, THE Unified_Command_Center SHALL invalidate the `commandCenter` query key so the next mount or explicit refresh fetches fresh data.

---

### Requirement 13: Retirement of Legacy Views

**User Story:** As a developer, I want the old split-view routes to be retired cleanly, so that the codebase does not maintain two diverging detail implementations.

#### Acceptance Criteria

1. THE Router SHALL register redirect rules for `/properties/:leadId` → `/leads/:leadId` and `/leads/:id/command-center` → `/leads/:id` in the same deployment as the Unified_Command_Center is made the primary route, so that no partially migrated state exists where redirects are present but legacy components are still active.
2. THE Properties_List SHALL remove the `onLeadSelect` prop callback and all code that opens the contacts side drawer.
3. WHEN all entry points have been updated to the Canonical_Route, THE PropertyDetailPage component file SHALL be removed from the codebase.
4. WHEN all entry points have been updated to the Canonical_Route, THE LeadCommandCenter component file SHALL be removed from the codebase OR consolidated as the implementation backing the Unified_Command_Center.
