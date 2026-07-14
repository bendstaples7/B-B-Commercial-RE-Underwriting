import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { adminService } from '@/services/api'
import type { AdminUserSummary } from '@/types'

/** Format an ISO date string as a locale date (no time). Returns '—' for null/undefined/invalid. */
function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString()
}

/**
 * AdminPanel — read-only cross-user visibility page at /admin.
 *
 * Fetches all users via GET /api/admin/users, then fetches each user's
 * activity summary via GET /api/admin/users/:id/summary in parallel.
 * Shows a loading spinner while any fetch is in-flight and an error alert
 * if any fetch fails (no partial data is rendered).
 *
 * Clicking a row navigates to /admin/users/:user_id.
 *
 * Requirements: 6.3, 6.4, 6.5, 6.6
 */
export const AdminPanel: React.FC = () => {
  const navigate = useNavigate()

  const {
    data: summaries,
    isLoading,
    isError,
    error,
  } = useQuery<AdminUserSummary[]>({
    queryKey: ['admin', 'users', 'summaries'],
    queryFn: async (): Promise<AdminUserSummary[]> => {
      // Step 1: fetch the user list
      const users = await adminService.listUsers()

      // Step 2: fetch each user's summary in parallel
      const summaryResults = await Promise.all(
        users.map((u) => adminService.getUserSummary(u.user_id))
      )

      return summaryResults
    },
  })

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <Box
        sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}
        aria-label="Loading admin panel"
      >
        <CircularProgress aria-label="Loading users" />
      </Box>
    )
  }

  // ── Error state — no partial data ─────────────────────────────────────────
  if (isError) {
    return (
      <Alert severity="error" role="alert" sx={{ m: 2 }}>
        {(error as Error)?.message ?? 'Failed to load user data. Please try again.'}
      </Alert>
    )
  }

  const rows: AdminUserSummary[] = summaries ?? []

  // ── Table ──────────────────────────────────────────────────────────────────
  return (
    <Box
      component="section"
      aria-labelledby="admin-panel-heading"
      sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
    >
      <Box sx={{ mb: 2 }}>
        <Typography variant="h5" component="h1" id="admin-panel-heading" fontWeight={600}>
          Admin Panel
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {rows.length} user{rows.length !== 1 ? 's' : ''}
        </Typography>
      </Box>

      <TableContainer component={Paper} sx={{ overflowX: 'auto', maxWidth: '100%' }}>
        <Table size="small" aria-label="Users table" sx={{ minWidth: 720 }}>
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Display Name
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Email
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Status
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Admin
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Member Since
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="right" scope="col">
                Lead Count
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="right" scope="col">
                Marketing Lists
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="right" scope="col">
                Import Jobs
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 6 }}>
                  <Typography variant="body2" color="text.secondary">
                    No users found.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((user) => (
                <TableRow
                  key={user.user_id}
                  hover
                  tabIndex={0}
                  role="button"
                  onClick={() => navigate(`/admin/users/${user.user_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      navigate(`/admin/users/${user.user_id}`)
                    }
                  }}
                  sx={{ cursor: 'pointer' }}
                  aria-label={`View details for ${user.display_name}`}
                >
                  <TableCell>
                    <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
                      {user.display_name}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                      {user.email}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {user.is_active ? 'Active' : 'Inactive'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {user.is_admin ? 'Yes' : 'No'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{formatDate(user.created_at)}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body2">{user.lead_count}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body2">{user.marketing_list_count}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body2">{user.import_job_count}</Typography>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}

export default AdminPanel
