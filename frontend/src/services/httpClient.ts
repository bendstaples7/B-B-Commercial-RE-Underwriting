import axios, { AxiosError, AxiosInstance } from 'axios'
import { isApiErrorEnvelope } from '@/services/apiErrorEnvelopes'

type ApiErrorPayload = {
  error?: string | { message?: unknown }
  message?: unknown
}

function asApiErrorPayload(value: unknown): ApiErrorPayload {
  return value != null && typeof value === 'object'
    ? value as ApiErrorPayload
    : {}
}

/** True for backend `error: "SomeExceptionClassName"` wrappers. */
function looksLikeExceptionClassName(value: string): boolean {
  return /^[A-Z][A-Za-z0-9]+(?:Error|Exception|Violation)$/.test(value)
}

/** Map a backend JSON error body to the sentence shown in the UI. */
export function userFacingApiErrorMessage(errorData: unknown): string {
  const payload = asApiErrorPayload(errorData)
  const errorField = payload.error
  const detailedMessage =
    typeof payload.message === 'string'
      ? payload.message
      : null
  const nestedMessage =
    errorField != null
      && typeof errorField === 'object'
      && typeof errorField.message === 'string'
      ? errorField.message
      : null
  // Prefer the human message over generic/envelope labels and Exception class names
  // (command-center handle_errors returns error: e.__class__.__name__).
  if (nestedMessage) return nestedMessage
  if (
    typeof errorField === 'string'
    && detailedMessage
    && (isApiErrorEnvelope(errorField) || looksLikeExceptionClassName(errorField))
  ) {
    return detailedMessage
  }
  if (typeof errorField === 'string') return errorField
  return detailedMessage || 'An error occurred'
}


// Create axios instance with default config
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 second timeout
})

// Request interceptor — sends user identity via header, not body.
// Injecting user_id into the request body breaks Marshmallow schemas that
// don't declare it, causing 400 validation errors on endpoints like /confirm.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('session_token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    // Keep X-User-Id for backward compatibility during transition
    const userId = localStorage.getItem('user_id') || 'default_user'
    config.headers['X-User-Id'] = userId
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<unknown>) => {
    if (error.response) {
      // Server responded with error status
      const errorData = error.response.data
      const url = error.config?.url ?? 'unknown'
      const status = error.response.status

      // Handle 401 Unauthorized — clear session and redirect to login.
      // Exclude /auth/login itself: a 401 there means wrong credentials,
      // not an expired session, so the LoginPage handles it directly.
      if (status === 401 && !url.includes('/auth/login')) {
        const returnUrl = window.location.pathname + window.location.search
        localStorage.removeItem('session_token')
        localStorage.removeItem('user_id')
        window.location.href = `/login?returnUrl=${encodeURIComponent(returnUrl)}`
        return Promise.reject(error)
      }

      const message = userFacingApiErrorMessage(errorData)

      console.error(`[API] ${status} ${url}:`, message, errorData)

      // Handle specific error codes
      if (status === 429) {
        throw new Error('Rate limit exceeded. Please try again later.')
      }

      throw new Error(message)
    } else if (error.request) {
      // Request made but no response received
      console.error('[API] Network error — no response received:', error.request)
      throw new Error('Network error. Please check your connection.')
    } else {
      // Something else happened
      console.error('[API] Request setup error:', error.message)
      throw new Error(error.message)
    }
  }
)

export default api
