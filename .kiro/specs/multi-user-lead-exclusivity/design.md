# Design Document: Multi-User Lead Exclusivity

## Overview

This feature adds credential-based authentication and per-user lead ownership to the B&B Real Estate Analyzer. Currently the system uses an unverified `X-User-Id` string header with no authentication — all leads are globally shared. After this feature, every user signs in with email + password, receives a signed JWT, and can only see and modify their own leads and lead-adjacent resources.

The design follows the existing Flask application factory pattern, adds a new `users` table, a `User` SQLAlchemy model, an `AuthService`, an `auth_controller` Blueprint, a `require_auth` decorator, and a React `AuthContext` with a `LoginPage` component. The existing `X-User-Id` header path is preserved as a fallback but Bearer JWT takes precedence.

### Key Design Decisions

- **JWT over sessions**: Stateless JWTs avoid server-side session storage. PyJWT (already a transitive dependency via python-jose) is used directly. Tokens are HS256-signed with the app's `SECRET_KEY`.
- **8-hour token lifetime**: Balances security (short enough to limit exposure) with usability (a full working day without re-login).
- **owner_user_id as a string FK**: Matches the existing `user_id` string pattern used throughout `import_jobs`, `marketing_lists`, `scoring_weights`, and `analysis_sessions`. The `users.user_id` column is a UUID string, not an integer PK, to stay consistent with the existing pattern.
- **404 for cross-user access**: Returning 404 instead of 403 prevents information leakage about the existence of other users' resources.
- **Idempotent migration**: The Alembic migration uses `IF NOT EXISTS` / `DO $$ BEGIN ... EXCEPTION` patterns per project conventions.

---

## Architecture

```mermaid
graph TD
    subgraph Frontend
        LP[LoginPage]
        AC[AuthContext]
        AI[Axios Interceptor]
        APP[App.tsx / Routes]
    end

    subgraph Backend
        AE[/api/auth/login\nPOST]
        MW[require_auth decorator]
        AS[AuthService]
        UM[User model]
        LM[Lead model]
        DB[(PostgreSQL)]
    end

    LP -->|POST credentials| AE
    AE --> AS
    AS --> UM
    UM --> DB
    AC -->|stores JWT| LS[localStorage]
    AI -->|Authorization: Bearer| MW
    MW --> AS
    AS -->|g.user_id| APP
    APP -->|owner_user_id filter| LM
    LM --> DB
```

The request lifecycle for a protected endpoint:

1. Frontend Axios interceptor reads `localStorage.getItem('session_token')` and attaches `Authorization: Bearer <token>`.
2. Flask `before_request` hook calls `set_user_identity()` — updated to prefer Bearer JWT over `X-User-Id`.
3. `require_auth` decorator on protected routes verifies the JWT and populates `g.user_id`.
4. Route handler filters all DB queries by `owner_user_id == g.user_id`.
5. Cross-user access returns 404.

---

## Components and Interfaces

### Backend Components

#### `app/models/user.py` — User Model

New SQLAlchemy model. `user_id` is a UUID string (consistent with existing string `user_id` columns throughout the schema).

```python
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), unique=True, nullable=False, index=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    email_lower = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)
```

`email_lower` stores `email.lower()` and carries the unique constraint for case-insensitive uniqueness enforcement. The `email` column stores the original case for display.

#### `app/services/auth_service.py` — AuthService

Responsible for:
- `create_user(email, password, display_name)` → `User`
- `authenticate(email, password)` → `User | None`
- `issue_token(user)` → `str` (JWT)
- `verify_token(token)` → `dict` (claims) or raises `AuthError`

```python
class AuthService:
    TOKEN_LIFETIME_SECONDS = 8 * 3600  # 8 hours

    def issue_token(self, user: User) -> str:
        now = datetime.utcnow()
        payload = {
            'sub': user.user_id,
            'email': user.email,
            'display_name': user.display_name,
            'iat': now,
            'exp': now + timedelta(seconds=self.TOKEN_LIFETIME_SECONDS),
        }
        return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

    def verify_token(self, token: str) -> dict:
        # Raises jwt.ExpiredSignatureError, jwt.InvalidTokenError on failure
        return jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
```

#### `app/controllers/auth_controller.py` — Auth Blueprint

New Blueprint registered at `/api/auth`.

| Method | Path | Auth Required | Description |
|--------|------|---------------|-------------|
| POST | `/api/auth/login` | No (public) | Validate credentials, return JWT |

The login endpoint is added to the public allowlist so `require_auth` skips it.

#### `require_auth` Decorator

Replaces the existing `require_user` decorator for protected routes. Reads the `Authorization: Bearer <token>` header, verifies the JWT via `AuthService.verify_token()`, and populates `g.user_id`. Falls back to `X-User-Id` only if no `Authorization` header is present (backward compatibility during transition).

```python
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                claims = auth_service.verify_token(token)
                g.user_id = claims['sub']
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Invalid token'}), 401
        elif request.headers.get('X-User-Id'):
            # Legacy fallback — only used during transition
            g.user_id = request.headers.get('X-User-Id')
        else:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated
```

#### Updated `app/__init__.py` — `set_user_identity` Hook

The existing `before_request` hook is updated to prefer Bearer JWT:

```python
@app.before_request
def set_user_identity():
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        try:
            from app.services.auth_service import AuthService
            claims = AuthService().verify_token(token)
            g.user_id = claims['sub']
            return  # token wins
        except Exception:
            pass  # fall through to X-User-Id
    g.user_id = request.headers.get('X-User-Id', 'anonymous')
```

### Frontend Components

#### `src/context/AuthContext.tsx` — Auth Context

New React context file. Exports `AuthProvider`, `useAuth` hook, and `AuthContextValue` type.

```typescript
interface AuthContextValue {
  user: AuthUser | null;       // null = unauthenticated
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;          // true during initial token validation on load
}

interface AuthUser {
  user_id: string;
  email: string;
  display_name: string;
}
```

On mount, `AuthProvider` reads `localStorage.getItem('session_token')`, decodes the JWT payload (without verification — signature is verified server-side), checks the `exp` claim against `Date.now()`, and restores the session if valid. If the token is malformed or expired, it is removed from localStorage and the user is treated as unauthenticated.

#### `src/pages/LoginPage.tsx` — Login Page

New page component. Uses MUI `TextField`, `Button`, and `Alert`. Calls `useAuth().login()` on submit. Displays a generic error message on failure. Redirects to the originally requested URL (stored in `location.state.from`) on success.

#### `src/services/api.ts` — Updated Axios Interceptors

The existing request interceptor is updated to attach the Bearer token instead of (or in addition to) `X-User-Id`:

```typescript
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('session_token');
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  // Keep X-User-Id for backward compatibility during transition
  const userId = localStorage.getItem('user_id') || 'default_user';
  config.headers['X-User-Id'] = userId;
  return config;
});
```

A new response interceptor handles 401 responses:

```typescript
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      const returnUrl = window.location.pathname + window.location.search;
      localStorage.removeItem('session_token');
      localStorage.removeItem('user_id');
      window.location.href = `/login?returnUrl=${encodeURIComponent(returnUrl)}`;
    }
    // ... existing error handling
  }
);
```

#### `src/App.tsx` — Route Guards

`App.tsx` is updated to wrap all routes in an `AuthGuard` component that checks `useAuth().user`. If null and not loading, it redirects to `/login` with `state={{ from: location }}`.

---

## Data Models

### `users` Table (New)

```sql
CREATE TABLE IF NOT EXISTS users (
    id           SERIAL PRIMARY KEY,
    user_id      VARCHAR(36)  NOT NULL UNIQUE,
    email        VARCHAR(254) NOT NULL,
    email_lower  VARCHAR(254) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_users_user_id    ON users(user_id);
CREATE INDEX IF NOT EXISTS ix_users_email_lower ON users(email_lower);
```

### `leads` Table — New Column

```sql
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(36) REFERENCES users(user_id);
```

After the data migration (assigning all NULL rows to Ben), a NOT NULL constraint is added:

```sql
ALTER TABLE leads ALTER COLUMN owner_user_id SET NOT NULL;
```

This is done in two steps within the same migration to allow the seed data to be inserted first.

### Existing Tables — No Schema Changes Required

`marketing_lists`, `import_jobs`, `scoring_weights`, and `analysis_sessions` already have a `user_id VARCHAR(255)` column. After this feature, that column is populated with the JWT-verified `user_id` (a UUID string) rather than an arbitrary header value. No schema migration is needed for these tables — only the application logic changes.

---

## API Endpoints

### New: `POST /api/auth/login`

**Request:**
```json
{
  "email": "ben.d.staples.7@gmail.com",
  "password": "secret"
}
```

**Response 200:**
```json
{
  "session_token": "<jwt>",
  "user_id": "a1b2c3d4-...",
  "email": "ben.d.staples.7@gmail.com",
  "display_name": "Ben"
}
```

**Response 400:** Missing email or password field.

**Response 401:** Invalid credentials or inactive account. Generic message: `"Invalid email or password."` — identical for both wrong email and wrong password.

### Modified: All Protected Endpoints

All existing endpoints that read `g.user_id` (set by `set_user_identity`) continue to work. The change is that `g.user_id` is now populated from a verified JWT rather than an unverified header. No endpoint signatures change.

Lead CRUD endpoints (`GET /api/properties/`, `GET /api/properties/<id>`, etc.) gain an `owner_user_id == g.user_id` filter on all queries. Cross-user access returns 404.

---

## Security Considerations

### Password Storage
- bcrypt with work factor 12 (via `bcrypt` library). Never stored or logged in plaintext.
- Error responses for duplicate email, validation failures, and login failures never include the submitted password.

### JWT Security
- Algorithm: HS256. Secret: `SECRET_KEY` from environment (must be a strong random value in production).
- Token lifetime: 8 hours (`exp = iat + 28800`).
- The frontend validates `exp` on load and rejects tokens where `exp - iat > 28800` as an additional client-side guard.
- Tokens are stored in `localStorage`. This is acceptable for this application's threat model (single-user desktop app). If the threat model changes, `httpOnly` cookies should be considered.

### Information Leakage Prevention
- Login endpoint returns identical 401 for wrong email and wrong password.
- Cross-user resource access returns 404, not 403.
- Error responses never include submitted passwords.

### Public Endpoint Allowlist
The following endpoints bypass `require_auth`:
- `POST /api/auth/login`
- `GET /api/health`

All other endpoints require a valid Bearer token.

### Backward Compatibility
The `X-User-Id` header fallback is preserved during the transition period. Once all clients are updated to send Bearer tokens, the fallback can be removed. The fallback is only active when no `Authorization` header is present.

---

## Migration Strategy

A single Alembic migration handles all schema changes and data seeding. It follows the project's idempotent migration conventions.

### Migration Steps (in order)

1. **Create `users` table** — `CREATE TABLE IF NOT EXISTS users (...)`
2. **Seed Ben's account** — `INSERT INTO users ... ON CONFLICT (email_lower) DO NOTHING`
3. **Add `owner_user_id` column to `leads`** — `ALTER TABLE leads ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(36)`
4. **Assign NULL-owner leads to Ben** — `UPDATE leads SET owner_user_id = (SELECT user_id FROM users WHERE email_lower = 'ben.d.staples.7@gmail.com') WHERE owner_user_id IS NULL`
5. **Add NOT NULL constraint** — `ALTER TABLE leads ALTER COLUMN owner_user_id SET NOT NULL`
6. **Add FK constraint** — `ALTER TABLE leads ADD CONSTRAINT IF NOT EXISTS fk_leads_owner FOREIGN KEY (owner_user_id) REFERENCES users(user_id)`
7. **Seed User_X** (conditional) — only if `USER_X_EMAIL` and `USER_X_NAME` env vars are set

### Ben's Password

Ben's initial password is read from the `BEN_INITIAL_PASSWORD` environment variable at migration time. If not set, a random secure password is generated and printed to stdout once (the operator must record it). The password is bcrypt-hashed before storage.

### Downgrade

```sql
ALTER TABLE leads DROP CONSTRAINT IF EXISTS fk_leads_owner;
ALTER TABLE leads DROP COLUMN IF EXISTS owner_user_id;
DROP TABLE IF EXISTS users;
```

---

## Error Handling

| Scenario | HTTP Status | Response Body |
|----------|-------------|---------------|
| Missing Authorization header | 401 | `{"error": "Authentication required"}` |
| Malformed JWT (not 3 segments) | 401 | `{"error": "Invalid token"}` |
| Invalid JWT signature | 401 | `{"error": "Invalid token"}` |
| Expired JWT | 401 | `{"error": "Token expired"}` |
| Wrong email or password | 401 | `{"error": "Invalid email or password."}` |
| Inactive account | 401 | `{"error": "Invalid email or password."}` |
| Missing required field (login) | 400 | `{"error": "Validation error", "details": {...}}` |
| Duplicate email (registration) | 409 | `{"error": "Email already registered"}` |
| Cross-user lead access | 404 | `{"error": "Property not found", ...}` |
| Cross-user marketing list | 404 | `{"error": "Not found"}` |

All error responses are produced by the existing `@handle_errors` decorator pattern. A new `AuthError` exception class is added to `app/exceptions.py` and registered in `app/error_handlers.py`.

---

## Testing Strategy

### Unit Tests (pytest)

- `tests/test_auth_service.py` — AuthService unit tests: password hashing, token issuance, token verification, duplicate email rejection, inactive account rejection.
- `tests/test_auth_controller.py` — Login endpoint: valid credentials, wrong password, wrong email, missing fields, inactive account.
- `tests/test_require_auth.py` — Middleware: valid token, expired token, malformed token, missing header, X-User-Id fallback, Bearer takes precedence over X-User-Id.
- `tests/test_lead_ownership.py` — Lead isolation: create lead as user A, verify user B gets 404 on GET/PUT/DELETE.
- `tests/test_resource_isolation.py` — Marketing list, import job, scoring weights isolation.

### Property-Based Tests (Hypothesis)

See Correctness Properties section below. Each property is implemented as a Hypothesis `@given` test in `tests/test_auth_properties.py` and `tests/test_lead_isolation_properties.py`, with a minimum of 100 iterations per property.

### Frontend Tests (Vitest + React Testing Library)

- `LoginPage.test.tsx` — renders form fields, shows validation error on empty submit, shows generic error on 401, redirects on success.
- `AuthContext.test.tsx` — restores session from valid token, clears expired token, logout clears storage.
- `api.test.ts` — request interceptor attaches Bearer token, 401 response interceptor clears token and redirects.

### Integration Tests

- Migration idempotency: run migration twice, verify no errors.
- Ben's account seeding: verify `ben.d.staples.7@gmail.com` exists after migration.
- All existing leads assigned to Ben after migration.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: User record completeness

*For any* valid user creation input (email, password, display name), the created User record SHALL contain all required fields: a non-empty `user_id`, `email_lower` equal to `email.lower()`, a `password_hash` that is not equal to the submitted password, `is_active` equal to `True`, and UTC `created_at` / `updated_at` timestamps.

**Validates: Requirements 1.1**

### Property 2: Email uniqueness is case-insensitive

*For any* email string `e`, if a User with `email_lower = e.lower()` already exists, then any attempt to create another User with any case variant of `e` SHALL be rejected with HTTP 409.

**Validates: Requirements 1.2, 1.3**

### Property 3: Plaintext password never appears in any response

*For any* password string `p` submitted in any API request (login, registration, or any validation failure), the string `p` SHALL NOT appear as a substring of any API response body.

**Validates: Requirements 1.3, 1.4**

### Property 4: Invalid inputs return 400 without creating a user

*For any* registration request where at least one required field (email, password, or display name) is absent or empty, the response SHALL be HTTP 400 and no User record SHALL be created in the database.

**Validates: Requirements 1.5**

### Property 5: Successful login response contains all identity fields

*For any* registered active User, a login request with correct credentials SHALL return a response containing `session_token`, `user_id`, `email`, and `display_name`, where `user_id` matches the User's stored `user_id`.

**Validates: Requirements 2.1**

### Property 6: Invalid credentials produce identical 401 responses

*For any* login attempt with an unrecognized email OR a recognized email with an incorrect password, the response SHALL be HTTP 401 with the identical message body, making the two failure modes indistinguishable.

**Validates: Requirements 2.2**

### Property 7: Issued tokens have a lifetime of at most 8 hours

*For any* token issued by `AuthService.issue_token()`, the difference `exp - iat` SHALL be less than or equal to 28800 seconds (8 hours).

**Validates: Requirements 2.4, 8.5**

### Property 8: Valid Bearer token populates g.user_id with token subject

*For any* valid JWT with subject claim `sub = user_id`, a request carrying `Authorization: Bearer <token>` SHALL result in `g.user_id == user_id` and the route handler SHALL execute.

**Validates: Requirements 3.1**

### Property 9: Invalid or absent tokens produce 401

*For any* request carrying an absent Authorization header, a non-Bearer Authorization header, a malformed JWT (fewer than 3 segments), a JWT with an invalid signature, or a JWT with an expired `exp` claim, the response SHALL be HTTP 401 and the route handler SHALL NOT execute.

**Validates: Requirements 3.2**

### Property 10: Bearer token identity takes precedence over X-User-Id

*For any* request carrying both a valid Bearer token with subject `user_a` and an `X-User-Id` header with value `user_b` (where `user_a ≠ user_b`), `g.user_id` SHALL equal `user_a`.

**Validates: Requirements 3.4**

### Property 11: Lead ownership is assigned to the creating user

*For any* authenticated user `u` creating any lead, the created lead's `owner_user_id` SHALL equal `u.user_id`.

**Validates: Requirements 4.2**

### Property 12: Lead list returns only the authenticated user's leads

*For any* two distinct users `u1` and `u2`, each with one or more leads, querying the lead list as `u1` SHALL return only leads where `owner_user_id == u1.user_id`, and SHALL NOT return any lead owned by `u2`.

**Validates: Requirements 4.3**

### Property 13: Cross-user lead access returns 404

*For any* two distinct users `u1` and `u2`, and any lead `L` owned by `u1`, a GET, PUT, or DELETE request for `L` authenticated as `u2` SHALL return HTTP 404.

**Validates: Requirements 4.4**

### Property 14: Resource isolation — marketing lists and import jobs

*For any* two distinct users `u1` and `u2`, each with marketing lists and import jobs, querying those resources as `u1` SHALL return only records where `user_id == u1.user_id`, and cross-user access to a specific record SHALL return HTTP 404.

**Validates: Requirements 4.5, 6.1, 6.2, 6.3, 6.4**

### Property 15: Post-migration lead ownership invariant

*For all* lead rows in the database after the migration runs, `owner_user_id` SHALL be non-NULL.

**Validates: Requirements 5.3**

### Property 16: Authorization header is attached to every API request when a token exists

*For any* JWT string stored in `localStorage` as `session_token`, every Axios request made by the frontend SHALL include the header `Authorization: Bearer <token>` where `<token>` is the stored JWT string.

**Validates: Requirements 7.6**

### Property 17: Token expiry is validated on app load

*For any* JWT stored in `localStorage` with an `exp` claim in the past, loading the frontend application SHALL result in the token being removed from `localStorage` and the user being treated as unauthenticated.

**Validates: Requirements 8.1**
