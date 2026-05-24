import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
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
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { adminService } from '@/services/api'

export default function AdminUserDetail() {
  const { userId } = useParams<{ userId: string }>()
  const navigate = useNavigate()
  const [page, setPage] = useState(0) // MUI TablePagination is 0-indexed
  const PAGE_SIZE = 50

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
                {new Date(summary.created_at).toLocaleDateString()}
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
        </Paper>
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
                    {new Date(lead.created_at).toLocaleDateString()}
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
    </Box>
  )
}
