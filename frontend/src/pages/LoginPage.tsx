/**
 * LoginPage — credential-based login form.
 *
 * Calls AuthContext.login() which POSTs to /api/auth/login and stores the JWT.
 * On success, redirects to the page the user was trying to reach (state.from)
 * or falls back to the root route.
 *
 * If the server returns { setup_required: true, setup_token: "..." }, the user
 * is redirected to /set-password with the token passed via navigation state
 * (never stored in localStorage).
 *
 * Requirements: 2.1, 2.2, 2.3, 9.6
 */
import { useState, useEffect, FormEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import { useAuth } from '@/context/AuthContext'
import api from '@/services/api'

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LoginPage() {
  const { loginWithToken } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // Redirect destination — check returnUrl query param first (set by 401 interceptor),
  // then fall back to location.state.from (set by ProtectedRoute), then root.
  // Validate returnUrl: only use it if it's a safe internal path.
  const rawReturnUrl = new URLSearchParams(location.search).get('returnUrl') ?? ''
  const isInternalPath = (() => {
    if (!rawReturnUrl.startsWith('/') || rawReturnUrl.startsWith('//')) return false
    try {
      const parsed = new URL(rawReturnUrl, window.location.origin)
      return parsed.origin === window.location.origin
    } catch {
      return false
    }
  })()
  const from =
    (isInternalPath ? rawReturnUrl : null) ??
    (location.state as { from?: Location })?.from?.pathname ??
    (location.pathname !== '/login' && location.pathname !== '/set-password'
      ? location.pathname
      : '/')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  // If redirected back here via returnUrl, the session expired or the DB is
  // unavailable — show an immediate message rather than a blank form.
  const [error, setError] = useState<string | null>(
    rawReturnUrl ? 'Your session could not be verified. Please sign in again.' : null
  )
  const [isLocalFallback, setIsLocalFallback] = useState(false)

  // Check on mount whether the backend is running on the local DB fallback
  // (e.g. cloud DB quota exceeded). If so, show a clear warning so the user
  // understands why their cloud credentials won't work.
  useEffect(() => {
    api.get<{ db_mode?: string }>('/health')
      .then((res) => {
        if (res.data?.db_mode === 'local_fallback') {
          setIsLocalFallback(true)
        }
      })
      .catch(() => {
        // Health check failure is non-critical — don't block the login form
      })
  }, [])

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setIsLoading(true)

    try {
      // Call the login endpoint directly so we can inspect the response before
      // deciding whether to store the session token or redirect to /set-password.
      const response = await api.post<{
        session_token?: string
        user_id?: string
        setup_required?: boolean
        setup_token?: string
      }>('/auth/login', { email, password })

      // Handle first-time password setup flow (Req 9.6)
      // setup_token is passed via navigation state only — never stored in localStorage.
      if (response.data.setup_required === true) {
        navigate('/set-password', { state: { setupToken: response.data.setup_token } })
        return
      }

      // Normal login path — store the token we already have via loginWithToken.
      // This avoids a second network request since we already have the response.
      const { session_token, user_id } = response.data as { session_token: string; user_id: string }
      loginWithToken(session_token, user_id)
      navigate(from, { replace: true })
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Login failed. Please try again.'
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Container maxWidth="xs">
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
        }}
      >
        <Paper elevation={3} sx={{ p: 4, width: '100%' }}>
          <Typography variant="h5" component="h1" gutterBottom textAlign="center">
            Real Estate Analysis Platform
          </Typography>
          <Typography
            variant="body2"
            color="text.secondary"
            textAlign="center"
            sx={{ mb: 3 }}
          >
            Sign in to your account
          </Typography>

          {isLocalFallback && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              The cloud database is temporarily unavailable. You are connected to
              a local copy — your usual account may not be available. Contact your
              administrator or try again later.
            </Alert>
          )}

          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
              {error}
            </Alert>
          )}

          <Box component="form" onSubmit={handleSubmit} noValidate>
            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              fullWidth
              required
              autoComplete="email"
              autoFocus
              disabled={isLoading}
              sx={{ mb: 2 }}
              inputProps={{ 'aria-label': 'Email address' }}
            />
            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              fullWidth
              required
              autoComplete="current-password"
              disabled={isLoading}
              sx={{ mb: 3 }}
              inputProps={{ 'aria-label': 'Password' }}
            />
            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="large"
              disabled={isLoading || !email || !password}
              startIcon={isLoading ? <CircularProgress size={18} color="inherit" /> : null}
              aria-label="Sign in"
            >
              {isLoading ? 'Signing in…' : 'Sign In'}
            </Button>
          </Box>
        </Paper>
      </Box>
    </Container>
  )
}
