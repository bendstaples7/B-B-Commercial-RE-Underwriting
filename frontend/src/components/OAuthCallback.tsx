import React, { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, Typography, CircularProgress, Alert } from '@mui/material'
import { leadService } from '@/services/leadApi'

/**
 * OAuth2 callback page. Google redirects here with ?code=... after the user
 * authorizes. This component automatically exchanges the code for tokens
 * and redirects back to the import wizard.
 */
export const OAuthCallback: React.FC = () => {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const code = searchParams.get('code')
    const errorParam = searchParams.get('error')

    if (errorParam) {
      setError(`Google authorization failed: ${errorParam}`)
      return
    }

    if (!code) {
      setError('No authorization code received from Google.')
      return
    }

    // Exchange the code for tokens via the backend
    const exchangeCode = async () => {
      try {
        const result = await leadService.authenticateGoogleSheets({
          auth_code: code,
          redirect_uri: `${window.location.origin}/import/callback`,
        })
        // Store the user_id and auth status
        localStorage.setItem('user_id', result.user_id)
        localStorage.setItem('google_authenticated', 'true')
        // Redirect back to import page
        navigate('/import', { replace: true })
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : 'Failed to complete authentication.'
        setError(message)
      }
    }

    exchangeCode()
  }, [searchParams, navigate])

  if (error) {
    return (
      <Box sx={{ p: 4, maxWidth: 600, mx: 'auto' }}>
        <Alert severity="error">{error}</Alert>
        <Typography
          variant="body2"
          sx={{ mt: 2, cursor: 'pointer', color: 'primary.main' }}
          onClick={() => navigate('/import')}
        >
          Back to Import
        </Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ p: 4, textAlign: 'center' }}>
      <CircularProgress sx={{ mb: 2 }} />
      <Typography>Completing Google authentication...</Typography>
    </Box>
  )
}
