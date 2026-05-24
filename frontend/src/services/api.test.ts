/**
 * Tests for the Axios request and response interceptors in api.ts
 *
 * Validates: Requirements 7.6, 8.3
 *
 * Strategy: We intercept outgoing requests by replacing the axios adapter
 * with a custom one that captures the final config (including headers set
 * by interceptors) without making a real network call. For response
 * interceptor tests we simulate error responses via the same adapter.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import api from './api'

/**
 * Installs a one-shot adapter on the api instance that resolves immediately
 * and returns the request config so we can inspect the headers.
 */
function captureNextRequest(): Promise<Record<string, string>> {
  return new Promise((resolve) => {
    const originalAdapter = api.defaults.adapter
    api.defaults.adapter = (config) => {
      // Restore the original adapter immediately
      api.defaults.adapter = originalAdapter
      // Resolve with the headers that were set by interceptors
      resolve((config.headers ?? {}) as Record<string, string>)
      // Return a valid axios response so the caller doesn't throw
      return Promise.resolve({
        data: {},
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      })
    }
  })
}

/**
 * Installs a one-shot adapter that rejects with a simulated Axios error
 * carrying the given HTTP status code, so we can exercise response interceptors.
 */
function simulateErrorResponse(status: number): Promise<void> {
  return new Promise((resolve) => {
    const originalAdapter = api.defaults.adapter
    api.defaults.adapter = (config) => {
      api.defaults.adapter = originalAdapter
      // Build a minimal AxiosError-shaped rejection
      const err: any = new Error(`Request failed with status code ${status}`)
      err.isAxiosError = true
      err.config = config
      err.response = {
        status,
        statusText: status === 401 ? 'Unauthorized' : 'Error',
        data: { message: 'error' },
        headers: {},
        config,
      }
      resolve()
      return Promise.reject(err)
    }
  })
}

describe('Request interceptor — Authorization header (Validates: Requirements 7.6)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('attaches Authorization: Bearer <token> when session_token is in localStorage', async () => {
    const token = 'test.jwt.token'
    localStorage.setItem('session_token', token)

    const headersPromise = captureNextRequest()
    // Fire a request (it won't actually hit the network)
    api.get('/health').catch(() => {})
    const headers = await headersPromise

    expect(headers['Authorization']).toBe(`Bearer ${token}`)
  })

  it('does NOT attach Authorization header when no session_token in localStorage', async () => {
    // No token set

    const headersPromise = captureNextRequest()
    api.get('/health').catch(() => {})
    const headers = await headersPromise

    expect(headers['Authorization']).toBeUndefined()
  })

  it('attaches X-User-Id for backward compatibility when token is present', async () => {
    const token = 'test.jwt.token'
    const userId = 'user-123'
    localStorage.setItem('session_token', token)
    localStorage.setItem('user_id', userId)

    const headersPromise = captureNextRequest()
    api.get('/health').catch(() => {})
    const headers = await headersPromise

    expect(headers['Authorization']).toBe(`Bearer ${token}`)
    expect(headers['X-User-Id']).toBe(userId)
  })

  it('uses default_user for X-User-Id when user_id is not in localStorage', async () => {
    const headersPromise = captureNextRequest()
    api.get('/health').catch(() => {})
    const headers = await headersPromise

    expect(headers['X-User-Id']).toBe('default_user')
  })
})

/**
 * Property 16: Authorization header is attached to every API request when a token exists
 *
 * Validates: Requirements 7.6
 *
 * For any JWT string stored in localStorage as `session_token`, every Axios
 * request made by the frontend SHALL include the header
 * `Authorization: Bearer <token>` where `<token>` is the stored JWT string.
 *
 * Strategy: Generate arbitrary JWT-like strings (header.payload.signature
 * format) and for each one, set it in localStorage, fire a request via the
 * captureNextRequest helper, and assert the Authorization header matches.
 */
describe('Property 16 — Authorization header on every request (Validates: Requirements 7.6)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  /**
   * Generate a random base64url-like segment of the given length.
   * Uses only characters valid in a JWT segment (A-Z, a-z, 0-9, -, _).
   */
  function randomSegment(length: number): string {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    let result = ''
    for (let i = 0; i < length; i++) {
      result += chars[Math.floor(Math.random() * chars.length)]
    }
    return result
  }

  /**
   * Generate an arbitrary JWT-like string in header.payload.signature format.
   * Segment lengths are varied to cover a realistic range of token sizes.
   */
  function generateJwtLikeToken(headerLen = 36, payloadLen = 80, sigLen = 43): string {
    return `${randomSegment(headerLen)}.${randomSegment(payloadLen)}.${randomSegment(sigLen)}`
  }

  /**
   * A fixed set of representative token shapes to ensure deterministic
   * coverage alongside the randomly generated tokens below.
   */
  const representativeTokens: string[] = [
    // Minimal valid JWT-like token
    'a.b.c',
    // Typical HS256 JWT shape
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImVtYWlsIjoidGVzdEBleGFtcGxlLmNvbSIsImV4cCI6OTk5OTk5OTk5OX0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c',
    // Token with special-but-valid base64url characters
    'header-part_1.payload-part_2.signature-part_3',
    // Long token (simulates a token with many claims)
    `${randomSegment(50)}.${randomSegment(200)}.${randomSegment(86)}`,
    // Short token (edge case — still three segments)
    'x.y.z',
  ]

  it.each(representativeTokens)(
    'attaches Authorization: Bearer <token> for representative token: "%s"',
    async (token) => {
      localStorage.setItem('session_token', token)

      const headersPromise = captureNextRequest()
      api.get('/health').catch(() => {})
      const headers = await headersPromise

      expect(headers['Authorization']).toBe(`Bearer ${token}`)
    }
  )

  it('attaches Authorization: Bearer <token> for 50 randomly generated JWT-like tokens', async () => {
    // Run 50 iterations with randomly generated tokens to cover the property
    // across a wide range of token shapes and lengths.
    for (let i = 0; i < 50; i++) {
      // Vary segment lengths to exercise different token sizes
      const headerLen = 20 + Math.floor(Math.random() * 40)   // 20–59
      const payloadLen = 40 + Math.floor(Math.random() * 160)  // 40–199
      const sigLen = 30 + Math.floor(Math.random() * 60)       // 30–89

      const token = generateJwtLikeToken(headerLen, payloadLen, sigLen)

      localStorage.setItem('session_token', token)

      const headersPromise = captureNextRequest()
      api.get('/health').catch(() => {})
      const headers = await headersPromise

      expect(headers['Authorization']).toBe(`Bearer ${token}`)

      localStorage.clear()
    }
  })

  it('omits Authorization header when no session_token is set (property boundary)', async () => {
    // Confirm the property boundary: when no token exists, no header is attached.
    // This validates the "when a token exists" precondition of Property 16.
    const headersPromise = captureNextRequest()
    api.get('/health').catch(() => {})
    const headers = await headersPromise

    expect(headers['Authorization']).toBeUndefined()
  })
})

describe('Response interceptor — 401 handling (Validates: Requirements 8.3)', () => {
  let originalHref: string

  beforeEach(() => {
    localStorage.clear()
    // Capture the original descriptor so we can restore it after each test
    originalHref = window.location.href
    // Allow window.location.href to be set in jsdom (it is read-only by default)
    vi.stubGlobal('location', {
      ...window.location,
      href: originalHref,
      pathname: '/leads',
      search: '',
    })
  })

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('clears session_token and user_id from localStorage and redirects to /login on 401', async () => {
    // Seed localStorage with a session
    localStorage.setItem('session_token', 'existing.jwt.token')
    localStorage.setItem('user_id', 'user-abc')

    // Arrange: next request will receive a 401 response
    const adapterReady = simulateErrorResponse(401)

    // Act: fire the request (the response interceptor will handle the 401)
    const requestPromise = api.get('/leads').catch(() => {
      // Expected — the interceptor rejects after redirecting
    })

    await adapterReady
    await requestPromise

    // Assert: localStorage cleared
    expect(localStorage.getItem('session_token')).toBeNull()
    expect(localStorage.getItem('user_id')).toBeNull()

    // Assert: redirected to /login with returnUrl
    expect(window.location.href).toContain('/login')
    expect(window.location.href).toContain('returnUrl')
  })
})
