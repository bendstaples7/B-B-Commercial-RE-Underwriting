/**
 * SetPasswordPage — first-time password setup for admin-provisioned users.
 *
 * Accessed via /set-password after a login that returns setup_required=true.
 * The setup_token is passed via React Router location state (never localStorage).
 *
 * Requirements: 9.7, 9.8
 */
import { useState, FormEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import axios from 'axios'
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

export function SetPasswordPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { loginWithToken } = useAuth()

  // All hooks must be called unconditionally before any early return.
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  // Read the setup_token from navigation state — if absent, redirect to login.
  // This token is never stored in localStorage per Req 9.6.
  const setupToken = (location.state as { setupToken?: string } | null)?.setupToken
  if (!setupToken) {
    navigate('/login', { replace: true })
    return null
  }

  function validate(): string | null {
    if (!password) return 'New password is required.'
    if (!confirmPassword) return 'Please confirm your password.'
    if (password.length < 8) return 'Password must be at least 8 characters.'
    if (confirmPassword.length < 8) return 'Password must be at least 8 characters.'
    if (password !== confirmPassword) return 'Passwords do not match.'
    return null
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()

    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }

    setError(null)
    setIsLoading(true)

    try {
      // Call set-password using a standalone axios instance so the shared
      // api interceptor cannot overwrite the setup_token Authorization header
      // with a stale session_token from localStorage.
      const standaloneAxios = axios.create({
        baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
        headers: { 'Content-Type': 'application/json' },
      })
      const response = await standaloneAxios.post<{
        session_token: string
        user_id: string
      }>(
        '/auth/set-password',
        { new_password: password },
        { headers: { Authorization: `Bearer ${setupToken}` } }
      )

      // Update AuthContext state (and localStorage) atomically so the app
      // treats the user as authenticated before navigating to the home page.
      loginWithToken(response.data.session_token, response.data.user_id)
      navigate('/', { replace: true })
    } catch (err: unknown) {
      // Extract the error message from the Axios response if available.
      if (axios.isAxiosError(err) && err.response?.data) {
        const data = err.response.data as { message?: string; error?: string }
        setError(data.message ?? data.error ?? 'Failed to set password. Please try again.')
      } else {
        setError(err instanceof Error ? err.message : 'Failed to set password. Please try again.')
      }
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
            Set Your Password
          </Typography>
          <Typography
            variant="body2"
            color="text.secondary"
            textAlign="center"
            sx={{ mb: 3 }}
          >
            Your account was created without a password. Please set one now.
          </Typography>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
              {error}
            </Alert>
          )}

          <Box component="form" onSubmit={handleSubmit} noValidate>
            <TextField
              label="New Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              fullWidth
              required
              autoComplete="new-password"
              autoFocus
              disabled={isLoading}
              sx={{ mb: 2 }}
              inputProps={{ 'aria-label': 'New password' }}
            />
            <TextField
              label="Confirm Password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              fullWidth
              required
              autoComplete="new-password"
              disabled={isLoading}
              sx={{ mb: 3 }}
              inputProps={{ 'aria-label': 'Confirm password' }}
            />
            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="large"
              disabled={isLoading || !password || !confirmPassword}
              startIcon={isLoading ? <CircularProgress size={18} color="inherit" /> : null}
              aria-label="Set password"
            >
              {isLoading ? 'Setting password…' : 'Set Password'}
            </Button>
          </Box>
        </Paper>
      </Box>
    </Container>
  )
}
