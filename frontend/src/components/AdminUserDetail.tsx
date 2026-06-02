import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  Button,
  CircularProgress,
  Alert,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { adminService } from '@/services/api'

/** Format a date string safely. Returns '—' for null/undefined/invalid values. */
function safeFormatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString()
}

/** Extract a human-readable error message from an unknown error (e.g. Axios error). */
function extractErrorMessage(err: unknown): string {
  if (err && typeof err === 'object') {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    return (
      axiosErr.response?.data?.error ??
      axiosErr.response?.data?.message ??
      axiosErr.message ??
      'An unexpected error occurred.'
    )
  }
  return 'An unexpected error occurred.'
}

export default function AdminUserDetail() {
  const { userId } = useParams<{ userId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0) // MUI TablePagination is 0-indexed
  const PAGE_SIZE = 50

  // ── Reset Password dialog state ──────────────────────────────────────────
  const [resetPwdOpen, setResetPwdOpen] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [resetPwdSuccess, setResetPwdSuccess] = useState<string | null>(null)
  const [resetPwdError, setResetPwdError] = useState<string | null>(null)

  // ── Edit User dialog state ───────────────────────────────────────────────
  const [editOpen, setEditOpen] = useState(false)
  const [editDisplayName, setEditDisplayName] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [editError, setEditError] = useState<string | null>(null)

  // Fetch user summary
  const {
    data: summary,
    isLoading: summaryLoading,
    error: summaryError,
  } = useQuery({
    queryKey: ['adminUserSummary', userId],
    queryFn: () => adminService.getUserSummary(userId!),
    enabled: !!userId,
  })

  // Fetch paginated leads for this user
  const {
    data: leadsData,
    isLoading: leadsLoading,
    error: leadsError,
  } = useQuery({
    queryKey: ['adminUserLeads', userId, page],
    queryFn: () =>
      adminService.listLeads({
        owner_user_id: userId,
        page: page + 1, // backend is 1-indexed
        page_size: PAGE_SIZE,
      }),
    enabled: !!userId,
  })

  // ── Reset Password mutation ──────────────────────────────────────────────
  const resetPasswordMutation = useMutation({
    mutationFn: (password: string) => adminService.resetPassword(userId!, password),
    onSuccess: () => {
      setResetPwdSuccess('Password reset successfully.')
      setResetPwdOpen(false)
      setNewPassword('')
    },
    onError: (err: unknown) => {
      setResetPwdError(extractErrorMessage(err))
    },
  })

  // ── Update User mutation ─────────────────────────────────────────────────
  const updateUserMutation = useMutation({
    mutationFn: (data: { display_name?: string; email?: string }) =>
      adminService.updateUser(userId!, data),
    onSuccess: () => {
      setEditOpen(false)
      queryClient.invalidateQueries({ queryKey: ['adminUserSummary', userId] })
    },
    onError: (err: unknown) => {
      setEditError(extractErrorMessage(err))
    },
  })

  const isLoading = summaryLoading || leadsLoading
  const error = summaryError || leadsError

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="200px">
        <CircularProgress />
      </Box>
    )
  }

  if (error) {
    return (
      <Box p={3}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/admin')}
          sx={{ mb: 2 }}
        >
          Back to Admin
        </Button>
        <Alert severity="error">
          {error instanceof Error ? error.message : 'Failed to load user details.'}
        </Alert>
      </Box>
    )
  }

  const totalLeads = leadsData?.total_count ?? 0

  return (
    <Box p={3}>
      {/* Back button */}
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/admin')}
        sx={{ mb: 3 }}
      >
        Back to Admin
      </Button>

      {/* User profile */}
      {summary && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h5" gutterBottom>
            {summary.display_name}
          </Typography>
          <Box
            display="grid"
            gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' }}
            gap={2}
          >
            <Box>
              <Typography variant="caption" color="text.secondary">
                Email
              </Typography>
              <Typography variant="body1">{summary.email}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Status
              </Typography>
              <Box>
                <Chip
                  label={summary.is_active ? 'Active' : 'Inactive'}
                  color={summary.is_active ? 'success' : 'default'}
                  size="small"
                />
              </Box>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Admin
              </Typography>
              <Box>
                <Chip
                  label={summary.is_admin ? 'Yes' : 'No'}
                  color={summary.is_admin ? 'primary' : 'default'}
                  size="small"
                />
              </Box>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Member Since
              </Typography>
              <Typography variant="body1">
                {safeFormatDate(summary.created_at)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Lead Count
              </Typography>
              <Typography variant="body1">{summary.lead_count}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Marketing Lists
              </Typography>
              <Typography variant="body1">{summary.marketing_list_count}</Typography>
            </Box>
          </Box>

          {/* Action buttons */}
          <Box display="flex" gap={2} mt={3}>
            <Button
              variant="outlined"
              onClick={() => {
                setEditDisplayName(summary?.display_name ?? '')
                setEditEmail(summary?.email ?? '')
                setEditError(null)
                setEditOpen(true)
              }}
            >
              Edit
            </Button>
            <Button
              variant="outlined"
              color="warning"
              onClick={() => {
                setResetPwdOpen(true)
                setResetPwdError(null)
                setNewPassword('')
              }}
            >
              Reset Password
            </Button>
          </Box>
        </Paper>
      )}

      {/* Reset password success alert */}
      {resetPwdSuccess && (
        <Alert
          severity="success"
          onClose={() => setResetPwdSuccess(null)}
          sx={{ mb: 3 }}
        >
          {resetPwdSuccess}
        </Alert>
      )}

      {/* Leads table */}
      <Typography variant="h6" gutterBottom>
        Leads ({totalLeads})
      </Typography>
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Property Address</TableCell>
              <TableCell>City</TableCell>
              <TableCell>State</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Score</TableCell>
              <TableCell>Created At</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {leadsData?.leads.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center">
                  <Typography variant="body2" color="text.secondary" py={2}>
                    No leads found for this user.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              leadsData?.leads.map((lead) => (
                <TableRow key={lead.id} hover>
                  <TableCell>{lead.property_street ?? '—'}</TableCell>
                  <TableCell>{lead.property_city ?? '—'}</TableCell>
                  <TableCell>{lead.property_state ?? '—'}</TableCell>
                  <TableCell>{lead.lead_status}</TableCell>
                  <TableCell align="right">{lead.lead_score}</TableCell>
                  <TableCell>
                    {safeFormatDate(lead.created_at)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        <TablePagination
          component="div"
          count={totalLeads}
          page={page}
          onPageChange={(_event, newPage) => setPage(newPage)}
          rowsPerPage={PAGE_SIZE}
          rowsPerPageOptions={[PAGE_SIZE]}
        />
      </TableContainer>

      {/* ── Reset Password Dialog ── */}
      <Dialog open={resetPwdOpen} onClose={() => setResetPwdOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Reset Password</DialogTitle>
        <DialogContent>
          {resetPwdError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {resetPwdError}
            </Alert>
          )}
          <TextField
            label="New Password"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            fullWidth
            margin="dense"
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetPwdOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="warning"
            disabled={resetPasswordMutation.isPending || !newPassword}
            onClick={() => resetPasswordMutation.mutate(newPassword)}
          >
            Reset
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Edit User Dialog ── */}
      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Edit User</DialogTitle>
        <DialogContent>
          {editError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {editError}
            </Alert>
          )}
          <TextField
            label="Display Name"
            value={editDisplayName}
            onChange={(e) => setEditDisplayName(e.target.value)}
            fullWidth
            margin="dense"
            autoFocus
          />
          <TextField
            label="Email"
            value={editEmail}
            onChange={(e) => setEditEmail(e.target.value)}
            fullWidth
            margin="dense"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={updateUserMutation.isPending}
            onClick={() =>
              updateUserMutation.mutate({ display_name: editDisplayName, email: editEmail })
            }
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
