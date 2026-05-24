/**
 * LoginPage — credential-based login for multi-user support.
 *
 * Renders email + password fields and a submit button.
 * On success, redirects to `location.state.from` or `/` as fallback.
 * On 401, shows a generic error without revealing which field was wrong (Req 7.4).
 * On other errors, shows a generic "unexpected error" message.
 * Client-side validation prevents empty-field submissions (Req 7.7).
 */
import { useState, FormEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Box,
  Button,
  TextField,
  Typography,
  Alert,
  Paper,
  CircularProgress,
} from '@mui/material'
import { useAuth } from '@/context/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [emailError, setEmailError] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [serverError, setServerError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Where to redirect after a successful login.
  // location.state.from may be a Location object (from AuthGuard) or a plain
  // string path (from tests / direct navigation).
  const stateFrom = (location.state as { from?: string | { pathname?: string } } | null)?.from
  const from =
    typeof stateFrom === 'string'
      ? stateFrom
      : stateFrom?.pathname ?? '/'

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    // Client-side validation — Requirement 7.7
    let hasError = false
    if (!email.trim()) {
      setEmailError('Email is required.')
      hasError = true
    }
    if (!password) {
      setPasswordError('Password is required.')
      hasError = true
    }
    if (hasError) return

    setServerError(null)
    setIsSubmitting(true)

    try {
      await login(email.trim(), password)
      navigate(from, { replace: true })
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 401) {
        // Generic error — do not reveal whether email or password was wrong (Req 7.4)
        setServerError('Invalid email or password. Please try again.')
      } else {
        // Non-auth errors (network, 500, etc.)
        setServerError('An unexpected error occurred. Please try again.')
      }
      // Do NOT clear credentials (Req 7.4)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'grey.100',
        p: 2,
      }}
    >
      <Paper
        elevation={3}
        sx={{ p: { xs: 3, sm: 4 }, width: '100%', maxWidth: 400 }}
      >
        <Typography variant="h5" component="h1" gutterBottom fontWeight={600}>
          Sign In
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          B&amp;B Real Estate Analyzer
        </Typography>

        {serverError && (
          <Alert severity="error" sx={{ mb: 2 }} role="alert">
            {serverError}
          </Alert>
        )}

        <Box component="form" onSubmit={handleSubmit} noValidate>
          <TextField
            label="Email"
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              if (emailError) setEmailError(null)
            }}
            fullWidth
            required
            autoComplete="email"
            autoFocus
            sx={{ mb: emailError ? 0.5 : 2 }}
            inputProps={{
              'aria-label': 'Email address',
              'aria-required': 'true',
            }}
            error={!!emailError}
          />
          {emailError && (
            <Alert severity="warning" sx={{ mb: 1.5 }} role="alert">
              {emailError}
            </Alert>
          )}

          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              if (passwordError) setPasswordError(null)
            }}
            fullWidth
            required
            autoComplete="current-password"
            sx={{ mb: passwordError ? 0.5 : 3 }}
            inputProps={{
              'aria-label': 'Password',
              'aria-required': 'true',
            }}
            error={!!passwordError}
          />
          {passwordError && (
            <Alert severity="warning" sx={{ mb: 2 }} role="alert">
              {passwordError}
            </Alert>
          )}

          <Button
            type="submit"
            variant="contained"
            fullWidth
            size="large"
            disabled={isSubmitting}
            aria-label={isSubmitting ? 'Signing in' : 'Sign in'}
          >
            {isSubmitting ? (
              <>
                <CircularProgress size={20} color="inherit" sx={{ mr: 1 }} />
                Signing in…
              </>
            ) : (
              'Sign In'
            )}
          </Button>
        </Box>
      </Paper>
    </Box>
  )
}

export default LoginPage
