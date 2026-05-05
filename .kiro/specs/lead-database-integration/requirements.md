# Requirements Document

## Introduction

The Lead Database Integration feature extends the existing Real Estate Analysis Platform to ingest property and owner data from two Google Sheets into a structured PostgreSQL database. Once imported, the platform will support lead scoring, external data source enrichment, and marketing campaign management. This transforms the platform from a property analysis tool into a full lead management pipeline for real estate investors.

## Glossary

- **Lead**: A record representing a property owner who is a potential seller or marketing target, composed of property details, owner information, contact information, and mailing information.
- **Lead_Database**: The set of PostgreSQL tables that store imported lead records and their associated metadata.
- **Google_Sheets_Importer**: The backend service responsible for authenticating with the Google Sheets API, reading spreadsheet data, and transforming rows into Lead records.
- **Lead_Scoring_Engine**: The backend service that computes a numeric score for each Lead based on configurable criteria such as property characteristics, owner situation, and data completeness.
- **Data_Source_Connector**: The backend service responsible for linking Lead records to external data sources for enrichment (e.g., county records, skip tracing services, MLS data).
- **Marketing_Manager**: The backend service that organizes Leads into marketing lists, tracks campaign assignments, and records outreach status.
- **Import_Job**: A record representing a single execution of the Google Sheets import process, tracking status, row counts, and errors.
- **Lead_Score**: A numeric value between 0 and 100 representing the quality and likelihood of conversion for a given Lead.
- **Marketing_List**: A named collection of Leads grouped for a specific marketing campaign or outreach effort.
- **Platform**: The existing Real Estate Analysis Platform (Flask/PostgreSQL backend, React/TypeScript frontend).
- **Field_Mapping**: A configuration that maps column headers in a Google Sheet to corresponding Lead_Database fields.
- **Enrichment_Record**: A record that tracks data retrieved from an external Data_Source_Connector and attached to a Lead.

## Requirements

### Requirement 1: Google Sheets Authentication and Connection

**User Story:** As a platform user, I want to connect my Google Sheets to the platform, so that I can import my property and lead data.

#### Acceptance Criteria

1. WHEN a user provides Google OAuth2 credentials, THE Google_Sheets_Importer SHALL authenticate with the Google Sheets API and return a success or failure status within 10 seconds.
2. WHEN authentication succeeds, THE Google_Sheets_Importer SHALL retrieve the list of available sheets from the specified spreadsheet and present them to the user.
3. IF authentication fails due to invalid or expired credentials, THEN THE Google_Sheets_Importer SHALL return a descriptive error message indicating the authentication failure reason.
4. THE Platform SHALL store Google OAuth2 refresh tokens securely in the database using encryption at rest.

### Requirement 2: Google Sheets Field Mapping

**User Story:** As a platform user, I want to map columns from my Google Sheets to database fields, so that the import correctly places data into the right fields.

#### Acceptance Criteria

1. WHEN a user selects a Google Sheet for import, THE Google_Sheets_Importer SHALL read the header row and present all column names to the user.
2. THE Platform SHALL provide a default Field_Mapping that auto-maps common column names (e.g., "Address", "Owner Name", "Phone", "Mailing Address") to their corresponding Lead_Database fields.
3. WHEN a user modifies a Field_Mapping, THE Platform SHALL validate that all required Lead_Database fields (property address, owner name) have a mapped source column before allowing import to proceed.
4. THE Platform SHALL persist each Field_Mapping so that subsequent imports from the same spreadsheet reuse the saved mapping.
5. IF a column header in the Google Sheet does not match any known Lead_Database field, THEN THE Platform SHALL leave that column unmapped and allow the user to manually assign it or skip it.

### Requirement 3: Data Import and Validation

**User Story:** As a platform user, I want to import data from my two Google Sheets into the lead database, so that all my property and owner records are centralized.

#### Acceptance Criteria

1. WHEN a user initiates an import, THE Google_Sheets_Importer SHALL create an Import_Job record with status "in_progress" and begin reading rows from the specified Google Sheet.
2. THE Google_Sheets_Importer SHALL validate each row against the Lead_Database schema, checking for required fields (property address, owner name), valid data types, and field length constraints.
3. WHEN a row passes validation, THE Google_Sheets_Importer SHALL insert or update the corresponding Lead record in the Lead_Database using the property address as the deduplication key.
4. IF a row fails validation, THEN THE Google_Sheets_Importer SHALL skip that row, log the row number and error reason in the Import_Job record, and continue processing remaining rows.
5. WHEN all rows have been processed, THE Google_Sheets_Importer SHALL update the Import_Job status to "completed" and record the total rows processed, rows imported, and rows skipped.
6. THE Google_Sheets_Importer SHALL process imports asynchronously using the existing Celery task queue so that the user interface remains responsive during large imports.
7. WHILE an Import_Job is in progress, THE Platform SHALL allow the user to view the current import progress including rows processed and rows remaining.

### Requirement 4: Lead Data Model and Storage

**User Story:** As a platform user, I want my lead data stored in a structured database, so that I can query, filter, and manage leads efficiently.

#### Acceptance Criteria

1. THE Lead_Database SHALL store each Lead with the following field groups: property details (address, property type, bedrooms, bathrooms, square footage, lot size, year built), owner information (owner name, ownership type, acquisition date), contact information (phone numbers, email addresses), and mailing information (mailing address, city, state, zip code).
2. THE Lead_Database SHALL enforce a unique constraint on property address to prevent duplicate Lead records.
3. THE Lead_Database SHALL track metadata for each Lead including created_at timestamp, updated_at timestamp, data source identifier, and last import job reference.
4. WHEN a Lead record is updated by a subsequent import, THE Lead_Database SHALL preserve the previous field values in an audit trail.
5. THE Platform SHALL provide API endpoints to list, search, filter, and retrieve individual Lead records with pagination support.
6. WHEN a user requests a filtered list of Leads, THE Platform SHALL support filtering by property type, location (city, state, zip code), owner name, lead score range, and marketing list membership.

### Requirement 5: Lead Scoring

**User Story:** As a platform user, I want each lead scored automatically, so that I can prioritize the most promising leads for outreach.

#### Acceptance Criteria

1. WHEN a Lead record is created or updated, THE Lead_Scoring_Engine SHALL compute a Lead_Score between 0 and 100 for that Lead.
2. THE Lead_Scoring_Engine SHALL calculate the Lead_Score based on configurable weighted criteria including: property characteristics (property type, condition, equity estimate), data completeness (percentage of fields populated), owner situation indicators (length of ownership, absentee owner status), and location desirability.
3. THE Platform SHALL allow users to view and modify the scoring weights for each criterion through the user interface.
4. WHEN a user modifies scoring weights, THE Lead_Scoring_Engine SHALL recalculate Lead_Scores for all affected Leads within the background task queue.
5. THE Platform SHALL display Lead_Score alongside each Lead record in list and detail views.
6. THE Platform SHALL allow users to sort and filter Leads by Lead_Score.

### Requirement 6: External Data Source Connection

**User Story:** As a platform user, I want to enrich my leads with data from external sources, so that I have more complete information for decision-making.

#### Acceptance Criteria

1. THE Data_Source_Connector SHALL provide a plugin interface that allows registering external data sources with a name, endpoint configuration, and field mapping.
2. WHEN a user triggers enrichment for a Lead, THE Data_Source_Connector SHALL query the configured external data source using the Lead property address or owner name as lookup keys.
3. WHEN an external data source returns results, THE Data_Source_Connector SHALL create an Enrichment_Record linking the retrieved data to the Lead and update the corresponding Lead fields.
4. IF an external data source query fails or returns no results, THEN THE Data_Source_Connector SHALL log the failure in the Enrichment_Record with the error reason and leave the Lead record unchanged.
5. THE Platform SHALL display enrichment status and source attribution for each enriched field on the Lead detail view.
6. WHEN a user triggers bulk enrichment for a Marketing_List, THE Data_Source_Connector SHALL process enrichment requests asynchronously through the Celery task queue.

### Requirement 7: Marketing List Management

**User Story:** As a platform user, I want to organize leads into marketing lists, so that I can run targeted outreach campaigns.

#### Acceptance Criteria

1. THE Marketing_Manager SHALL allow users to create, rename, and delete Marketing_Lists.
2. WHEN a user adds Leads to a Marketing_List, THE Marketing_Manager SHALL associate the selected Lead records with the specified Marketing_List.
3. THE Marketing_Manager SHALL allow a single Lead to belong to multiple Marketing_Lists simultaneously.
4. THE Platform SHALL allow users to create Marketing_Lists from saved filter criteria so that the list automatically includes all Leads matching those filters.
5. WHEN a user views a Marketing_List, THE Platform SHALL display the list members with their Lead_Score, contact information, and outreach status.
6. THE Marketing_Manager SHALL track outreach status for each Lead within a Marketing_List using the statuses: "not_contacted", "contacted", "responded", "converted", and "opted_out".
7. WHEN a Lead outreach status is updated to "opted_out", THE Marketing_Manager SHALL exclude that Lead from future Marketing_Lists created from filter criteria.

### Requirement 8: Import History and Management

**User Story:** As a platform user, I want to view my import history and re-run imports, so that I can keep my lead database up to date.

#### Acceptance Criteria

1. THE Platform SHALL display a list of all Import_Jobs with their status, start time, completion time, total rows, imported rows, and skipped rows.
2. WHEN a user selects a completed Import_Job, THE Platform SHALL display the detailed error log showing each skipped row number and the corresponding validation error.
3. THE Platform SHALL allow users to re-run a previous Import_Job using the same spreadsheet and Field_Mapping configuration.
4. WHEN a user re-runs an import, THE Google_Sheets_Importer SHALL use upsert logic to update existing Lead records and insert new ones without creating duplicates.

### Requirement 9: Lead-to-Analysis Integration

**User Story:** As a platform user, I want to start a property analysis directly from a lead record, so that I can seamlessly move from lead management to deal analysis.

#### Acceptance Criteria

1. WHEN a user selects a Lead and initiates an analysis, THE Platform SHALL create a new AnalysisSession pre-populated with the Lead property address and available property details.
2. THE Platform SHALL store a reference linking the AnalysisSession to the originating Lead record.
3. WHEN an AnalysisSession linked to a Lead is completed, THE Platform SHALL display the analysis results on the Lead detail view.

