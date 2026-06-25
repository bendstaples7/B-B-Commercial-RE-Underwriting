# Requirements Document

## Introduction

A global search bar embedded in the application's top header (AppBar) that allows users to search across all their data from a single entry point. The primary use cases are finding a lead/property owner by first name and finding a property by street address (e.g. a house number). Results surface leads from the lead management database and analysis sessions tied to property addresses, and clicking a result navigates directly to the relevant record.

## Glossary

- **Search_Bar**: The input control rendered inside the MUI AppBar at the top of every authenticated page.
- **Search_Service**: The Flask backend endpoint that receives a query string and returns ranked results.
- **Search_Result**: A single matched record returned by the Search_Service, tagged with its result type and a navigation target.
- **Lead**: A property owner record stored in the `leads` table (`Property` model), containing owner name, property address, contact info, and lead score.
- **Analysis_Session**: A stateful property analysis workflow session stored in the `analysis_sessions` table, tied to a property address via its linked `PropertyFacts` record.
- **Query**: The text the user types into the Search_Bar, trimmed of leading and trailing whitespace.
- **Admin_User**: An authenticated user whose JWT contains the `is_admin: true` claim (mapped to `g.is_admin = True` in the backend).
- **Regular_User**: An authenticated user whose JWT does not contain `is_admin: true` (`g.is_admin = False`).

---

## Requirements

### Requirement 1: Search Bar Placement

**User Story:** As a real estate investor, I want a search bar always visible in the top header, so that I can start a search from anywhere in the application without navigating to a dedicated search page.

#### Acceptance Criteria

1. THE Search_Bar SHALL be rendered inside the MUI AppBar Toolbar on every authenticated page.
2. THE Search_Bar SHALL be positioned in the right portion of the AppBar Toolbar on all screen sizes at or above the MUI `sm` breakpoint.
3. WHILE the viewport is below the MUI `sm` breakpoint, THE Search_Bar SHALL be collapsed to a single icon button (magnifying glass) in the Toolbar.
4. WHEN the user clicks or taps the icon button in the collapsed state, THE Search_Bar SHALL expand to fill the full width of the Toolbar inline, replacing other Toolbar content, and SHALL receive focus automatically.
5. WHEN the expanded mobile Search_Bar loses focus and the Query is empty, THE Search_Bar SHALL collapse back to the icon button state.
6. IF the Search_Bar is empty and not focused, THEN THE Search_Bar SHALL display placeholder text of "Search leads, addresses…".

---

### Requirement 2: Query Input Behavior

**User Story:** As a user, I want the search bar to feel responsive as I type, so that I get results quickly without having to press Enter.

#### Acceptance Criteria

1. WHEN the user types a Query of 2 or more characters, THE Search_Bar SHALL dispatch a search request to the Search_Service within 300 ms of the last keystroke (debounced input).
2. WHEN the Query length drops below 2 characters, THE Search_Bar SHALL clear any displayed results, cancel any in-flight search request, and SHALL NOT dispatch a new search request.
3. WHEN the user presses the Escape key while the Search_Bar is focused, THE Search_Bar SHALL clear the Query and cancel any in-flight search request.
4. WHEN the user presses the Escape key while the Search_Bar is focused, THE Search_Bar SHALL close the results dropdown and remove focus from the input.
5. THE Search_Bar SHALL reject input beyond 200 characters such that the 201st character is not entered into the field.
6. WHEN a search response arrives for a Query that is no longer the current Query value, THE Search_Bar SHALL discard that response and SHALL NOT render its results.

---

### Requirement 3: Backend Search Endpoint

**User Story:** As a developer, I want a dedicated search API endpoint, so that the frontend can retrieve matched records with a single request.

#### Acceptance Criteria

1. THE Search_Service SHALL expose a `GET /api/search` endpoint that accepts a `q` query parameter containing the Query string.
2. IF a request is received with no `q` parameter, THEN THE Search_Service SHALL return HTTP 400 with a JSON error body containing a `message` field.
3. IF a request is received with a `q` parameter of fewer than 2 characters (after trimming whitespace), THEN THE Search_Service SHALL return HTTP 400 with a JSON error body containing a `message` field.
4. IF a request is received with a `q` parameter longer than 200 characters, THEN THE Search_Service SHALL return HTTP 400 with a JSON error body containing a `message` field.
5. WHEN a request is received with a valid `q` parameter, THE Search_Service SHALL query the `leads` table for records where `owner_first_name`, `owner_last_name`, or `property_street` contain the Query string (case-insensitive, partial match).
6. WHEN a request is received with a valid `q` parameter, THE Search_Service SHALL query the `analysis_sessions` table (via the linked `PropertyFacts` record) for sessions where the property address contains the Query string (case-insensitive, partial match).
7. THE Search_Service SHALL apply ownership scoping to all results as defined in Requirement 9.
8. THE Search_Service SHALL return at most 10 Lead results and at most 5 Analysis_Session results per request.
9. THE Search_Service SHALL return results ordered by relevance: exact prefix matches before mid-string matches, then alphabetically within each group.
10. THE Search_Service SHALL return results in a JSON object with a `leads` array and a `sessions` array. Each Lead item SHALL include: `id` (integer), `type` ("lead"), `label` (string formatted as `"{owner_first_name} {owner_last_name}"` or `property_street` if names are absent), and `nav_path` (string formatted as `"/properties/{id}"`). Each Analysis_Session item SHALL include: `id` (integer), `type` ("session"), `label` (property address string), `nav_path` (string formatted as `"/analysis/{session_id}"`), and `created_at` (ISO 8601 date string).
11. WHEN the search produces no matching records, THE Search_Service SHALL return HTTP 200 with `{"leads": [], "sessions": []}`.
12. THE Search_Service SHALL respond within 500 ms at the 95th percentile for queries against a dataset of up to 50,000 lead records.
13. IF an unauthenticated request is received, THEN THE Search_Service SHALL return HTTP 401.

---

### Requirement 4: Search Results Dropdown

**User Story:** As a user, I want to see a dropdown of results as I type, so that I can quickly identify and navigate to the record I am looking for.

#### Acceptance Criteria

1. WHEN the Search_Service returns one or more results for a Query of 1 or more characters, THE Search_Bar SHALL display a results dropdown directly below the input field.
2. THE Search_Bar SHALL group results under labeled sections: "Leads" for Lead results and "Analysis Sessions" for Analysis_Session results.
3. WHEN a results section contains no matches, THE Search_Bar SHALL omit that section from the dropdown.
4. WHEN the Search_Service returns no results, THE Search_Bar SHALL display a single "No results found" message inside the dropdown.
5. WHILE a search request is in-flight, THE Search_Bar SHALL display a loading indicator inside the dropdown area.
6. IF the Search_Service returns an error response, THEN THE Search_Bar SHALL display a "Search failed. Please try again." message in the dropdown.
7. THE Search_Bar SHALL display at most 10 Lead result items and at most 5 Analysis_Session result items in the dropdown.
8. WHEN a result item is focused via keyboard arrow-key navigation, THE Search_Bar SHALL apply a distinct background style to that item that differs visibly from all non-focused items.
9. WHEN the user presses Enter on a keyboard-focused result item or clicks a result item, THE Search_Bar SHALL navigate to that item's detail page and close the dropdown.
10. WHEN the Search_Bar loses focus, or the user presses Escape, or the Query is cleared to 0 characters, THE Search_Bar SHALL close the results dropdown.

---

### Requirement 5: Result Navigation

**User Story:** As a user, I want clicking a search result to take me directly to that record, so that I can access the full details without additional steps.

#### Acceptance Criteria

1. WHEN the user clicks a Lead result item, THE Search_Bar SHALL navigate to `/properties/{lead_id}` using React Router's client-side navigation.
2. WHEN the user clicks an Analysis_Session result item, THE Search_Bar SHALL navigate to the `nav_path` value for that specific result item as returned by the Search_Service.
3. IF a result item's `nav_path` field is absent or empty, THEN THE Search_Bar SHALL not navigate and SHALL display a "Search failed. Please try again." message in the dropdown.
4. WHEN the user presses Enter while a result item is keyboard-focused, THE Search_Bar SHALL perform the same navigation as clicking that item.
5. WHEN navigation to a result item completes, THE Search_Bar SHALL clear the Query and close the results dropdown.

---

### Requirement 6: Lead Result Display

**User Story:** As a user searching by owner name, I want each lead result to show enough context to confirm it is the right person, so that I can distinguish between similarly named leads.

#### Acceptance Criteria

1. WHEN a Lead result item is displayed and both `owner_first_name` and `owner_last_name` are present, THE Search_Bar SHALL display the owner's full name formatted as `"{owner_first_name} {owner_last_name}"` as the primary label.
2. WHEN a Lead result item is displayed, THE Search_Bar SHALL display the `property_street` value as secondary text positioned below the primary label.
3. IF only one of `owner_first_name` or `owner_last_name` is present, THEN THE Search_Bar SHALL display that single available name value as the primary label.
4. IF both `owner_first_name` and `owner_last_name` are absent or empty, THEN THE Search_Bar SHALL display the `property_street` as the primary label.
5. IF both name fields and `property_street` are all absent or empty, THEN THE Search_Bar SHALL display "Unknown Lead" as the primary label.
6. WHEN a Lead result item is displayed and the lead score is a non-null numeric value (including 0), THE Search_Bar SHALL display the numeric score value (0–100) in a chip or badge element alongside the primary label.

---

### Requirement 7: Analysis Session Result Display

**User Story:** As a user searching by property address, I want each analysis session result to show the address and session status, so that I can identify the correct session.

#### Acceptance Criteria

1. WHEN an Analysis_Session result item is displayed, THE Search_Bar SHALL display the property address as the primary label (the topmost text line of the result item).
2. WHEN an Analysis_Session result item is displayed, THE Search_Bar SHALL display the session creation date as secondary text positioned below the property address (format: `MM/DD/YYYY`).
3. WHEN an Analysis_Session result item is displayed, THE Search_Bar SHALL display the session status (e.g., "In Progress", "Complete") as a label or badge alongside the primary label.
4. IF an Analysis_Session result item has no property address, THEN THE Search_Bar SHALL display "Unknown Address" as the primary label.

---

### Requirement 9: Search Result Ownership Scoping

**User Story:** As a regular user, I want search results to show only my own leads and analysis sessions, so that I cannot see private data belonging to other users. As an admin user, I want to be able to search across all users' records, so that I can support and manage the platform.

#### Acceptance Criteria

1. WHEN a Regular_User submits a search request, THE Search_Service SHALL filter all Lead results to only those records where `leads.owner_user_id` matches `g.user_id` of the authenticated user.
2. WHEN a Regular_User submits a search request, THE Search_Service SHALL filter all Analysis_Session results to only those sessions whose linked `PropertyFacts` record is owned by the authenticated user (i.e., `analysis_sessions.user_id` matches `g.user_id`).
3. IF a Regular_User's query matches a Lead or Analysis_Session that belongs to a different user, THEN THE Search_Service SHALL NOT include that record in the response.
4. WHEN an Admin_User (where `g.is_admin` is `True`) submits a search request, THE Search_Service SHALL return matching records across all users without ownership filtering.
5. THE Search_Service SHALL determine the user's admin status exclusively from the `g.is_admin` value set during JWT verification, and SHALL NOT accept any client-supplied parameter to elevate search scope.
6. IF a Lead record has a `NULL` `owner_user_id`, THEN THE Search_Service SHALL NOT include that record in results returned to a Regular_User.


**User Story:** As a developer, I want the search query to execute efficiently, so that response time remains acceptable as the lead database grows.

#### Acceptance Criteria

1. WHERE the PostgreSQL `pg_trgm` extension is available, THE Search_Service SHALL use trigram index-backed queries on `owner_first_name`, `owner_last_name`, and `property_street`. IF `pg_trgm` is not available, THEN THE Search_Service SHALL use case-insensitive pattern matching (ILIKE) on those columns.
2. THE Search_Service SHALL apply LIMIT clauses to all database queries: at most 10 Lead results and at most 5 Analysis_Session results per request (matching Requirement 3.8).
3. THE Search_Service SHALL respond within 2 seconds at the 95th percentile for queries against a dataset of up to 100,000 lead records.
