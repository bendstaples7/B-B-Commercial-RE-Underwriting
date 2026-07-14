/**
 * ReviewQueue — Manual review UI for uncertain/unmatched HubSpot records.
 *
 * Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7
 */
import React, { useState } from 'react'
import {
  Alert,
  Badge,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutline'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp'
import PendingActionsIcon from '@mui/icons-material/PendingActions'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { hubSpotService } from '@/services/api'
import type { HubSpotMatch } from '@/types'
import { MatchConfidence, MatchStatus } from '@/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ReviewQueueFilters {
  type?: string
  confidence?: string
  page: number
  per_page: number
}

interface RelinkDialogState {
  open: boolean
  matchId: number | null
  searchValue: string
  selectedRecordId: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getConfidenceSx(confidence: MatchConfidence): Record<string, string> {
  switch (confidence) {
    case MatchConfidence.HIGH:
      return { bgcolor: 'success.main', color: 'success.contrastText' }
    case MatchConfidence.MEDIUM:
      return { bgcolor: 'warning.main', color: 'warning.contrastText' }
    case MatchConfidence.LOW:
      return { bgcolor: 'orange', color: '#fff' }
    case MatchConfidence.UNMATCHED:
      return { bgcolor: 'error.main', color: 'error.contrastText' }
    default:
      return {}
  }
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return '—'
  }
}

// ---------------------------------------------------------------------------
// Expandable row — side-by-side comparison panel (Req 13.2)
// ---------------------------------------------------------------------------

interface ComparisonPanelProps {
  match: HubSpotMatch
}

const ComparisonPanel: React.FC<ComparisonPanelProps> = ({ match }) => {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 2,
        p: 2,
        bgcolor: 'grey.50',
        borderRadius: 1,
      }}
      aria-label="Side-by-side comparison"
    >
      {/* Incoming HubSpot record */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle2" color="primary" gutterBottom>
          HubSpot Record (Incoming)
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Typography variant="body2">
            <strong>Type:</strong> {match.hubspot_record_type}
          </Typography>
          {match.display_name && (
            <Typography variant="body2">
              <strong>Name:</strong> {match.display_name}
            </Typography>
          )}
          <Typography variant="body2">
            <strong>HubSpot ID:</strong> {match.hubspot_id}
          </Typography>
          <Typography variant="body2">
            <strong>Confidence:</strong>{' '}
            <Chip
              label={match.confidence}
              size="small"
              sx={getConfidenceSx(match.confidence)}
            />
          </Typography>
          <Typography variant="body2">
            <strong>Matching Criteria:</strong> {match.matching_criteria || '—'}
          </Typography>
          <Typography variant="body2">
            <strong>First Seen:</strong> {formatDate(match.created_at)}
          </Typography>
        </Box>
      </Paper>

      {/* Proposed internal match */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle2" color="secondary" gutterBottom>
          {match.internal_record_id ? 'Proposed Internal Match (Existing)' : 'No Match Found'}
        </Typography>
        {match.internal_record_id ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            <Typography variant="body2">
              <strong>Internal Type:</strong> {match.internal_record_type || '—'}
            </Typography>
            {match.internal_display_name && (
              <Typography variant="body2">
                <strong>Name:</strong> {match.internal_display_name}
              </Typography>
            )}
            <Typography variant="body2">
              <strong>Internal ID:</strong> {match.internal_record_id}
            </Typography>
            <Typography variant="body2">
              <strong>Status:</strong>{' '}
              <Chip
                label={match.status}
                size="small"
                color={match.status === MatchStatus.CONFIRMED ? 'success' : 'default'}
                variant="outlined"
              />
            </Typography>
            <Typography variant="body2">
              <strong>Last Updated:</strong> {formatDate(match.updated_at)}
            </Typography>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Typography variant="body2" color="error.main">
              This HubSpot record could not be matched to any existing property or contact in the database.
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Use <strong>Mark as New Record</strong> to accept it as a brand-new entry, or <strong>Reject + Re-link</strong> to manually assign it to an existing property ID.
            </Typography>
          </Box>
        )}
      </Paper>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Single expandable row
// ---------------------------------------------------------------------------

interface ReviewRowProps {
  match: HubSpotMatch
  onConfirm: (matchId: number) => void
  onRelink: (matchId: number) => void
  onMarkNew: (matchId: number) => void
  isConfirming: boolean
  isRejecting: boolean
  isMarkingNew: boolean
}

const ReviewRow: React.FC<ReviewRowProps> = ({
  match,
  onConfirm,
  onRelink,
  onMarkNew,
  isConfirming,
  isRejecting,
  isMarkingNew,
}) => {
  const [expanded, setExpanded] = useState(false)
  const isBusy = isConfirming || isRejecting || isMarkingNew

  return (
    <>
      <TableRow
        hover
        sx={{ '& > *': { borderBottom: 'unset' } }}
        aria-label={`Review queue row for HubSpot ${match.hubspot_record_type} ${match.hubspot_id}`}
      >
        {/* Expand toggle */}
        <TableCell sx={{ width: 48 }}>
          <IconButton
            size="small"
            onClick={() => setExpanded((prev) => !prev)}
            aria-label={expanded ? 'Collapse comparison' : 'Expand comparison'}
          >
            {expanded ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>

        {/* HubSpot record summary */}
        <TableCell>
          <Typography variant="body2" fontWeight="medium">
            {match.display_name || match.hubspot_record_type.toUpperCase()}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {match.hubspot_record_type.toUpperCase()} · ID: {match.hubspot_id}
          </Typography>
        </TableCell>

        {/* Proposed internal match */}
        <TableCell>
          {match.internal_record_id ? (
            <>
              <Typography variant="body2">{match.internal_display_name || match.internal_record_type}</Typography>
              <Typography variant="caption" color="text.secondary">
                {match.internal_record_type} · ID: {match.internal_record_id}
              </Typography>
            </>
          ) : (
            <Typography variant="body2" color="error.main" fontStyle="italic">
              No match found
            </Typography>
          )}
        </TableCell>

        {/* Confidence badge — color-coded (Req 13.2) */}
        <TableCell>
          <Chip
            label={match.confidence}
            size="small"
            sx={getConfidenceSx(match.confidence)}
            aria-label={`Confidence: ${match.confidence}`}
          />
        </TableCell>

        {/* Matching criteria */}
        <TableCell>
          <Typography variant="body2" color="text.secondary">
            {match.matching_criteria
              ? match.matching_criteria.replace(/_/g, ' ')
              : '—'}
          </Typography>
        </TableCell>

        {/* Action buttons (Req 13.3) */}
        <TableCell align="right">
          <Box
            sx={{
              display: 'flex',
              gap: 1,
              justifyContent: { xs: 'stretch', sm: 'flex-end' },
              flexWrap: 'wrap',
              flexDirection: { xs: 'column', sm: 'row' },
            }}
          >
            <Tooltip title="Confirm this match">
              <span style={{ width: '100%' }}>
                <Button
                  size="small"
                  variant="contained"
                  color="success"
                  startIcon={
                    isConfirming ? (
                      <CircularProgress size={14} color="inherit" />
                    ) : (
                      <CheckCircleIcon />
                    )
                  }
                  onClick={() => onConfirm(match.id)}
                  disabled={isBusy}
                  aria-label={`Confirm match for ${match.hubspot_id}`}
                  sx={{ width: { xs: '100%', sm: 'auto' } }}
                >
                  Confirm
                </Button>
              </span>
            </Tooltip>

            <Tooltip title="Reject and link to a different record">
              <span style={{ width: '100%' }}>
                <Button
                  size="small"
                  variant="outlined"
                  color="warning"
                  startIcon={
                    isRejecting ? (
                      <CircularProgress size={14} color="inherit" />
                    ) : (
                      <CancelIcon />
                    )
                  }
                  onClick={() => onRelink(match.id)}
                  disabled={isBusy}
                  aria-label={`Reject and re-link ${match.hubspot_id}`}
                  sx={{ width: { xs: '100%', sm: 'auto' } }}
                >
                  Reject + Re-link
                </Button>
              </span>
            </Tooltip>

            <Tooltip title="Mark as a brand-new record (no existing match)">
              <span style={{ width: '100%' }}>
                <Button
                  size="small"
                  variant="outlined"
                  color="info"
                  startIcon={
                    isMarkingNew ? (
                      <CircularProgress size={14} color="inherit" />
                    ) : (
                      <AddCircleOutlineIcon />
                    )
                  }
                  onClick={() => onMarkNew(match.id)}
                  disabled={isBusy}
                  aria-label={`Mark ${match.hubspot_id} as new record`}
                  sx={{ width: { xs: '100%', sm: 'auto' } }}
                >
                  Mark as New Record
                </Button>
              </span>
            </Tooltip>
          </Box>
        </TableCell>
      </TableRow>

      {/* Expandable comparison panel (Req 13.2) */}
      <TableRow>
        <TableCell colSpan={6} sx={{ py: 0 }}>
          <Collapse in={expanded} timeout="auto" unmountOnExit>
            <ComparisonPanel match={match} />
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  )
}

// ---------------------------------------------------------------------------
// Main ReviewQueue component
// ---------------------------------------------------------------------------

export interface ReviewQueueProps {
  /** When true, renders as a standalone page with its own heading */
  standalone?: boolean
}

export const ReviewQueue: React.FC<ReviewQueueProps> = ({ standalone = true }) => {
  const queryClient = useQueryClient()

  // Filter state (Req 13.7)
  const [filters, setFilters] = useState<ReviewQueueFilters>({
    page: 1,
    per_page: 20,
  })

  // Re-link dialog state (Req 13.3 — "Reject + Re-link" opens a dialog)
  const [relinkDialog, setRelinkDialog] = useState<RelinkDialogState>({
    open: false,
    matchId: null,
    searchValue: '',
    selectedRecordId: '',
  })

  // Track which row is currently being mutated
  const [activeMatchId, setActiveMatchId] = useState<number | null>(null)
  const [activeAction, setActiveAction] = useState<'confirm' | 'reject' | 'new' | null>(null)

  // ---------------------------------------------------------------------------
  // Data fetching (Req 13.1)
  // ---------------------------------------------------------------------------

  const { data, isLoading, error } = useQuery({
    queryKey: ['reviewQueue', filters],
    queryFn: () =>
      hubSpotService.getReviewQueue({
        type: filters.type,
        confidence: filters.confidence,
        page: filters.page,
        per_page: filters.per_page,
      }),
  })

  // Pending count badge — separate query with no filters to get total (Req 13.6)
  const { data: pendingData } = useQuery({
    queryKey: ['reviewQueuePendingCount'],
    queryFn: () => hubSpotService.getReviewQueue({ per_page: 1, page: 1 }),
    staleTime: 30_000,
  })

  const pendingCount = pendingData?.total ?? 0

  // ---------------------------------------------------------------------------
  // Mutations with optimistic UI (Req 13.4, 13.5)
  // ---------------------------------------------------------------------------

  const invalidateQueue = () => {
    queryClient.invalidateQueries({ queryKey: ['reviewQueue'] })
    queryClient.invalidateQueries({ queryKey: ['reviewQueuePendingCount'] })
  }

  const confirmMutation = useMutation({
    mutationFn: ({ matchId, internalRecordId }: { matchId: number; internalRecordId?: number }) =>
      hubSpotService.confirmMatch(matchId, internalRecordId),
    onSuccess: () => {
      invalidateQueue()
      setActiveMatchId(null)
      setActiveAction(null)
    },
    onError: () => {
      setActiveMatchId(null)
      setActiveAction(null)
    },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ matchId, internalRecordId }: { matchId: number; internalRecordId?: number }) =>
      hubSpotService.rejectMatch(matchId, internalRecordId),
    onSuccess: () => {
      invalidateQueue()
      setActiveMatchId(null)
      setActiveAction(null)
      setRelinkDialog({ open: false, matchId: null, searchValue: '', selectedRecordId: '' })
    },
    onError: () => {
      setActiveMatchId(null)
      setActiveAction(null)
    },
  })

  const markNewMutation = useMutation({
    mutationFn: (matchId: number) => hubSpotService.markMatchAsNewRecord(matchId),
    onSuccess: () => {
      invalidateQueue()
      setActiveMatchId(null)
      setActiveAction(null)
    },
    onError: () => {
      setActiveMatchId(null)
      setActiveAction(null)
    },
  })

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleConfirm = (matchId: number) => {
    setActiveMatchId(matchId)
    setActiveAction('confirm')
    confirmMutation.mutate({ matchId })
  }

  const handleOpenRelink = (matchId: number) => {
    setRelinkDialog({ open: true, matchId, searchValue: '', selectedRecordId: '' })
  }

  const handleRelinkSubmit = () => {
    if (relinkDialog.matchId === null) return
    const internalRecordId = relinkDialog.selectedRecordId
      ? parseInt(relinkDialog.selectedRecordId, 10)
      : undefined
    setActiveMatchId(relinkDialog.matchId)
    setActiveAction('reject')
    rejectMutation.mutate({ matchId: relinkDialog.matchId, internalRecordId })
  }

  const handleMarkNew = (matchId: number) => {
    setActiveMatchId(matchId)
    setActiveAction('new')
    markNewMutation.mutate(matchId)
  }

  const handlePageChange = (_event: unknown, newPage: number) => {
    setFilters((prev) => ({ ...prev, page: newPage + 1 }))
  }

  const handleRowsPerPageChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setFilters((prev) => ({
      ...prev,
      per_page: parseInt(event.target.value, 10),
      page: 1,
    }))
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const mutationError =
    confirmMutation.error || rejectMutation.error || markNewMutation.error

  return (
    <Box sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      {/* Header with pending count badge (Req 13.6) */}
      {standalone && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            mb: 3,
            flexWrap: 'wrap',
          }}
        >
          <Typography variant="h5" component="h1">
            Review Queue
          </Typography>
          <Badge
            badgeContent={pendingCount}
            color="warning"
            max={999}
            aria-label={`${pendingCount} pending review items`}
          >
            <PendingActionsIcon color="action" />
          </Badge>
          {pendingCount > 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
              {pendingCount} item{pendingCount !== 1 ? 's' : ''} pending review
            </Typography>
          )}
        </Box>
      )}

      {/* Filters (Req 13.7) */}
      <Paper sx={{ p: { xs: 1.5, sm: 2 }, mb: 2 }}>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
            gap: 2,
          }}
          role="search"
          aria-label="Review queue filters"
        >
          {/* Object type filter */}
          <FormControl size="small" fullWidth>
            <InputLabel id="rq-type-filter-label">Object Type</InputLabel>
            <Select
              labelId="rq-type-filter-label"
              value={filters.type || ''}
              label="Object Type"
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  type: e.target.value || undefined,
                  page: 1,
                }))
              }
            >
              <MenuItem value="">All Types</MenuItem>
              <MenuItem value="deal">Deal</MenuItem>
              <MenuItem value="contact">Contact</MenuItem>
              <MenuItem value="company">Company</MenuItem>
            </Select>
          </FormControl>

          {/* Confidence filter */}
          <FormControl size="small" fullWidth>
            <InputLabel id="rq-confidence-filter-label">Confidence</InputLabel>
            <Select
              labelId="rq-confidence-filter-label"
              value={filters.confidence || ''}
              label="Confidence"
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  confidence: e.target.value || undefined,
                  page: 1,
                }))
              }
            >
              <MenuItem value="">All Confidence Levels</MenuItem>
              <MenuItem value={MatchConfidence.MEDIUM}>Medium</MenuItem>
              <MenuItem value={MatchConfidence.LOW}>Low</MenuItem>
              <MenuItem value={MatchConfidence.UNMATCHED}>Unmatched</MenuItem>
            </Select>
          </FormControl>
        </Box>
      </Paper>

      {/* Mutation error banner */}
      {mutationError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => {}}>
          {mutationError instanceof Error
            ? mutationError.message
            : 'Action failed. The item remains in the queue.'}
        </Alert>
      )}

      {/* Fetch error */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error instanceof Error ? error.message : 'Failed to load review queue.'}
        </Alert>
      )}

      {/* Loading */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress aria-label="Loading review queue" />
        </Box>
      )}

      {/* Table */}
      {!isLoading && data && (
        <>
          <TableContainer component={Paper} sx={{ overflowX: 'auto', maxWidth: '100%' }}>
            <Table aria-label="HubSpot review queue" sx={{ minWidth: 800 }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: 48 }} />
                  <TableCell>HubSpot Record</TableCell>
                  <TableCell>Proposed Internal Match</TableCell>
                  <TableCell>Confidence</TableCell>
                  <TableCell>Matching Criteria</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.matches.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} align="center">
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ py: 4 }}
                      >
                        No items in the review queue matching the current filters.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  data.matches.map((match) => (
                    <ReviewRow
                      key={match.id}
                      match={match}
                      onConfirm={handleConfirm}
                      onRelink={handleOpenRelink}
                      onMarkNew={handleMarkNew}
                      isConfirming={
                        activeMatchId === match.id && activeAction === 'confirm'
                      }
                      isRejecting={
                        activeMatchId === match.id && activeAction === 'reject'
                      }
                      isMarkingNew={
                        activeMatchId === match.id && activeAction === 'new'
                      }
                    />
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>

          <TablePagination
            component="div"
            count={data.total}
            page={filters.page - 1}
            onPageChange={handlePageChange}
            rowsPerPage={filters.per_page}
            onRowsPerPageChange={handleRowsPerPageChange}
            rowsPerPageOptions={[10, 20, 50, 100]}
          />
        </>
      )}

      {/* Re-link dialog (Req 13.3 — "Reject + Re-link" opens a search dialog) */}
      <Dialog
        open={relinkDialog.open}
        onClose={() =>
          setRelinkDialog({ open: false, matchId: null, searchValue: '', selectedRecordId: '' })
        }
        maxWidth="sm"
        fullWidth
        aria-labelledby="relink-dialog-title"
      >
        <DialogTitle id="relink-dialog-title">Reject &amp; Re-link to Different Record</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Enter the internal record ID to link this HubSpot record to a different existing
            record, or leave blank to reject without re-linking.
          </Typography>
          <TextField
            label="Search / Internal Record ID"
            value={relinkDialog.searchValue}
            onChange={(e) =>
              setRelinkDialog((prev) => ({
                ...prev,
                searchValue: e.target.value,
                selectedRecordId: e.target.value,
              }))
            }
            fullWidth
            size="small"
            placeholder="e.g. 1042"
            inputProps={{ 'aria-label': 'Internal record ID for re-link' }}
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() =>
              setRelinkDialog({
                open: false,
                matchId: null,
                searchValue: '',
                selectedRecordId: '',
              })
            }
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            color="warning"
            onClick={handleRelinkSubmit}
            disabled={rejectMutation.isPending}
            startIcon={
              rejectMutation.isPending ? (
                <CircularProgress size={14} color="inherit" />
              ) : (
                <CancelIcon />
              )
            }
          >
            Reject &amp; Re-link
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default ReviewQueue
