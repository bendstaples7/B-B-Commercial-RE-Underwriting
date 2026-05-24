# Requirements Document

## Introduction

This feature adds user authentication and lead exclusivity to the B&B Real Estate Analyzer platform. Currently the system has no login mechanism — user identity is passed as a plain string header (`X-User-Id`) with no verification, and all leads in the `leads` table are shared globally with no ownership concept.

The goal is to:
1. Introduce a lightweight credential-based login (email + password) so users can sign in and receive a verified session token.
2. Assign every lead a `user_id` owner column so that each user's pipeline is completely isolated from others.
3. Migrate all existing leads to Ben (ben.d.staples.7@gmail.com) as the sole owner.
4. Provision a second user, "User X" (placeholder — email and name TBD), who can sign in and manage their own independent lead pipeline.

The system uses a Flask/Python backend with PostgreSQL and a React/TypeScript frontend. Authentication must integrate with the existing `X-User-Id` header pattern used throughout the API layer.

---

## Glossary

- **Auth_Service**: The backend component responsible for validating credentials, issuing session tokens, and verifying tokens on incoming requests.
- **Session_Token**: A short-lived, cryptographically signed token (JWT or equivalent) issued to a user upon successful login, used to authenticate subsequent API requests.
- **User**: A registered account with an email address, hashed password, display name, and a unique `user_id` string.
- **Lead**: A property owner record stored in the `leads` table. After this feature, every lead has an `owner_user_id` column that ties it to exactly one User.
- **Lead_Pipeline**: The set of leads, marketing lists, scoring weights, import jobs, and analysis sessions owned by a specific User.
- **Ben**: The primary/admin user with email `ben.d.staples.7@gmail.com`. All existing leads are migrated to Ben's ownership.
- **User_X**: A placeholder second user whose email and display name will be configured at deployment time. User X has an independent lead pipeline with no visibility into Ben's leads.
- **Login_Page**: The frontend page presented to unauthenticated users where they enter their email and password.
- **Auth_Context**: The React context that holds the current user's identity and session token, and exposes login/logout actions to the rest of the frontend.

---

## Requirements

### Requirement 1: User Account Storage

**User Story:** As a system administrator, I want user accounts stored securely in the database, so that credentials can be verified at login time.

#### Acceptance Criteria

1. THE Auth_Service SHALL store each User record with: a unique `user_id` string, an email address (unique, case-insensitive, max 254 characters), a bcrypt-hashed password, a display name (max 100 characters), an `is_active` boolean (default `true`), and `created_at` / `updated_at` timestamps stored in UTC.
2. THE Auth_Service SHALL enforce uniqueness of email addresses across all User records, treating email comparison as case-insensitive.
3. IF a duplicate email is submitted during account creation, THEN THE Auth_Service SHALL return an error response with HTTP status 409, and SHALL NOT include any submitted plaintext password value in the error response body or log entry.
4. THE Auth_Service SHALL never store or return plaintext passwords in any API response or log entry, including in error responses for duplicate email or any other validation failure.
5. IF an account creation request is missing a required field (email, password, or display name) or any required field is empty, THEN THE Auth_Service SHALL return HTTP status 400 and SHALL NOT create any partial User record.

---

### Requirement 2: Credential-Based Login

**User Story:** As a user, I want to sign in with my email and password, so that I can access my own lead pipeline securely.

#### Acceptance Criteria

1. WHEN a POST request is made to the login endpoint with a valid email and password, THE Auth_Service SHALL return a Session_Token and the authenticated user's `user_id`, email, and display name.
2. WHEN a POST request is made to the login endpoint with an unrecognised email or an incorrect password, THE Auth_Service SHALL return HTTP status 401 and a generic message that does not distinguish between the two failure modes.
3. WHEN a POST request is made to the login endpoint with a missing email or missing password field, THE Auth_Service SHALL return an error response with HTTP status 400.
4. THE Auth_Service SHALL issue Session_Tokens that expire after no more than 24 hours from the time of issuance.
5. THE Auth_Service SHALL reject login attempts for User accounts where `is_active` is false, returning HTTP status 401.

---

### Requirement 3: Token Verification on API Requests

**User Story:** As a system, I want every API request to carry a verified identity, so that lead data is never served to the wrong user.

#### Acceptance Criteria

1. WHEN an API request is received with a valid Session_Token in the `Authorization: Bearer <token>` header, THE Auth_Service SHALL populate `g.user_id` with the token's subject claim and allow the route handler to execute.
2. WHEN an API request is received without an `Authorization` header, or with a token that is missing the `Bearer` scheme, not parseable as a three-segment JWT, has an invalid signature, or has an expired `exp` claim, THE Auth_Service SHALL return HTTP status 401 with an error message indicating the rejection reason, and SHALL prevent the route handler from executing.
3. IF an endpoint's path is present in the application's configured public-endpoint allowlist, THEN THE Auth_Service SHALL skip token verification for that endpoint, ensuring the login endpoint is always on the allowlist and never requires a token.
4. WHERE the existing `X-User-Id` header is present alongside a valid Bearer token, THE Auth_Service SHALL use the Bearer token's identity and ignore the `X-User-Id` header.

---

### Requirement 4: Lead Ownership

**User Story:** As a user, I want every lead I create or import to be exclusively mine, so that other users cannot see or modify my pipeline.

#### Acceptance Criteria

1. THE system SHALL enforce that every Lead is associated with exactly one User as its owner, and SHALL reject any attempt to create a Lead without an owner.
2. WHEN a lead is created or imported, THE Lead SHALL be assigned the `owner_user_id` of the authenticated user making the request.
3. WHEN the lead list endpoint is queried, THE Lead_Pipeline SHALL return only leads where `owner_user_id` matches the authenticated user's `user_id`, and SHALL return an empty list with HTTP status 200 when the authenticated user owns no leads.
4. WHEN a lead detail, update, or delete request is made for a lead owned by a different user, THE Auth_Service SHALL return HTTP status 404 so that the existence of other users' leads is not revealed.
5. WHEN a request targets a lead-adjacent resource (marketing list, import job, scoring weights, enrichment record, or analysis session) belonging to a different user, THE Lead_Pipeline SHALL return HTTP status 404, and WHEN a list endpoint for any lead-adjacent resource is queried, THE Lead_Pipeline SHALL return only records where the owner matches the authenticated user's `user_id`.

---

### Requirement 5: Data Migration — Assign Existing Leads to Ben

**User Story:** As Ben, I want all existing leads in the system to be assigned to my account, so that my pipeline is preserved after the migration.

#### Acceptance Criteria

1. IF Ben's User record (email: `ben.d.staples.7@gmail.com`) does not already exist in the database, THEN THE Auth_Service SHALL create it with display name "Ben" as part of the database migration.
2. IF Ben's User record creation fails during migration, THEN THE Auth_Service SHALL abort the entire migration and return an error.
3. WHEN the migration runs, THE Lead SHALL have its `owner_user_id` set to Ben's `user_id` for every existing lead row where `owner_user_id` is NULL; lead rows where `owner_user_id` is already non-NULL SHALL be left unchanged.
4. IF the `USER_X_EMAIL` and `USER_X_NAME` environment variables are both set at migration time, THEN THE Auth_Service SHALL create User_X's User record with those values if it does not already exist.
5. IF `USER_X_EMAIL` or `USER_X_NAME` is not set at migration time, THEN THE Auth_Service SHALL attempt to log a warning and skip User_X account creation without failing the migration, regardless of whether the warning was successfully recorded.

---

### Requirement 6: Lead-Adjacent Resource Isolation

**User Story:** As a user, I want my marketing lists, import jobs, and scoring weights to be isolated from other users, so that my configuration and campaign data remain private.

#### Acceptance Criteria

1. WHEN a marketing list is created, THE Lead_Pipeline SHALL assign the authenticated user's `user_id` to the `user_id` column of the marketing list.
2. WHEN marketing lists are queried, THE Lead_Pipeline SHALL return only marketing lists where `user_id` matches the authenticated user's `user_id`.
3. WHEN an import job is created, THE Lead_Pipeline SHALL assign the authenticated user's `user_id` to the `user_id` column of the import job.
4. WHEN import jobs are queried, THE Lead_Pipeline SHALL return only import jobs where `user_id` matches the authenticated user's `user_id`.
5. WHEN scoring weights are queried or updated for a `user_id` that does not match the authenticated user's `user_id`, THE Lead_Pipeline SHALL reject the operation with an error and make no modification.
6. WHEN an analysis session is created from a lead, THE Lead_Pipeline SHALL verify that the lead's `owner_user_id` matches the authenticated user's `user_id` before creating the session.
7. IF the lead's `owner_user_id` does not match the authenticated user's `user_id` when creating an analysis session, THEN THE Lead_Pipeline SHALL return an error and SHALL NOT create the session record.

---

### Requirement 7: Frontend Login Page

**User Story:** As a user, I want a login page presented when I am not authenticated, so that I can enter my credentials and access the application.

#### Acceptance Criteria

1. WHEN the frontend application loads and no valid Session_Token is present in local storage, or the stored token is expired or malformed, THE Login_Page SHALL be displayed instead of the main application layout.
2. THE Login_Page SHALL provide an email input field, a password input field, and a submit button.
3. WHEN the backend returns a successful authentication response, THE Auth_Context SHALL store the Session_Token and user identity in local storage and redirect the user to the main application.
4. WHEN the backend returns an authentication error response, THE Login_Page SHALL display an error message that does not reveal whether the email or password was incorrect, and SHALL NOT clear the entered credentials.
5. WHEN the user clicks the logout button, THE Auth_Context SHALL remove the Session_Token and user identity from local storage and redirect the user to the Login_Page.
6. WHILE a Session_Token exists in local storage, THE Auth_Context SHALL include the Session_Token as a `Bearer` token in the `Authorization` header of every API request, and WHILE no Session_Token exists in local storage, THE Auth_Context SHALL omit the `Authorization` header from API requests.
7. WHEN the login form is submitted with an empty email field or an empty password field, THE Login_Page SHALL display a validation error and SHALL NOT submit the request to the backend.

---

### Requirement 8: Session Token Lifecycle

**User Story:** As a user, I want my session to persist across page refreshes but expire after a reasonable period, so that I stay logged in during a working session without leaving an indefinitely open session.

#### Acceptance Criteria

1. WHEN the frontend application loads and a Session_Token is present in local storage, THE Auth_Context SHALL parse the token's `exp` claim, compare it to the current UTC time, and restore the authenticated session if the token has not expired; IF the token is malformed or unparseable, THE Auth_Context SHALL remove it from local storage and treat the user as unauthenticated without redirecting.
2. WHEN the frontend application loads and no Session_Token is present in local storage, THE Auth_Context SHALL treat the user as unauthenticated and display the Login_Page.
3. WHEN a Session_Token has expired and the user attempts to make an API request, THE Auth_Context SHALL receive a 401 response, remove the stored token from local storage, and redirect the user to the Login_Page, preserving the originally requested URL for post-login return.
4. THE Auth_Context SHALL not expose the Session_Token value or any token metadata (including expiration time, issuer, or claims) in any rendered UI element or browser console log.
5. THE Auth_Service SHALL issue Session_Tokens with a maximum lifetime of 8 hours from the time of issuance, and THE Auth_Context SHALL treat any token whose `exp` claim exceeds 8 hours from its `iat` claim as invalid.
