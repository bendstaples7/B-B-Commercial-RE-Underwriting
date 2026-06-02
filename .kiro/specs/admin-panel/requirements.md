# Requirements Document

## Introduction

This feature adds an admin panel to the B&B Real Estate Analyzer platform. The platform has three users: the admin account (`admin@admin.com`, display name "Ben Staples"), and two sub-users — Ben (`ben.d.staples.7@gmail.com`) and UserX (`userx@test.com`). The sub-users do not yet exist in the database and must be seeded. All 6,790 existing leads currently have `owner_user_id = NULL` and must be reassigned to `ben.d.staples.7@gmail.com` via migration.

The admin panel covers two areas:
1. **Read-only cross-user visibility** — admins can see all users, their activity summaries, and their leads.
2. **User management** — admins can reset a user's password, change a user's display name, and change a user's email.

Sub-users are seeded without a password and must set one on first login via a "set password" flow (they are issued a one-time setup token instead of a normal session token).

Admin status is stored as an `is_admin` boolean on the `users` table. The system uses a Flask/Python backend with PostgreSQL and a React/TypeScript frontend (MUI v5, React Router v6, TanStack React Query v5).

---

## Glossary

- **Admin_User**: A User whose `is_admin` column is `true`. Currently only `admin@admin.com` (display name "Ben Staples").
- **Sub_User**: A non-admin User account. Currently `ben.d.staples.7@gmail.com` ("Ben") and `userx@test.com` ("UserX").
- **Admin_Service**: The backend component that enforces admin-only access and aggregates cross-user data.
- **Admin_Panel**: The frontend page at `/admin` that is only visible and accessible to Admin_Users.
- **User_Summary**: A read-only aggregate view of one user's data: their profile fields plus counts of owned leads, marketing lists, and import jobs.
- **require_admin**: A Flask decorator that verifies the authenticated user is an Admin_User, returning HTTP 403 if not.
- **Setup_Token**: A short-lived JWT (1 hour) issued to a newly seeded sub-user that has no password yet. It carries a `setup_required: true` claim and can only be used to call `POST /api/auth/set-password`. It cannot authenticate any other endpoint.
- **User**: A registered account (fields: `id`, `user_id`, `email`, `email_lower`, `display_name`, `password_hash`, `is_active`, `is_admin`, `password_set`, `created_at`, `updated_at`).
- **Lead**: A property owner record in the `leads` table with an `owner_user_id` foreign key to `users.user_id`.
- **MarketingList**: A campaign group in the `marketing_lists` table with a `user_id` foreign key.
- **ImportJob**: A Google Sheets import record in the `import_jobs` table with a `user_id` foreign key.

---

## Requirements

### Requirement 1: Admin Flag on User Model

**User Story:** As a system administrator, I want Ben's account to be marked as an admin in the database, so that admin privileges are stored persistently and do not depend on environment variables or hardcoded email checks.

#### Acceptance Criteria

1. THE Admin_Service SHALL add an `is_admin` boolean column to the `users` table with a default value of `false` and a `NOT NULL` constraint.
2. WHEN the migration runs, THE Admin_Service SHALL set `is_admin = true` for the User record whose `email_lower` is `ben.d.staples.7@gmail.com`, and SHALL leave all other User records with `is_admin = false`.
3. IF no User record with `email_lower = 'ben.d.staples.7@gmail.com'` exists at migration time, THE Admin_Service migration SHALL fail with a clear error indicating that the user must be created before the migration is run; user/account creation (including `display_name = "Ben"`, `is_active = true`, `is_admin = true`) is handled by a separate seed/bootstrap process and is not part of the migration.
4. THE Auth_Service SHALL include the `is_admin` claim in the JWT payload when issuing a Session_Token, so that the frontend can determine admin status without an additional API call.
5. THE Auth_Service SHALL reject any JWT whose `is_admin` claim is present but not a boolean as malformed; if the `is_admin` claim is absent, THE Auth_Service SHALL treat it as `false` (non-admin).

---

### Requirement 2: Admin-Only Endpoint Guard

**User Story:** As a security-conscious developer, I want all admin endpoints to be protected by a dedicated guard, so that non-admin users receive a clear rejection rather than silently seeing empty data.

#### Acceptance Criteria

1. THE Admin_Service SHALL expose a `require_admin` decorator that, when applied to a Flask route, first verifies the request carries a valid Session_Token (delegating to the existing `require_auth` mechanism) and then verifies the token's `is_admin` claim is `true`; WHERE additional route-level conditions exist, THE Admin_Service SHALL evaluate those conditions after the admin check passes.
2. WHEN a request reaches an admin endpoint and the authenticated user's `is_admin` claim is `false`, THE Admin_Service SHALL return HTTP 403 with a JSON body `{"error": "Forbidden", "message": "Admin access required."}`, SHALL log the unauthorized access attempt including the requesting user's `user_id` and the requested path, and SHALL NOT execute the route handler.
3. WHEN a request reaches an admin endpoint with no valid Session_Token, THE Admin_Service SHALL return HTTP 401 (delegated from `require_auth`) before the admin check is evaluated.
4. THE Admin_Service SHALL apply `require_admin` to every route registered under the `/api/admin` prefix, with no exceptions.

---

### Requirement 3: List All Users Endpoint

**User Story:** As an admin, I want to retrieve a list of all registered users with their key profile fields, so that I can see who has accounts on the platform.

#### Acceptance Criteria

1. WHEN a GET request is made to `/api/admin/users` by an Admin_User, THE Admin_Service SHALL return HTTP 200 with a JSON array of all User records, each containing: `user_id`, `email`, `display_name`, `is_active`, `is_admin`, and `created_at`.
2. THE Admin_Service SHALL NOT include `password_hash` or any other credential field in the response.
3. WHEN a GET request is made to `/api/admin/users` by a non-admin authenticated user, THE Admin_Service SHALL return HTTP 403.
4. THE Admin_Service SHALL return users ordered by `created_at` ascending.

---

### Requirement 4: Per-User Activity Summary Endpoint

**User Story:** As an admin, I want to see a summary of each user's activity — lead count, marketing list count, and import job count — so that I can understand how the platform is being used across users.

#### Acceptance Criteria

1. WHEN a GET request is made to `/api/admin/users/<user_id>/summary` by an Admin_User, THE Admin_Service SHALL return HTTP 200 with a JSON object containing: `user_id`, `email`, `display_name`, `is_active`, `is_admin`, `created_at`, `lead_count` (integer), `marketing_list_count` (integer), and `import_job_count` (integer).
2. THE Admin_Service SHALL compute `lead_count` as the number of rows in the `leads` table where `owner_user_id` matches the requested `user_id`.
3. THE Admin_Service SHALL compute `marketing_list_count` as the number of rows in the `marketing_lists` table where `user_id` matches the requested `user_id`.
4. THE Admin_Service SHALL compute `import_job_count` as the number of rows in the `import_jobs` table where `user_id` matches the requested `user_id`.
5. IF the requested `user_id` does not correspond to any User record, THEN THE Admin_Service SHALL return HTTP 404.
6. WHEN a GET request is made to `/api/admin/users/<user_id>/summary` by a non-admin authenticated user, THE Admin_Service SHALL return HTTP 403.

---

### Requirement 5: Cross-User Lead List Endpoint

**User Story:** As an admin, I want to view all leads across all users, optionally filtered by owner, so that I can audit the full lead database.

#### Acceptance Criteria

1. WHEN a GET request is made to `/api/admin/leads` by an Admin_User, THE Admin_Service SHALL return HTTP 200 with a paginated JSON response containing leads from all users, each lead record including: `id`, `owner_user_id`, `owner_display_name`, `property_street`, `property_city`, `property_state`, `lead_status`, `lead_score`, and `created_at`.
2. WHEN the request includes an `owner_user_id` query parameter, THE Admin_Service SHALL filter the results to only leads where `owner_user_id` matches the provided value.
3. THE Admin_Service SHALL support `page` (default 1) and `page_size` (default 50, maximum 200) query parameters for pagination, and SHALL include `total_count`, `page`, and `page_size` in the response envelope; IF a request specifies a `page_size` greater than 200, THEN THE Admin_Service SHALL return HTTP 400 with an error message indicating the maximum allowed value.
4. WHEN a GET request is made to `/api/admin/leads` by a non-admin authenticated user, THE Admin_Service SHALL return HTTP 403.
5. THE Admin_Service SHALL NOT expose any endpoint that allows an Admin_User to modify, delete, or reassign leads belonging to another user.

---

### Requirement 6: Frontend Admin Panel Page

**User Story:** As an admin, I want a dedicated page in the application where I can see all users and their activity summaries, so that I have a single place to monitor platform usage.

#### Acceptance Criteria

1. WHEN the authenticated user's `is_admin` JWT claim is `true`, THE Admin_Panel SHALL be accessible at the `/admin` route and a navigation link labeled "Admin" SHALL appear in the application sidebar.
2. WHEN the authenticated user's `is_admin` JWT claim is `false` or absent, THE Admin_Panel route SHALL redirect to the application home page and the "Admin" navigation link SHALL NOT be rendered.
3. THE Admin_Panel SHALL display a table of all users with columns: Display Name, Email, Status (active/inactive), Admin (yes/no), Member Since, Lead Count, Marketing Lists, and Import Jobs.
4. WHEN the Admin_Panel loads, THE Admin_Panel SHALL fetch user summaries for all users by calling the `/api/admin/users` endpoint followed by `/api/admin/users/<user_id>/summary` for each user, and SHALL display a loading indicator while the data is being fetched.
5. IF any fetch request returns an error, THE Admin_Panel SHALL display an error message and SHALL NOT show partial data from a failed request.
6. THE Admin_Panel SHALL display each user's lead count, marketing list count, and import job count in the summary table.
7. WHEN the admin clicks on a user row, THE Admin_Panel SHALL navigate to a user detail view at `/admin/users/<user_id>` that shows the user's summary and a paginated list of their leads fetched from `/api/admin/leads?owner_user_id=<user_id>`.

---

### Requirement 7: Admin Claim in Frontend Auth Context

**User Story:** As a frontend developer, I want the `is_admin` flag available in the AuthContext, so that any component can conditionally render admin-only UI without additional API calls.

#### Acceptance Criteria

1. THE Auth_Context SHALL decode the `is_admin` claim from the stored JWT and expose it as a boolean field on the `AuthUser` object (defaulting to `false` if the claim is absent).
2. WHEN the JWT is validated on application load or at any point during the session, THE Auth_Context SHALL include `is_admin` in the restored or updated `AuthUser` state.
3. WHEN a new token is received from the login endpoint, THE Auth_Context SHALL extract and store the `is_admin` claim from the token payload as part of the `AuthUser` object.
4. THE Auth_Context SHALL treat a token whose `is_admin` claim is present but not a boolean as malformed and SHALL remove it from local storage, treating the user as unauthenticated; if the `is_admin` claim is absent, THE Auth_Context SHALL default it to `false`.

---

### Requirement 8: Seed Sub-Users and Reassign Leads

**User Story:** As a system administrator, I want the two sub-user accounts to exist in the database and all existing leads to be owned by the correct user, so that the admin panel shows accurate data from the start.

#### Acceptance Criteria

1. WHEN the migration runs, THE Admin_Service SHALL insert a User record for `ben.d.staples.7@gmail.com` with `display_name = 'Ben'`, `is_active = true`, `is_admin = false`, and `password_set = false` IF no such record already exists (idempotent).
2. WHEN the migration runs, THE Admin_Service SHALL insert a User record for `userx@test.com` with `display_name = 'UserX'`, `is_active = true`, `is_admin = false`, and `password_set = false` IF no such record already exists (idempotent).
3. WHEN the migration runs, THE Admin_Service SHALL update all `leads` rows where `owner_user_id IS NULL` to set `owner_user_id` to the `user_id` of the `ben.d.staples.7@gmail.com` User record.
4. THE `users` table SHALL have a `password_set` boolean column (`NOT NULL DEFAULT FALSE`) that tracks whether a user has set their own password; this column SHALL be added by the same migration if it does not already exist.
5. THE migration SHALL be idempotent — running it twice SHALL NOT create duplicate users or fail.

---

### Requirement 9: First-Login Password Setup Flow

**User Story:** As a sub-user who was seeded by the admin, I want to be prompted to set my password on first login, so that I can access the platform securely without the admin knowing my credentials.

#### Acceptance Criteria

1. WHEN a User with `password_set = false` attempts to log in via `POST /api/auth/login`, THE Auth_Service SHALL return HTTP 200 with a JSON body `{"setup_required": true, "setup_token": "<token>"}` instead of a normal session token; the `setup_token` SHALL be a signed JWT with `setup_required: true`, `sub: <user_id>`, `exp: now + 3600` (1 hour), and no `is_admin` claim.
2. WHEN `POST /api/auth/set-password` is called with a valid `setup_token` in the `Authorization: Bearer` header and a `new_password` in the request body, THE Auth_Service SHALL hash the password, update `password_hash` and set `password_set = true` on the User record, and return a normal session token (same format as a successful login).
3. IF the `setup_token` is expired or invalid, THE Auth_Service SHALL return HTTP 401.
4. IF `new_password` is absent or fewer than 8 characters, THE Auth_Service SHALL return HTTP 400 with `{"error": "Validation error", "message": "Password must be at least 8 characters."}`.
5. THE `setup_token` SHALL NOT be accepted by `require_auth` — any endpoint protected by `require_auth` SHALL return HTTP 401 if presented with a `setup_token`.
6. WHEN the frontend receives `{"setup_required": true, "setup_token": "..."}` from the login endpoint, THE Login_Page SHALL redirect to `/set-password` and store the `setup_token` in memory (not localStorage).
7. THE Set_Password_Page at `/set-password` SHALL display a form with a "New Password" field and a "Confirm Password" field; WHEN submitted with matching passwords of at least 8 characters, it SHALL call `POST /api/auth/set-password` and on success redirect to the application home page with the returned session token stored in localStorage.
8. IF the passwords do not match or are fewer than 8 characters, THE Set_Password_Page SHALL display an inline validation error and SHALL NOT submit the request.

---

### Requirement 10: Admin User Management — Reset Password

**User Story:** As an admin, I want to reset any user's password from the admin panel, so that I can help users who are locked out without needing direct database access.

#### Acceptance Criteria

1. WHEN a `POST /api/admin/users/<user_id>/reset-password` request is made by an Admin_User with a JSON body `{"new_password": "<password>"}`, THE Admin_Service SHALL hash the new password, update the User's `password_hash`, set `password_set = true`, and return HTTP 200 with `{"message": "Password reset successfully."}`.
2. IF `new_password` is absent or fewer than 8 characters, THE Admin_Service SHALL return HTTP 400 with `{"error": "Validation error", "message": "Password must be at least 8 characters."}`.
3. IF the `user_id` does not correspond to any User record, THE Admin_Service SHALL return HTTP 404.
4. WHEN a `POST /api/admin/users/<user_id>/reset-password` request is made by a non-admin authenticated user, THE Admin_Service SHALL return HTTP 403.
5. THE Admin_Service SHALL NOT allow an Admin_User to reset their own password via this endpoint; IF the `user_id` matches the requesting admin's `user_id`, THE Admin_Service SHALL return HTTP 400 with `{"error": "Validation error", "message": "Use the standard password change flow to update your own password."}`.
6. THE Admin_Panel user detail view SHALL include a "Reset Password" button that opens a dialog with a "New Password" field; WHEN submitted, it SHALL call `POST /api/admin/users/<user_id>/reset-password` and display a success or error message.

---

### Requirement 11: Admin User Management — Edit Display Name and Email

**User Story:** As an admin, I want to update a user's display name and email from the admin panel, so that I can correct mistakes or accommodate name changes without direct database access.

#### Acceptance Criteria

1. WHEN a `PATCH /api/admin/users/<user_id>` request is made by an Admin_User with a JSON body containing `display_name` and/or `email`, THE Admin_Service SHALL update the specified fields on the User record and return HTTP 200 with the updated user object (same shape as the user summary, without credential fields).
2. IF `email` is provided, THE Admin_Service SHALL validate it is a non-empty string containing `@`; IF the new email is already in use by another User, THE Admin_Service SHALL return HTTP 409 with `{"error": "Conflict", "message": "Email already in use."}`.
3. IF `display_name` is provided, THE Admin_Service SHALL validate it is a non-empty string of at most 100 characters.
4. IF neither `display_name` nor `email` is provided in the request body, THE Admin_Service SHALL return HTTP 400 with `{"error": "Validation error", "message": "At least one of display_name or email must be provided."}`.
5. IF the `user_id` does not correspond to any User record, THE Admin_Service SHALL return HTTP 404.
6. WHEN a `PATCH /api/admin/users/<user_id>` request is made by a non-admin authenticated user, THE Admin_Service SHALL return HTTP 403.
7. WHEN `email` is updated, THE Admin_Service SHALL also update `email_lower` to `email.lower()`.
8. THE Admin_Panel user detail view SHALL include an "Edit" button that opens a dialog pre-populated with the user's current `display_name` and `email`; WHEN submitted, it SHALL call `PATCH /api/admin/users/<user_id>` and refresh the displayed data on success.
