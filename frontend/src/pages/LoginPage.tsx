/**
 * LoginPage — credential-based login form.
 *
 * Calls AuthContext.login() which POSTs to /api/auth/login and stores the JWT.
 * On success, redirects to the page the user was trying to reach (state.from)
 * or falls back to the root route.
 *
 * Requirements: 2.1, 2.2, 2.3
 */
import { useState, FormEvent } from 'react'
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Redirect destination — check returnUrl query param first (set by 401 interceptor),
  // then fall back to location.state.from (set by ProtectedRoute), then root.
  const from =
    new URLSearchParams(location.search).get('returnUrl') ??
    (location.state as { from?: Location })?.from?.pathname ??
    '/'

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setIsLoading(true)

    try {
      await login(email, password)
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
