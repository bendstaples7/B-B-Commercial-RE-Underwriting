# Requirements Document

## Introduction

This feature adds an admin panel to the B&B Real Estate Analyzer platform. The platform currently has two users — Ben (ben.d.staples.7@gmail.com) and User X (userx@test.com) — with full lead exclusivity enforced per user. Admins need cross-user visibility to monitor the overall health of the system: who owns what leads, how many import jobs each user has run, and how many marketing lists each user has created.

The scope is intentionally narrow: **read-only visibility** across all users. Admins can see everything but cannot modify another user's data or impersonate them. Admin status is stored as an `is_admin` boolean on the `users` table, seeded for Ben via a migration.

The system uses a Flask/Python backend with PostgreSQL and a React/TypeScript frontend (MUI v5, React Router v6, TanStack React Query v5).

---

## Glossary

- **Admin_User**: A User whose `is_admin` column is `true`. Currently only Ben (ben.d.staples.7@gmail.com).
- **Admin_Service**: The backend component that enforces admin-only access and aggregates cross-user data.
- **Admin_Panel**: The frontend page at `/admin` that is only visible and accessible to Admin_Users.
- **User_Summary**: A read-only aggregate view of one user's data: their profile fields plus counts of owned leads, marketing lists, and import jobs.
- **require_admin**: A Flask decorator that verifies the authenticated user is an Admin_User, returning HTTP 403 if not.
- **User**: A registered account as defined in the multi-user-lead-exclusivity spec (fields: `id`, `user_id`, `email`, `display_name`, `is_active`, `is_admin`, `created_at`, `updated_at`).
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
3. IF no User record with `email_lower = 'ben.d.staples.7@gmail.com'` exists at migration time, THEN THE Admin_Service SHALL create Ben's User record with `display_name = "Ben"`, `is_active = true`, and `is_admin = true` as part of the migration, and IF the User record creation fails, THEN THE Admin_Service SHALL abort the migration and return an error.
4. THE Auth_Service SHALL include the `is_admin` claim in the JWT payload when issuing a Session_Token, so that the frontend can determine admin status without an additional API call.
5. THE Auth_Service SHALL reject any JWT whose `is_admin` claim is absent or non-boolean as malformed.

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
4. THE Auth_Context SHALL treat a token whose `is_admin` claim is present but not a boolean as malformed and SHALL remove it from local storage, treating the user as unauthenticated.
