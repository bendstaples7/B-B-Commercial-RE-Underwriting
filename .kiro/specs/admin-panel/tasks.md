# Implementation Plan: Admin Panel

## Overview

Implement read-only cross-user visibility for admin users across three layers: a new Alembic migration adding `is_admin` to the `users` table, a Flask backend with a `require_admin` decorator and three new endpoints under `/api/admin`, and a React/TypeScript frontend with an updated `AuthContext`, two new components (`AdminPanel`, `AdminUserDetail`), and a guarded `/admin` route.

---

## Tasks

- [x] 1. Database migration — add `is_admin` to `users` table
  - [x] 1.1 Create Alembic migration `add_is_admin_to_users`
    - Create `backend/alembic_migrations/versions/t0u1v2w3x4y5_add_is_admin_to_users.py`
    - Set `revision = 't0u1v2w3x4y5'`, `down_revision = 's9t0u1v2w3x4'`
    - `upgrade()`: use `op.execute` with `ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE`, then `UPDATE users SET is_admin = TRUE WHERE email_lower = 'ben.d.staples.7@gmail.com'`
    - `downgrade()`: use `op.execute` with `ALTER TABLE users DROP COLUMN IF EXISTS is_admin`
    - Never use `batch_alter_table`; all DDL via raw `op.execute` with `IF NOT EXISTS`
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 Add `is_admin` column to the `User` SQLAlchemy model
    - In `backend/app/models/user.py`, add `is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default='false')`
    - _Requirements: 1.1_

- [x] 2. Backend — JWT and auth decorator updates
  - [x] 2.1 Update `AuthService.issue_token` to include `is_admin` in JWT payload
    - In `backend/app/services/auth_service.py`, add `"is_admin": bool(user.is_admin)` to the payload dict
    - _Requirements: 1.4_

  - [x] 2.2 Write property test for JWT `is_admin` claim round-trip (Property 1)
    - **Property 1: JWT `is_admin` claim round-trip**
    - **Validates: Requirements 1.4**
    - In `backend/tests/test_admin_properties.py`, use `@given(is_admin=st.booleans())` with `@settings(max_examples=100)`
    - Build a mock user with the given `is_admin` value, call `AuthService().issue_token(user)`, decode the JWT, assert `payload['is_admin'] == is_admin` and `isinstance(payload['is_admin'], bool)`

  - [x] 2.3 Update `require_auth` to extract and set `g.is_admin` from JWT claims
    - In `backend/app/api_utils.py`, after `g.user_id = claims['sub']`, add `g.is_admin = claims.get('is_admin', False)`
    - If `is_admin` is present but not a boolean, default to `False` (guards against tampered tokens)
    - _Requirements: 1.4, 2.1_

  - [x] 2.4 Implement `require_admin` decorator in `api_utils.py`
    - Add `require_admin(f)` decorator that reads `g.is_admin`; if not `True`, returns `jsonify({"error": "Forbidden", "message": "Admin access required."})` with HTTP 403 and logs the attempt (user_id + path) at WARNING level
    - Must be applied after `@require_auth` in the decorator stack
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 2.5 Write property test for `require_admin` guarding all admin routes (Property 3)
    - **Property 3: `require_admin` guards all admin routes**
    - **Validates: Requirements 2.1, 2.2, 2.4**
    - In `backend/tests/test_admin_properties.py`, use `@given(route=st.sampled_from(ADMIN_ROUTES))` with `@settings(max_examples=100)`
    - For each route, send a request with a valid JWT where `is_admin=False`; assert HTTP 403 with `{"error": "Forbidden", "message": "Admin access required."}`

- [x] 3. Backend — `AdminService`
  - [x] 3.1 Create `backend/app/services/admin_service.py` with `AdminService` class
    - Implement `list_users(self) -> list[dict]`: query `users` table, select `user_id, email, display_name, is_active, is_admin, created_at`, order by `created_at ASC`, return as list of dicts (no `password_hash`)
    - Implement `get_user_summary(self, user_id: str) -> dict`: query `users` by `user_id` with three `COUNT` subqueries against `leads`, `marketing_lists`, `import_jobs`; raise `NotFoundError` if not found
    - Implement `list_leads(self, owner_user_id: str | None, page: int, page_size: int) -> dict`: query `leads` joined to `users` for `owner_display_name`, optional `owner_user_id` filter, pagination with `LIMIT`/`OFFSET`; validate `page_size <= 200` (raise `ValidationError` if exceeded); return envelope with `leads`, `total_count`, `page`, `page_size`
    - Re-export from `backend/app/services/__init__.py`
    - _Requirements: 3.1, 3.2, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3_

  - [x] 3.2 Write property test for user list excludes credential fields (Property 4)
    - **Property 4: User list excludes credential fields**
    - **Validates: Requirements 3.1, 3.2**
    - In `backend/tests/test_admin_properties.py`, use `@given(users=st.lists(user_strategy(), min_size=1, max_size=10))` with `@settings(max_examples=100)`
    - Seed users, call `AdminService().list_users()`, assert no user dict contains `password_hash` or any credential field

  - [x] 3.3 Write property test for user list ordering invariant (Property 5)
    - **Property 5: User list ordering invariant**
    - **Validates: Requirements 3.4**
    - In `backend/tests/test_admin_properties.py`, use `@given(users=st.lists(user_strategy(), min_size=2, max_size=20))` with `@settings(max_examples=100)`
    - Seed users with distinct `created_at` values, call `AdminService().list_users()`, assert result is sorted ascending by `created_at`

  - [x] 3.4 Write property test for user summary count accuracy (Property 6)
    - **Property 6: User summary count accuracy**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    - In `backend/tests/test_admin_properties.py`, use `@given(lead_count=st.integers(0, 50), list_count=st.integers(0, 20), job_count=st.integers(0, 30))` with `@settings(max_examples=100)`
    - Seed a user with exactly N leads, M marketing lists, K import jobs; call `AdminService().get_user_summary(user_id)`; assert `lead_count == N`, `marketing_list_count == M`, `import_job_count == K`

  - [x] 3.5 Write property test for cross-user lead visibility (Property 7)
    - **Property 7: Cross-user lead visibility**
    - **Validates: Requirements 5.1**
    - In `backend/tests/test_admin_properties.py`, use `@given(user_count=st.integers(1, 5), leads_per_user=st.integers(0, 10))` with `@settings(max_examples=100)`
    - Seed multiple users each with N leads; call `AdminService().list_leads(None, 1, 200)`; assert all leads appear and each has `owner_display_name`

  - [x] 3.6 Write property test for lead filter correctness (Property 8)
    - **Property 8: Lead filter correctness**
    - **Validates: Requirements 5.2**
    - In `backend/tests/test_admin_properties.py`, use `@given(owner_user_id=st.uuids())` with `@settings(max_examples=100)`
    - Seed leads for multiple users; call `AdminService().list_leads(str(owner_user_id), 1, 200)`; assert every returned lead has `owner_user_id` equal to the filter value

  - [x] 3.7 Write property test for pagination envelope correctness (Property 9)
    - **Property 9: Pagination envelope correctness**
    - **Validates: Requirements 5.3**
    - In `backend/tests/test_admin_properties.py`, use `@given(page=st.integers(1, 10), page_size=st.integers(1, 200))` with `@settings(max_examples=100)`
    - Seed a known number of leads; call `AdminService().list_leads(None, page, page_size)`; assert `total_count` equals actual count, `leads` array length equals `min(page_size, max(0, total - offset))`

- [x] 4. Backend — `admin_controller.py` Blueprint
  - [x] 4.1 Create `backend/app/controllers/admin_controller.py` with `admin_bp` Blueprint
    - Register Blueprint at prefix `/api/admin`
    - Implement `GET /api/admin/users`: decorated with `@handle_errors`, `@require_auth`, `@require_admin`; calls `AdminService().list_users()`; returns JSON array
    - Implement `GET /api/admin/users/<user_id>/summary`: same decorators; calls `AdminService().get_user_summary(user_id)`; returns JSON object; 404 on `NotFoundError`
    - Implement `GET /api/admin/leads`: same decorators; reads `owner_user_id`, `page`, `page_size` from query params with defaults (page=1, page_size=50); calls `AdminService().list_leads(...)`; returns paginated envelope; 400 on `ValidationError`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4_

  - [x] 4.2 Register `admin_bp` in `backend/app/__init__.py`
    - Import `admin_bp` from `controllers.admin_controller` and call `app.register_blueprint(admin_bp, url_prefix='/api/admin')` inside `create_app`
    - _Requirements: 2.4_

  - [x] 4.3 Write unit tests for `admin_controller.py`
    - In `backend/tests/test_admin_controller.py`:
      - `require_admin` returns 403 with correct body for non-admin user
      - `require_admin` returns 401 when no token is present
      - `GET /api/admin/users` returns all users ordered by `created_at` asc
      - `GET /api/admin/users` response never contains `password_hash`
      - `GET /api/admin/users/<user_id>/summary` returns 404 for unknown `user_id`
      - `GET /api/admin/leads` with `page_size=201` returns 400
      - `GET /api/admin/leads?owner_user_id=<id>` returns only leads for that user
    - _Requirements: 2.2, 2.3, 3.1, 3.2, 3.3, 4.5, 5.2, 5.3_

- [x] 5. Backend checkpoint
  - Ensure all backend tests pass (`cd backend && pytest`). Ask the user if any questions arise before proceeding to the frontend.

- [x] 6. Frontend — types and API service
  - [x] 6.1 Add `is_admin` to `AuthUser` and add admin types to `frontend/src/types/index.ts`
    - Add `is_admin: boolean` field to the existing `AuthUser` interface (defaults to `false`)
    - Add new interfaces: `AdminUserSummary`, `AdminLead`, `AdminLeadParams`, `AdminLeadListResponse` as specified in the design
    - _Requirements: 7.1_

  - [x] 6.2 Add `adminService` methods to `frontend/src/services/api.ts`
    - Add `adminService` object with three methods:
      - `listUsers(): Promise<AdminUserSummary[]>` — `GET /api/admin/users`
      - `getUserSummary(userId: string): Promise<AdminUserSummary>` — `GET /api/admin/users/<userId>/summary`
      - `listLeads(params: AdminLeadParams): Promise<AdminLeadListResponse>` — `GET /api/admin/leads` with query params
    - Use the existing Axios instance (which already attaches the `Authorization` header)
    - _Requirements: 6.4, 6.7_

- [x] 7. Frontend — `AuthContext` updates
  - [x] 7.1 Update `AuthContext` to decode and expose `is_admin` from JWT
    - In `frontend/src/context/AuthContext.tsx`, update `validateStoredToken`:
      - Extract `is_admin` from the decoded JWT payload
      - If `is_admin` is present but not a boolean → return `null` (malformed token, triggers logout)
      - If `is_admin` is absent → default to `false`
    - Update the `login` callback to extract `is_admin` from the decoded token and include it in the `AuthUser` object
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 7.2 Write property test for malformed `is_admin` claim rejection (Property 2)
    - **Property 2: Malformed `is_admin` claim rejection**
    - **Validates: Requirements 1.5, 7.4**
    - In `frontend/src/context/AuthContext.test.tsx`, using `fast-check`:
      ```typescript
      fc.assert(fc.property(
        fc.oneof(fc.string(), fc.integer(), fc.constant(null), fc.object()),
        (nonBooleanValue) => {
          const token = buildToken({ is_admin: nonBooleanValue })
          expect(validateStoredToken(token)).toBeNull()
        }
      ), { numRuns: 100 })
      ```
    - Install `fast-check` if not already present: `npm install --save-dev fast-check`

  - [x] 7.3 Write property test for `AuthUser.is_admin` decoding (Property 11)
    - **Property 11: `AuthUser.is_admin` decoding**
    - **Validates: Requirements 7.1, 7.2, 7.3**
    - In `frontend/src/context/AuthContext.test.tsx`, using `fast-check`:
      ```typescript
      fc.assert(fc.property(
        fc.boolean(),
        (isAdmin) => {
          const token = buildToken({ is_admin: isAdmin })
          const user = validateStoredToken(token)
          expect(user?.is_admin).toBe(isAdmin)
        }
      ), { numRuns: 100 })
      ```

  - [x] 7.4 Write unit tests for `AuthContext` `is_admin` decoding
    - In `frontend/src/context/AuthContext.test.tsx`:
      - `validateStoredToken` returns `null` for tokens with `is_admin` as string, number, null, or object
      - `validateStoredToken` returns `AuthUser` with `is_admin=true` for valid admin token
      - `validateStoredToken` returns `AuthUser` with `is_admin=false` for valid non-admin token
      - `validateStoredToken` returns `AuthUser` with `is_admin=false` when claim is absent
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 8. Frontend — `AdminPanel` component
  - [x] 8.1 Create `frontend/src/components/AdminPanel.tsx`
    - Use `useQuery` (React Query v5) to fetch all users via `adminService.listUsers()`, then fetch each user's summary via `adminService.getUserSummary(userId)` in parallel with `Promise.all`
    - Show `CircularProgress` while any fetch is in-flight
    - Show MUI `Alert` with `severity="error"` if any fetch fails; do not render partial data
    - Render an MUI `Table` with columns: Display Name, Email, Status, Admin, Member Since, Lead Count, Marketing Lists, Import Jobs
    - Clicking a row navigates to `/admin/users/<user_id>` via React Router `useNavigate`
    - _Requirements: 6.3, 6.4, 6.5, 6.6_

  - [x] 8.2 Write component tests for `AdminPanel`
    - In `frontend/src/components/AdminPanel.test.tsx`:
      - Renders `CircularProgress` while fetching
      - Renders error `Alert` when fetch fails; no table rendered
      - Renders table with all required columns when data loads
      - Clicking a user row navigates to `/admin/users/<user_id>`
    - _Requirements: 6.3, 6.4, 6.5_

- [x] 9. Frontend — `AdminUserDetail` component
  - [x] 9.1 Create `frontend/src/components/AdminUserDetail.tsx`
    - Read `userId` from route params via `useParams`
    - Use `useQuery` to fetch user summary via `adminService.getUserSummary(userId)` and paginated leads via `adminService.listLeads({ owner_user_id: userId, page, page_size: 50 })`
    - Display user profile fields (Display Name, Email, Status, Admin, Member Since)
    - Display a paginated MUI `Table` of leads with columns: Property Address, City, State, Status, Score, Created At
    - Include a back button that navigates to `/admin`
    - _Requirements: 6.7_

  - [x] 9.2 Write component tests for `AdminUserDetail`
    - In `frontend/src/components/AdminUserDetail.test.tsx`:
      - Renders user profile fields from summary data
      - Renders leads table with correct columns
      - Back button navigates to `/admin`
    - _Requirements: 6.7_

- [x] 10. Frontend — route guard and sidebar link in `App.tsx`
  - [x] 10.1 Add guarded `/admin` and `/admin/users/:userId` routes to `App.tsx`
    - Import `AdminPanel` and `AdminUserDetail`
    - Add routes:
      ```tsx
      <Route path="/admin" element={user?.is_admin ? <AdminPanel /> : <Navigate to="/" replace />} />
      <Route path="/admin/users/:userId" element={user?.is_admin ? <AdminUserDetail /> : <Navigate to="/" replace />} />
      ```
    - Add conditional sidebar link (renders only when `user?.is_admin` is `true`):
      ```tsx
      {user?.is_admin && (
        <ListItemButton component={Link} to="/admin">
          <ListItemIcon><AdminPanelSettingsIcon /></ListItemIcon>
          <ListItemText primary="Admin" />
        </ListItemButton>
      )}
      ```
    - _Requirements: 6.1, 6.2_

  - [x] 10.2 Write property test for admin route access control (Property 10)
    - **Property 10: Admin route access control**
    - **Validates: Requirements 6.1, 6.2**
    - In `frontend/src/App.test.tsx` (or `AdminPanel.test.tsx`), using `fast-check`:
      ```typescript
      fc.assert(fc.property(
        fc.record({ user_id: fc.uuid(), email: fc.emailAddress(), display_name: fc.string() }),
        (userFields) => {
          const user = { ...userFields, is_admin: false }
          // render App with this user in AuthContext, navigate to /admin, expect redirect to /
        }
      ), { numRuns: 100 })
      ```
    - Also assert that `is_admin: true` renders `AdminPanel` and shows the "Admin" sidebar link

- [x] 11. Final checkpoint — Ensure all tests pass
  - Run `cd backend && pytest` and `cd frontend && npm test` to confirm all tests pass. Ask the user if any questions arise.

---

## New Tasks — Admin Panel Enhancements

- [x] 12. Database migration — seed sub-users, add `password_set`, reassign leads
  - [x] 12.1 Create Alembic migration `seed_sub_users_and_reassign_leads`
    - Create `backend/alembic_migrations/versions/w2x3y4z5a6b7_seed_sub_users_and_reassign_leads.py`
    - Set `revision = 'w2x3y4z5a6b7'`, `down_revision = 'v1w2x3y4z5a6'`
    - `upgrade()`:
      1. `ALTER TABLE users ADD COLUMN IF NOT EXISTS password_set BOOLEAN NOT NULL DEFAULT FALSE`
      2. `UPDATE users SET password_set = TRUE WHERE password_hash IS NOT NULL AND password_hash != ''` (mark existing users as already having a password)
      3. Insert `ben.d.staples.7@gmail.com` with `display_name='Ben'`, `is_active=true`, `is_admin=false`, `password_set=false`, `password_hash=''` using `INSERT INTO users ... ON CONFLICT (email_lower) DO NOTHING`
      4. Insert `userx@test.com` with `display_name='UserX'`, `is_active=true`, `is_admin=false`, `password_set=false`, `password_hash=''` using `INSERT INTO users ... ON CONFLICT (email_lower) DO NOTHING`
      5. `UPDATE leads SET owner_user_id = (SELECT user_id FROM users WHERE email_lower = 'ben.d.staples.7@gmail.com') WHERE owner_user_id IS NULL`
    - `downgrade()`: `ALTER TABLE users DROP COLUMN IF EXISTS password_set` (do NOT delete seeded users or undo lead reassignment — data changes are irreversible)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 12.2 Add `password_set` column to the `User` SQLAlchemy model
    - In `backend/app/models/user.py`, add `password_set = db.Column(db.Boolean, nullable=False, default=False, server_default='false')`
    - _Requirements: 8.4_

- [x] 13. Backend — first-login password setup flow
  - [x] 13.1 Update `AuthService.authenticate` to detect `password_set = false`
    - In `backend/app/services/auth_service.py`, after verifying the password (or if `password_hash` is empty), check `user.password_set`
    - If `password_set = false`, return a special sentinel instead of the User — e.g. raise a new `PasswordSetupRequiredException(user)` exception
    - _Requirements: 9.1_

  - [x] 13.2 Add `AuthService.issue_setup_token` method
    - In `backend/app/services/auth_service.py`, add `issue_setup_token(self, user: User) -> str`
    - Payload: `{"sub": user.user_id, "setup_required": True, "iat": now, "exp": now + timedelta(hours=1)}`
    - No `is_admin` claim — this token cannot pass `require_auth`
    - _Requirements: 9.1_

  - [x] 13.3 Update `POST /api/auth/login` to return setup token for passwordless users
    - In the auth controller (find via `grep_search` for the login route), catch `PasswordSetupRequiredException`
    - Return HTTP 200 with `{"setup_required": true, "setup_token": "<token>"}` instead of the normal session token
    - _Requirements: 9.1_

  - [x] 13.4 Add `POST /api/auth/set-password` endpoint
    - In the auth controller, add a new route `POST /api/auth/set-password`
    - Verify the `Authorization: Bearer` token has `setup_required: true` claim (use a new `require_setup_token` decorator or inline check)
    - Validate `new_password` is present and >= 8 characters; return 400 if not
    - Hash the password with bcrypt work factor 12, update `password_hash` and `password_set = True`, commit
    - Return HTTP 200 with a normal session token (call `AuthService().issue_token(user)`)
    - _Requirements: 9.2, 9.3, 9.4, 9.5_

  - [x] 13.5 Update `require_auth` to reject setup tokens
    - In `backend/app/api_utils.py`, after decoding JWT claims in `require_auth`, check if `claims.get('setup_required') == True`; if so, return HTTP 401 `{"error": "Setup token cannot be used for authentication"}`
    - _Requirements: 9.5_

- [x] 14. Backend — admin user management endpoints
  - [x] 14.1 Add `AdminService.reset_user_password` method
    - In `backend/app/services/admin_service.py`, add `reset_user_password(self, user_id: str, new_password: str, requesting_admin_id: str) -> None`
    - Validate `new_password` >= 8 chars (raise `ValidationException` if not)
    - Raise `ValidationException` if `user_id == requesting_admin_id`
    - Raise `ResourceNotFoundError` if user not found
    - Hash with bcrypt work factor 12, update `password_hash` and `password_set = True`, commit
    - _Requirements: 10.1, 10.2, 10.3, 10.5_

  - [x] 14.2 Add `AdminService.update_user` method
    - In `backend/app/services/admin_service.py`, add `update_user(self, user_id: str, display_name: str | None, email: str | None) -> dict`
    - Validate at least one field is provided (raise `ValidationException` if neither)
    - Validate `display_name` is non-empty and <= 100 chars if provided
    - Validate `email` contains `@` if provided; raise `ConflictError` if email already in use by another user
    - Update `email_lower = email.lower()` when email is changed
    - Commit and return the updated user dict (same shape as `list_users` rows)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.7_

  - [x] 14.3 Add `POST /api/admin/users/<user_id>/reset-password` route to `admin_controller.py`
    - Decorated with `@handle_errors`, `@require_auth`, `@require_admin`
    - Read `new_password` from JSON body
    - Call `AdminService().reset_user_password(user_id, new_password, g.user_id)`
    - Return 200 `{"message": "Password reset successfully."}`; 400/403/404 handled by `handle_errors` and `require_admin`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 14.4 Add `PATCH /api/admin/users/<user_id>` route to `admin_controller.py`
    - Decorated with `@handle_errors`, `@require_auth`, `@require_admin`
    - Read `display_name` and `email` from JSON body (both optional)
    - Call `AdminService().update_user(user_id, display_name, email)`
    - Return 200 with updated user dict; 400/403/404/409 handled by decorators and `handle_errors`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

- [x] 15. Frontend — set-password page
  - [x] 15.1 Update `LoginPage` to handle `setup_required` response
    - In `frontend/src/pages/LoginPage.tsx` (or wherever the login form lives), after a successful login response, check if `response.data.setup_required === true`
    - If so, store `setup_token` in a React state/context (NOT localStorage) and navigate to `/set-password`
    - _Requirements: 9.6_

  - [x] 15.2 Create `frontend/src/pages/SetPasswordPage.tsx`
    - Display a form with "New Password" and "Confirm Password" fields
    - Validate: both fields non-empty, >= 8 characters, must match — show inline error if not
    - On submit, call `POST /api/auth/set-password` with `Authorization: Bearer <setup_token>` and `{"new_password": "..."}`
    - On success, store the returned `session_token` in localStorage and navigate to `/`
    - On API error, display the error message
    - _Requirements: 9.7, 9.8_

  - [x] 15.3 Add `/set-password` route to `App.tsx`
    - Import `SetPasswordPage` and add `<Route path="/set-password" element={<SetPasswordPage />} />`
    - This route must be accessible without authentication (outside the auth guard)
    - _Requirements: 9.7_

  - [x] 15.4 Add `setupToken` to a lightweight context or pass via navigation state
    - The `setup_token` must be available to `SetPasswordPage` without being stored in localStorage
    - Use React Router `useLocation` state (`navigate('/set-password', { state: { setupToken } })`) to pass it
    - `SetPasswordPage` reads `location.state?.setupToken`; if absent, redirect to `/login`
    - _Requirements: 9.6, 9.7_

- [x] 16. Frontend — admin user management UI
  - [x] 16.1 Add admin API methods to `frontend/src/services/api.ts`
    - Add to `adminService`:
      - `resetPassword(userId: string, newPassword: string): Promise<void>` — `POST /api/admin/users/<userId>/reset-password`
      - `updateUser(userId: string, data: { display_name?: string; email?: string }): Promise<AdminUserSummary>` — `PATCH /api/admin/users/<userId>`
    - _Requirements: 10.1, 11.1_

  - [x] 16.2 Add "Reset Password" dialog to `AdminUserDetail`
    - In `frontend/src/components/AdminUserDetail.tsx`, add a "Reset Password" `Button` in the user profile section
    - Clicking it opens an MUI `Dialog` with a "New Password" `TextField` and Submit/Cancel buttons
    - On submit, call `adminService.resetPassword(userId, newPassword)` via `useMutation`
    - Show a success `Snackbar` or inline `Alert` on success; show error `Alert` on failure
    - _Requirements: 10.6_

  - [x] 16.3 Add "Edit User" dialog to `AdminUserDetail`
    - In `frontend/src/components/AdminUserDetail.tsx`, add an "Edit" `Button` in the user profile section
    - Clicking it opens an MUI `Dialog` pre-populated with the user's current `display_name` and `email`
    - On submit, call `adminService.updateUser(userId, { display_name, email })` via `useMutation`
    - On success, invalidate the `['adminUserSummary', userId]` React Query cache key to refresh the displayed data
    - Show error `Alert` on failure (including 409 conflict for duplicate email)
    - _Requirements: 11.8_

- [x] 17. Final checkpoint — run all tests
  - Run `cd backend && pytest` and `cd frontend && npm test` to confirm all tests pass.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- All migrations use raw `op.execute` with `IF NOT EXISTS` — never `batch_alter_table`
- `require_admin` must always be applied after `@require_auth` in the decorator stack
- `fast-check` must be installed in the frontend before running property tests: `npm install --save-dev fast-check`
- Each property test runs a minimum of 100 iterations
- The `AdminPanel` never shows partial data — all user summaries are fetched in parallel and the table only renders when all succeed
- The existing Axios interceptor handles 401 responses automatically (clears localStorage, redirects to `/login`)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.3", "6.1"] },
    { "id": 2, "tasks": ["2.2", "2.4", "3.1", "6.2"] },
    { "id": 3, "tasks": ["2.5", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "4.1", "7.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "7.2", "7.3", "7.4"] },
    { "id": 5, "tasks": ["8.1", "9.1"] },
    { "id": 6, "tasks": ["8.2", "9.2", "10.1"] },
    { "id": 7, "tasks": ["10.2"] },
    { "id": 8, "tasks": ["12.1", "12.2"] },
    { "id": 9, "tasks": ["13.1", "13.2"] },
    { "id": 10, "tasks": ["13.3", "13.4", "13.5", "14.1", "14.2"] },
    { "id": 11, "tasks": ["14.3", "14.4", "15.1", "15.2"] },
    { "id": 12, "tasks": ["15.3", "15.4", "16.1"] },
    { "id": 13, "tasks": ["16.2", "16.3"] },
    { "id": 14, "tasks": ["17"] }
  ]
}
```
