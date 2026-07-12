/**
 * AuthContext tests
 *
 * Unit tests and property-based tests for AuthProvider token lifecycle.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ReactNode } from 'react'
import fc from 'fast-check'
import { AuthProvider, useAuth, validateStoredToken } from './AuthContext'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * UTF-8 safe base64url encoder.
 * btoa() only handles Latin-1; this handles the full Unicode range.
 */
function base64UrlEncode(str: string): string {
  const bytes = new TextEncoder().encode(str)
  const binary = Array.from(bytes).map((b) => String.fromCharCode(b)).join('')
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * Build a minimal JWT with the given payload claims.
 * The signature is a dummy value — AuthContext only decodes client-side.
 */
function buildJwt(payload: Record<string, unknown>): string {
  const header = base64UrlEncode(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = base64UrlEncode(JSON.stringify(payload))
  return `${header}.${body}.fakesignature`
}

/**
 * Build a structurally valid JWT with a non-expired payload, merging in any
 * extra claims. Used by property tests that need a token that passes all
 * validation rules except the one under test.
 */
function buildToken(extraClaims: Record<string, unknown>): string {
  const nowSeconds = Math.floor(Date.now() / 1000)
  const basePayload: Record<string, unknown> = {
    sub: 'user-prop-test',
    email: 'prop@example.com',
    display_name: 'Prop Test User',
    iat: nowSeconds - 60,
    exp: nowSeconds + 3600,
  }
  return buildJwt({ ...basePayload, ...extraClaims })
}

/**
 * Wrapper that provides MemoryRouter (required by useNavigate inside AuthProvider)
 * and AuthProvider itself.
 */
function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <AuthProvider>{children}</AuthProvider>
    </MemoryRouter>
  )
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

describe('AuthContext — unit tests', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('restores session from a valid non-expired token on mount', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const iat = nowSeconds - 60
    const exp = nowSeconds + 3600 // 1 hour from now, well within 30-day limit
    const token = buildJwt({
      sub: 'user-123',
      email: 'test@example.com',
      display_name: 'Test User',
      iat,
      exp,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).not.toBeNull()
    expect(result.current.user?.user_id).toBe('user-123')
    expect(result.current.user?.email).toBe('test@example.com')
    expect(result.current.user?.display_name).toBe('Test User')
    expect(localStorage.getItem('session_token')).toBe(token)
  })

  it('clears an expired token on mount and treats user as unauthenticated', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const iat = nowSeconds - 7200
    const exp = nowSeconds - 1 // 1 second in the past
    const token = buildJwt({
      sub: 'user-456',
      email: 'expired@example.com',
      display_name: 'Expired User',
      iat,
      exp,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
  })

  it('clears a malformed/unparseable token on mount without redirecting', async () => {
    localStorage.setItem('session_token', 'not.a.valid.jwt.at.all')

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
  })

  it('rejects a token where exp - iat > 2592000 (exceeds 30-day max lifetime)', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const iat = nowSeconds - 100
    const exp = nowSeconds + 2592001 // 1 second over the 30-day limit
    const token = buildJwt({
      sub: 'user-789',
      email: 'toolong@example.com',
      display_name: 'Long Token User',
      iat,
      exp,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
  })

  // -------------------------------------------------------------------------
  // is_admin decoding tests (Requirements 7.1, 7.2, 7.3, 7.4)
  // -------------------------------------------------------------------------

  it('validateStoredToken returns null for token with is_admin as a string', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const token = buildJwt({
      sub: 'user-admin-str',
      email: 'admin@example.com',
      display_name: 'Admin User',
      is_admin: 'true', // string — malformed
      iat: nowSeconds - 60,
      exp: nowSeconds + 3600,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
  })

  it('validateStoredToken returns null for token with is_admin as a number', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const token = buildJwt({
      sub: 'user-admin-num',
      email: 'admin@example.com',
      display_name: 'Admin User',
      is_admin: 1, // number — malformed
      iat: nowSeconds - 60,
      exp: nowSeconds + 3600,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
  })

  it('validateStoredToken returns null for token with is_admin as null', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const token = buildJwt({
      sub: 'user-admin-null',
      email: 'admin@example.com',
      display_name: 'Admin User',
      is_admin: null, // null — malformed
      iat: nowSeconds - 60,
      exp: nowSeconds + 3600,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
  })

  it('validateStoredToken returns null for token with is_admin as an object', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const token = buildJwt({
      sub: 'user-admin-obj',
      email: 'admin@example.com',
      display_name: 'Admin User',
      is_admin: { value: true }, // object — malformed
      iat: nowSeconds - 60,
      exp: nowSeconds + 3600,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
  })

  it('validateStoredToken returns AuthUser with is_admin=true for valid admin token', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const token = buildJwt({
      sub: 'user-admin-true',
      email: 'admin@example.com',
      display_name: 'Admin User',
      is_admin: true,
      iat: nowSeconds - 60,
      exp: nowSeconds + 3600,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).not.toBeNull()
    expect(result.current.user?.is_admin).toBe(true)
    expect(localStorage.getItem('session_token')).toBe(token)
  })

  it('validateStoredToken returns AuthUser with is_admin=false for valid non-admin token', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const token = buildJwt({
      sub: 'user-nonadmin',
      email: 'user@example.com',
      display_name: 'Regular User',
      is_admin: false,
      iat: nowSeconds - 60,
      exp: nowSeconds + 3600,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).not.toBeNull()
    expect(result.current.user?.is_admin).toBe(false)
    expect(localStorage.getItem('session_token')).toBe(token)
  })

  it('validateStoredToken returns AuthUser with is_admin=false when claim is absent', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    // No is_admin claim in the payload
    const token = buildJwt({
      sub: 'user-no-claim',
      email: 'user@example.com',
      display_name: 'No Claim User',
      iat: nowSeconds - 60,
      exp: nowSeconds + 3600,
    })
    localStorage.setItem('session_token', token)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.user).not.toBeNull()
    expect(result.current.user?.is_admin).toBe(false)
    expect(localStorage.getItem('session_token')).toBe(token)
  })

  it('logout() removes token from localStorage and clears user state', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const iat = nowSeconds - 60
    const exp = nowSeconds + 3600
    const token = buildJwt({
      sub: 'user-logout',
      email: 'logout@example.com',
      display_name: 'Logout User',
      iat,
      exp,
    })
    localStorage.setItem('session_token', token)
    localStorage.setItem('user_id', 'user-logout')

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.user).not.toBeNull()

    act(() => {
      result.current.logout()
    })

    expect(result.current.user).toBeNull()
    expect(result.current.token).toBeNull()
    expect(localStorage.getItem('session_token')).toBeNull()
    expect(localStorage.getItem('user_id')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Property 17: Token expiry is validated on app load
//
// Validates: Requirements 8.1
//
// For any JWT stored in localStorage with an exp claim in the past, loading
// the frontend application SHALL result in the token being removed from
// localStorage and the user being treated as unauthenticated.
// ---------------------------------------------------------------------------

describe('Property 17: Token expiry is validated on app load', () => {
  /**
   * **Validates: Requirements 8.1**
   *
   * For any JWT with exp in the past, after AuthProvider mounts:
   *   - localStorage.getItem('session_token') is null
   *   - result.current.user is null
   */
  it('removes any expired token and sets user to null on mount', async () => {
    await fc.assert(
      fc.asyncProperty(
        // Generate a past exp timestamp: anywhere from 1 second to 10 years ago
        fc.integer({ min: 1, max: 10 * 365 * 24 * 3600 }),
        // Generate a valid iat that is before exp (iat = exp - some positive delta)
        fc.integer({ min: 1, max: 30 * 24 * 3600 }),
        // Generate plausible user identity fields
        fc.string({ minLength: 1, maxLength: 36 }).filter(s => s.trim().length > 0),
        fc.emailAddress(),
        fc.string({ minLength: 1, maxLength: 100 }).filter(s => s.trim().length > 0),
        async (secondsAgo, tokenLifetime, userId, email, displayName) => {
          localStorage.clear()

          const nowSeconds = Math.floor(Date.now() / 1000)
          const exp = nowSeconds - secondsAgo          // always in the past
          const iat = exp - tokenLifetime              // iat before exp

          const token = buildJwt({
            sub: userId,
            email,
            display_name: displayName,
            iat,
            exp,
          })

          localStorage.setItem('session_token', token)

          const { result, unmount } = renderHook(() => useAuth(), { wrapper })

          await waitFor(() => expect(result.current.isLoading).toBe(false))

          // Core assertions: expired token must be cleared and user must be null
          expect(
            localStorage.getItem('session_token'),
            `Expected session_token to be removed for exp=${exp} (${secondsAgo}s ago)`
          ).toBeNull()

          expect(
            result.current.user,
            `Expected user to be null for exp=${exp} (${secondsAgo}s ago)`
          ).toBeNull()

          unmount()
          localStorage.clear()
        }
      ),
      { numRuns: 50 }
    )
  })
})

// ---------------------------------------------------------------------------
// Property 2: Malformed `is_admin` claim rejection
//
// Validates: Requirements 1.5, 7.4
//
// For any JWT token where the `is_admin` claim is present but not a boolean
// (e.g. a string, integer, null, or object), the frontend `validateStoredToken`
// function SHALL return `null`, causing the token to be removed from localStorage
// and the user to be treated as unauthenticated.
// ---------------------------------------------------------------------------

describe('Property 2: Malformed is_admin claim rejection', () => {
  /**
   * **Validates: Requirements 1.5, 7.4**
   *
   * For any non-boolean value of `is_admin` in the JWT payload,
   * `validateStoredToken` must return null.
   */
  it('rejects tokens with non-boolean is_admin for any non-boolean value', () => {
    fc.assert(
      fc.property(
        fc.oneof(fc.string(), fc.integer(), fc.constant(null), fc.object()),
        (nonBooleanValue) => {
          const token = buildToken({ is_admin: nonBooleanValue })
          expect(validateStoredToken(token)).toBeNull()
        }
      ),
      { numRuns: 100 }
    )
  })
})

// ---------------------------------------------------------------------------
// Property 11: AuthUser.is_admin decoding
//
// Validates: Requirements 7.1, 7.2, 7.3
//
// For any valid JWT payload, the is_admin field on the decoded AuthUser SHALL
// equal the boolean value of the is_admin claim in the payload, defaulting to
// false when the claim is absent.
// ---------------------------------------------------------------------------

describe('Property 11: AuthUser.is_admin decoding', () => {
  /**
   * **Validates: Requirements 7.1, 7.2, 7.3**
   *
   * For any boolean is_admin value, validateStoredToken must decode it correctly.
   */
  it('decodes is_admin correctly for any boolean value', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        (isAdmin) => {
          const token = buildToken({ is_admin: isAdmin })
          const user = validateStoredToken(token)
          expect(user?.is_admin).toBe(isAdmin)
        }
      ),
      { numRuns: 100 }
    )
  })
})
