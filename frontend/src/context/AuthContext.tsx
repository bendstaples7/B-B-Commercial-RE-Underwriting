/**
 * AuthContext — credential-based authentication for multi-user support.
 *
 * Provides:
 *   - `user`      — the decoded AuthUser from the stored JWT, or null
 *   - `token`     — the raw JWT string, or null
 *   - `login()`   — POST /api/auth/login, store token + user_id, update state
 *   - `logout()`  — clear localStorage, reset state, redirect to /login
 *   - `isLoading` — true only during the initial token validation on mount
 *
 * Token validation rules (client-side, signature verified server-side):
 *   1. Token must be a valid 3-segment JWT with a decodable payload.
 *   2. `exp` claim must be in the future (compared to Date.now() / 1000).
 *   3. `exp - iat` must be ≤ 28800 seconds (8 hours) — rejects tokens with
 *      an unexpectedly long lifetime.
 *
 * Usage:
 *   const { user, login, logout, isLoading } = useAuth()
 */
import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from 'react'
import { useNavigate } from 'react-router-dom'
import api from '@/services/api'
import type { AuthUser, AuthContextValue } from '@/types'

// ---------------------------------------------------------------------------
// JWT helpers (client-side decode only — no signature verification)
// ---------------------------------------------------------------------------

const MAX_TOKEN_LIFETIME_SECONDS = 28800 // 8 hours

/**
 * Decode the payload of a JWT without verifying the signature.
 * Returns null if the token is malformed.
 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    // Base64url → Base64 → JSON
    // Add padding so atob doesn't throw on unpadded base64url strings
    let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    while (base64.length % 4 !== 0) base64 += '='
    const json = atob(base64)
    return JSON.parse(json) as Record<string, unknown>
  } catch {
    return null
  }
}

/**
 * Validate a stored JWT against client-side rules.
 * Returns the decoded AuthUser on success, or null if the token should be rejected.
 *
 * Exported for use in property-based tests.
 */
export function validateStoredToken(token: string): AuthUser | null {
  const payload = decodeJwtPayload(token)
  if (!payload) return null

  const exp = typeof payload.exp === 'number' ? payload.exp : null
  const iat = typeof payload.iat === 'number' ? payload.iat : null

  if (exp === null || iat === null) return null

  const nowSeconds = Date.now() / 1000

  // Rule 1: token must not be expired
  if (exp <= nowSeconds) return null

  // Rule 2: token lifetime must not exceed 8 hours
  if (exp - iat > MAX_TOKEN_LIFETIME_SECONDS) return null

  // Extract user identity from claims
  const user_id = typeof payload.sub === 'string' ? payload.sub : null
  const email = typeof payload.email === 'string' ? payload.email : null
  const display_name =
    typeof payload.display_name === 'string' ? payload.display_name : null

  if (!user_id || !email || !display_name) return null

  // Extract is_admin: if present but not a boolean, the token is malformed
  const rawIsAdmin = payload.is_admin
  if (rawIsAdmin !== undefined && typeof rawIsAdmin !== 'boolean') return null
  const is_admin = typeof rawIsAdmin === 'boolean' ? rawIsAdmin : false

  return { user_id, email, display_name, is_admin }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue>({
  user: null,
  token: null,
  login: async () => {},
  logout: () => {},
  isLoading: true,
})

export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const navigate = useNavigate()

  // On mount: restore session from localStorage if the token is still valid
  useEffect(() => {
    const storedToken = localStorage.getItem('session_token')
    if (storedToken) {
      const validatedUser = validateStoredToken(storedToken)
      if (validatedUser) {
        setToken(storedToken)
        setUser(validatedUser)
      } else {
        // Token is expired, malformed, or has an invalid lifetime — remove it
        localStorage.removeItem('session_token')
        localStorage.removeItem('user_id')
      }
    }
    setIsLoading(false)
  }, [])

  /**
   * POST /api/auth/login with email + password.
   * On success, stores session_token and user_id in localStorage and updates state.
   * Throws on failure so the caller (LoginPage) can display an error.
   */
  const login = useCallback(
    async (email: string, password: string): Promise<void> => {
      const response = await api.post<{
        session_token: string
        user_id: string
        email: string
        display_name: string
      }>('/auth/login', { email, password })

      const { session_token, user_id, email: respEmail, display_name } = response.data

      localStorage.setItem('session_token', session_token)
      localStorage.setItem('user_id', user_id)

      // Decode is_admin from the token payload (defaults to false if absent)
      const tokenPayload = decodeJwtPayload(session_token)
      const rawIsAdmin = tokenPayload?.is_admin
      const is_admin = typeof rawIsAdmin === 'boolean' ? rawIsAdmin : false

      setToken(session_token)
      setUser({ user_id, email: respEmail, display_name, is_admin })
    },
    []
  )

  /**
   * Clear the session from localStorage and context state, then redirect to /login.
   */
  const logout = useCallback(() => {
    localStorage.removeItem('session_token')
    localStorage.removeItem('user_id')
    setToken(null)
    setUser(null)
    navigate('/login')
  }, [navigate])

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  )
}
