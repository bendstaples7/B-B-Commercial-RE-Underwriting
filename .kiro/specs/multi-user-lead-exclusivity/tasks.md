# Implementation Plan: Multi-User Lead Exclusivity

## Overview

Implement credential-based authentication and per-user lead ownership for the B&B Real Estate Analyzer. The work spans a new `users` table and Alembic migration, a `User` SQLAlchemy model, an `AuthService`, an `auth_controller` Blueprint, a `require_auth` decorator, an `owner_user_id` column on `leads`, ownership filters across all lead-adjacent controllers, and a React `AuthContext` + `LoginPage` with Axios interceptors.

## Tasks

- [x] 1. Create the `User` model and `AuthError` exception
  - [x] 1.1 Add `AuthError` exception class to `backend/app/exceptions.py`
    - Extend `RealEstateAnalysisException` with an `AuthError` subclass
    - Register `AuthError` in `backend/app/error_handlers.py` to return the correct HTTP status
    - _Requirements: 3.2_

  - [x] 1.2 Create `backend/app/models/user.py` with the `User` SQLAlchemy model
    - Define all columns: `id`, `user_id` (UUID string, unique, indexed), `email`, `email_lower` (unique, indexed), `password_hash`, `display_name`, `is_active`, `created_at`, `updated_at`
    - Re-export `User` from `backend/app/models/__init__.py`
    - _Requirements: 1.1_

  - [x] 1.3 Write property test for User record completeness
    - **Property 1: User record completeness**
    - **Validates: Requirements 1.1**
    - Use Hypothesis `@given` in `backend/tests/test_auth_properties.py`; generate valid (email, password, display_name) triples and assert all required fields are populated correctly after `create_user`

- [x] 2. Implement `AuthService`
  - [x] 2.1 Create `backend/app/services/auth_service.py` with `AuthService` class
    - Implement `create_user(email, password, display_name)` → `User` using bcrypt work factor 12
    - Implement `authenticate(email, password)` → `User | None` with case-insensitive email lookup via `email_lower`
    - Implement `issue_token(user)` → `str` (HS256 JWT, 8-hour lifetime, claims: `sub`, `email`, `display_name`, `iat`, `exp`)
    - Implement `verify_token(token)` → `dict` or raise `jwt.ExpiredSignatureError` / `jwt.InvalidTokenError`
    - Re-export `AuthService` from `backend/app/services/__init__.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.4, 8.5_

  - [x] 2.2 Write property test for email case-insensitive uniqueness
    - **Property 2: Email uniqueness is case-insensitive**
    - **Validates: Requirements 1.2, 1.3**
    - Generate an email string and case variants; assert second `create_user` raises a 409-equivalent error

  - [x] 2.3 Write property test for plaintext password never in response
    - **Property 3: Plaintext password never appears in any response**
    - **Validates: Requirements 1.3, 1.4**
    - Generate arbitrary password strings; call login and registration endpoints; assert password string is not a substring of any response body

  - [x] 2.4 Write property test for invalid inputs returning 400 without creating a user
    - **Property 4: Invalid inputs return 400 without creating a user**
    - **Validates: Requirements 1.5**
    - Generate requests with at least one missing/empty required field; assert HTTP 400 and no User row created

  - [x] 2.5 Write property test for successful login response fields
    - **Property 5: Successful login response contains all identity fields**
    - **Validates: Requirements 2.1**
    - For any registered active User, assert login response contains `session_token`, `user_id`, `email`, `display_name` with correct values

  - [x] 2.6 Write property test for indistinguishable 401 on invalid credentials
    - **Property 6: Invalid credentials produce identical 401 responses**
    - **Validates: Requirements 2.2**
    - Generate unrecognised emails and wrong passwords; assert both return HTTP 401 with identical body

  - [x] 2.7 Write property test for token lifetime ≤ 8 hours
    - **Property 7: Issued tokens have a lifetime of at most 8 hours**
    - **Validates: Requirements 2.4, 8.5**
    - For any issued token, decode and assert `exp - iat <= 28800`

- [x] 3. Create the `auth_controller` Blueprint and `require_auth` decorator
  - [x] 3.1 Create `backend/app/controllers/auth_controller.py`
    - Register Blueprint at `/api/auth`
    - Implement `POST /api/auth/login`: validate request with Marshmallow schema, call `AuthService.authenticate`, return JWT + identity fields on success, return 401 on failure, return 400 on missing fields
    - Add `POST /api/auth/login` and `GET /api/health` to the public-endpoint allowlist
    - _Requirements: 2.1, 2.2, 2.3, 3.3_

  - [x] 3.2 Implement `require_auth` decorator in `backend/app/api_utils.py` (or a new `backend/app/auth_utils.py`)
    - Read `Authorization: Bearer <token>` header; verify via `AuthService.verify_token`; populate `g.user_id`
    - Return 401 with appropriate message for expired, malformed, or missing tokens
    - Fall back to `X-User-Id` header only when no `Authorization` header is present
    - _Requirements: 3.1, 3.2, 3.4_

  - [x] 3.3 Update `backend/app/__init__.py` `set_user_identity` `before_request` hook
    - Prefer Bearer JWT over `X-User-Id`; fall through to `X-User-Id` only on JWT failure
    - Register `auth_controller` Blueprint in `create_app`
    - _Requirements: 3.1, 3.4_

  - [x] 3.4 Write property test for Bearer token populating `g.user_id`
    - **Property 8: Valid Bearer token populates g.user_id with token subject**
    - **Validates: Requirements 3.1**
    - Generate valid JWTs with arbitrary `sub` values; assert `g.user_id` equals `sub` after request

  - [x] 3.5 Write property test for invalid/absent tokens producing 401
    - **Property 9: Invalid or absent tokens produce 401**
    - **Validates: Requirements 3.2**
    - Generate absent headers, non-Bearer schemes, malformed JWTs, wrong-signature JWTs, expired JWTs; assert HTTP 401 and route handler not executed

  - [x] 3.6 Write property test for Bearer precedence over X-User-Id
    - **Property 10: Bearer token identity takes precedence over X-User-Id**
    - **Validates: Requirements 3.4**
    - Send requests with both a valid Bearer token (`user_a`) and `X-User-Id: user_b`; assert `g.user_id == user_a`

- [x] 4. Checkpoint — Ensure all auth tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Write the Alembic migration for `users` table and `owner_user_id` column
  - [x] 5.1 Create a new Alembic migration in `backend/alembic_migrations/`
    - Step 1: `CREATE TABLE IF NOT EXISTS users (...)` with all columns and indexes
    - Step 2: `INSERT INTO users ... ON CONFLICT (email_lower) DO NOTHING` to seed Ben's account (password from `BEN_INITIAL_PASSWORD` env var; generate and print a random secure password if not set)
    - Step 3: `ALTER TABLE leads ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(36)`
    - Step 4: `UPDATE leads SET owner_user_id = (SELECT user_id FROM users WHERE email_lower = 'ben.d.staples.7@gmail.com') WHERE owner_user_id IS NULL`
    - Step 5: `ALTER TABLE leads ALTER COLUMN owner_user_id SET NOT NULL`
    - Step 6: `ALTER TABLE leads ADD CONSTRAINT IF NOT EXISTS fk_leads_owner FOREIGN KEY (owner_user_id) REFERENCES users(user_id)`
    - Step 7: Conditionally seed User_X if `USER_X_EMAIL` and `USER_X_NAME` env vars are set; log a warning and skip (without failing) if not set
    - Implement idempotent `downgrade()` using `DROP ... IF EXISTS`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 5.2 Write property test for post-migration lead ownership invariant
    - **Property 15: Post-migration lead ownership invariant**
    - **Validates: Requirements 5.3**
    - After running the migration against a test DB with pre-existing leads, assert every lead row has a non-NULL `owner_user_id`

- [x] 6. Add `owner_user_id` ownership enforcement to the leads controller
  - [x] 6.1 Update `backend/app/controllers/lead_controller.py` to apply `require_auth` and filter by `owner_user_id`
    - Apply `@require_auth` to all lead endpoints
    - Set `owner_user_id = g.user_id` on lead creation and import
    - Add `owner_user_id == g.user_id` filter to all list and detail queries
    - Return 404 (not 403) for cross-user lead access on GET, PUT, DELETE
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 6.2 Write property test for lead ownership assignment on creation
    - **Property 11: Lead ownership is assigned to the creating user**
    - **Validates: Requirements 4.2**
    - For any authenticated user creating any lead, assert `lead.owner_user_id == g.user_id`

  - [x] 6.3 Write property test for lead list isolation
    - **Property 12: Lead list returns only the authenticated user's leads**
    - **Validates: Requirements 4.3**
    - Create leads for two distinct users; assert each user's list query returns only their own leads

  - [x] 6.4 Write property test for cross-user lead access returning 404
    - **Property 13: Cross-user lead access returns 404**
    - **Validates: Requirements 4.4**
    - For any two distinct users and a lead owned by user 1, assert GET/PUT/DELETE as user 2 returns HTTP 404

- [x] 7. Add ownership enforcement to lead-adjacent controllers
  - [x] 7.1 Update `backend/app/controllers/marketing_controller.py`
    - Apply `@require_auth` to all marketing list endpoints
    - Set `user_id = g.user_id` on marketing list creation
    - Filter list queries by `user_id == g.user_id`
    - Return 404 for cross-user access to a specific marketing list
    - _Requirements: 4.5, 6.1, 6.2_

  - [x] 7.2 Update `backend/app/controllers/import_controller.py`
    - Apply `@require_auth` to all import job endpoints
    - Set `user_id = g.user_id` on import job creation
    - Filter list queries by `user_id == g.user_id`
    - Return 404 for cross-user access to a specific import job
    - _Requirements: 4.5, 6.3, 6.4_

  - [x] 7.3 Update scoring weights and analysis session endpoints
    - In the relevant controller(s), reject scoring weight queries/updates where the target `user_id` does not match `g.user_id`
    - When creating an analysis session, verify `lead.owner_user_id == g.user_id` before creating the session; return 404 if not
    - _Requirements: 6.5, 6.6, 6.7_

  - [x] 7.4 Write property test for resource isolation (marketing lists and import jobs)
    - **Property 14: Resource isolation — marketing lists and import jobs**
    - **Validates: Requirements 4.5, 6.1, 6.2, 6.3, 6.4**
    - For any two distinct users with marketing lists and import jobs, assert list queries return only the authenticated user's records and cross-user access returns 404

- [x] 8. Checkpoint — Ensure all backend ownership and isolation tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement frontend `AuthContext` and token lifecycle
  - [x] 9.1 Create `frontend/src/context/AuthContext.tsx`
    - Define `AuthUser` and `AuthContextValue` TypeScript interfaces in `frontend/src/types/index.ts`
    - Implement `AuthProvider` with `user`, `token`, `login`, `logout`, `isLoading` state
    - On mount: read `localStorage.getItem('session_token')`, decode JWT payload (client-side only), check `exp` against `Date.now()`, and also reject tokens where `exp - iat > 28800`; restore session if valid, remove token and treat as unauthenticated otherwise
    - `login()`: POST to `/api/auth/login`, store `session_token` and `user_id` in localStorage, update context state
    - `logout()`: remove `session_token` and `user_id` from localStorage, clear context state, redirect to `/login`
    - Export `useAuth` hook
    - _Requirements: 7.1, 7.3, 7.5, 8.1, 8.2, 8.4, 8.5_

  - [x] 9.2 Write unit tests for `AuthContext`
    - Test: restores session from a valid non-expired token on mount
    - Test: clears an expired token on mount and treats user as unauthenticated
    - Test: clears a malformed/unparseable token on mount without redirecting
    - Test: rejects a token where `exp - iat > 28800`
    - Test: `logout()` removes token from localStorage and clears user state
    - _Requirements: 7.5, 8.1, 8.2, 8.4, 8.5_

  - [x] 9.3 Write property test for token expiry validation on app load
    - **Property 17: Token expiry is validated on app load**
    - **Validates: Requirements 8.1**
    - For any JWT with `exp` in the past, assert that after `AuthProvider` mounts the token is removed from localStorage and user is null

- [x] 10. Update Axios interceptors in `frontend/src/services/api.ts`
  - [x] 10.1 Update the request interceptor to attach `Authorization: Bearer <token>`
    - Read `localStorage.getItem('session_token')` and set `Authorization: Bearer <token>` header
    - Keep `X-User-Id` header for backward compatibility during transition
    - _Requirements: 7.6_

  - [x] 10.2 Add a 401 response interceptor
    - On 401 response: remove `session_token` and `user_id` from localStorage, redirect to `/login?returnUrl=<encoded current path>`
    - _Requirements: 8.3_

  - [x] 10.3 Write unit tests for Axios interceptors
    - Test: request interceptor attaches `Authorization: Bearer <token>` when token exists in localStorage
    - Test: request interceptor omits `Authorization` header when no token in localStorage
    - Test: 401 response interceptor clears localStorage and redirects to `/login`
    - _Requirements: 7.6, 8.3_

  - [x] 10.4 Write property test for Authorization header on every request
    - **Property 16: Authorization header is attached to every API request when a token exists**
    - **Validates: Requirements 7.6**
    - For any JWT string stored as `session_token`, assert every Axios request includes `Authorization: Bearer <token>`

- [x] 11. Implement `LoginPage` and route guards
  - [x] 11.1 Create `frontend/src/pages/LoginPage.tsx`
    - Render MUI `TextField` for email, `TextField` for password, and a `Button` for submit
    - On submit with empty email or password: display a validation error, do not call the API
    - On 401 from backend: display a generic error message (do not reveal which field was wrong), do not clear entered credentials
    - On success: redirect to `location.state.from` or `/` as fallback
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.7_

  - [x] 11.2 Add `AuthGuard` component and update routing in `frontend/src/App.tsx`
    - Create an `AuthGuard` component that checks `useAuth().user`; if null and not loading, redirect to `/login` with `state={{ from: location }}`
    - Wrap all existing routes in `AuthGuard`
    - Add `/login` route pointing to `LoginPage`
    - Wrap the app in `AuthProvider`
    - _Requirements: 7.1_

  - [x] 11.3 Write unit tests for `LoginPage`
    - Test: renders email field, password field, and submit button
    - Test: shows validation error on submit with empty email or password, does not call API
    - Test: shows generic error message on 401 response, does not clear credentials
    - Test: redirects to `location.state.from` on successful login
    - _Requirements: 7.2, 7.3, 7.4, 7.7_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass (backend: `cd backend && pytest`; frontend: `cd frontend && npm test`), ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at logical boundaries
- Property tests use Hypothesis (backend) and Vitest (frontend); minimum 100 iterations per Hypothesis property
- The `X-User-Id` fallback is preserved throughout for backward compatibility; it can be removed in a follow-up once all clients send Bearer tokens
- Ben's initial password is read from `BEN_INITIAL_PASSWORD` env var at migration time; if unset, a random secure password is generated and printed to stdout once
- All migration SQL uses `IF NOT EXISTS` / `ON CONFLICT DO NOTHING` patterns per project migration conventions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "3.4", "3.5", "3.6"] },
    { "id": 4, "tasks": ["5.1", "9.1", "10.1"] },
    { "id": 5, "tasks": ["5.2", "6.1", "9.2", "9.3", "10.2", "10.3", "10.4"] },
    { "id": 6, "tasks": ["6.2", "6.3", "6.4", "7.1", "7.2", "7.3", "11.1", "11.2"] },
    { "id": 7, "tasks": ["7.4", "11.3"] }
  ]
}
```
