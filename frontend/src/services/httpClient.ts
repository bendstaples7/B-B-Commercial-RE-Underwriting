import axios, { AxiosError, AxiosInstance } from 'axios'
import type { ErrorResponse } from '@/types'

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
  (error: AxiosError<ErrorResponse>) => {
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

      // Extract the real message — backend uses several shapes:
      //   { error: { message: "..." } }  — structured error object
      //   { error: "..." }               — plain string error (auth endpoints)
      //   { message: "..." }             — direct message field
      // Prefer `message` when `error` is a generic label like "Invalid request".
      const errorField = (errorData as any)?.error
      const detailedMessage =
        typeof (errorData as any)?.message === 'string'
          ? (errorData as any).message
          : null
      const genericErrorLabels = new Set([
        'Invalid request',
        'Validation error',
        'An error occurred',
        'Internal server error',
        'HTTP error',
      ])
      const message =
        errorField?.message
        || (typeof errorField === 'string'
          && genericErrorLabels.has(errorField)
          && detailedMessage
          ? detailedMessage
          : null)
        || (typeof errorField === 'string' ? errorField : null)
        || detailedMessage
        || 'An error occurred'

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
