import React, { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Paper,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Button,
  IconButton,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Chip,
  CircularProgress,
  Alert,
  Pagination,
  Tooltip,
  Divider,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import GroupIcon from '@mui/icons-material/Group'
import FilterListIcon from '@mui/icons-material/FilterList'
import type {
  MarketingList,
  MarketingListMember,
  OutreachStatus,
} from '@/types'
import { leadService } from '@/services/leadApi'

const OUTREACH_STATUS_OPTIONS: { value: OutreachStatus; label: string }[] = [
  { value: 'not_contacted' as OutreachStatus, label: 'Not Contacted' },
  { value: 'contacted' as OutreachStatus, label: 'Contacted' },
  { value: 'responded' as OutreachStatus, label: 'Responded' },
  { value: 'converted' as OutreachStatus, label: 'Converted' },
  { value: 'opted_out' as OutreachStatus, label: 'Opted Out' },
]

const MEMBERS_PER_PAGE = 20

/** Color mapping for outreach status chips. */
const statusColor = (
  status: string,
): 'default' | 'info' | 'warning' | 'success' | 'error' => {
  switch (status) {
    case 'contacted':
      return 'info'
    case 'responded':
      return 'warning'
    case 'converted':
      return 'success'
    case 'opted_out':
      return 'error'
    default:
      return 'default'
  }
}

const formatDate = (dateStr: string | null): string => {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return '—'
  }
}

/**
 * Marketing list management component.
 *
 * Provides CRUD for marketing lists, member management with outreach status tracking,
 * and the ability to create lists from filter criteria.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
 */
export const MarketingListManager: React.FC = () => {
  // ---------------------------------------------------------------------------
  // List-level state
  // ---------------------------------------------------------------------------
  const [lists, setLists] = useState<MarketingList[]>([])
  const [listsLoading, setListsLoading] = useState(true)
  const [listsError, setListsError] = useState<string | null>(null)

  // Create / rename dialog
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogMode, setDialogMode] = useState<'create' | 'rename' | 'filter'>('create')
  const [dialogListId, setDialogListId] = useState<number | null>(null)
  const [dialogName, setDialogName] = useState('')
  const [dialogSaving, setDialogSaving] = useState(false)
  const [dialogError, setDialogError] = useState<string | null>(null)

  // Filter criteria for "create from filters"
  const [filterPropertyType, setFilterPropertyType] = useState('')
  const [filterCity, setFilterCity] = useState('')
  const [filterState, setFilterState] = useState('')
  const [filterZip, setFilterZip] = useState('')
  const [filterScoreMin, setFilterScoreMin] = useState('')
  const [filterScoreMax, setFilterScoreMax] = useState('')

  // Delete confirmation
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteListId, setDeleteListId] = useState<number | null>(null)
  const [deleteListName, setDeleteListName] = useState('')
  const [deleting, setDeleting] = useState(false)

  // ---------------------------------------------------------------------------
  // Member-level state (shown when a list is selected)
  // ---------------------------------------------------------------------------
  const [selectedList, setSelectedList] = useState<MarketingList | null>(null)
  const [members, setMembers] = useState<MarketingListMember[]>([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [membersError, setMembersError] = useState<string | null>(null)
  const [membersPage, setMembersPage] = useState(1)
  const [membersTotalPages, setMembersTotalPages] = useState(0)
  const [membersTotal, setMembersTotal] = useState(0)
  const [statusUpdating, setStatusUpdating] = useState<number | null>(null)

  // Success feedback
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchLists = useCallback(async () => {
    setListsLoading(true)
    setListsError(null)
    try {
      const response = await leadService.listMarketingLists({ per_page: 100 })
      setLists(response.lists)
    } catch (err: any) {
      setListsError(err.message || 'Failed to load marketing lists.')
    } finally {
      setListsLoading(false)
    }
  }, [])

  const fetchMembers = useCallback(
    async (listId: number, page: number) => {
      setMembersLoading(true)
      setMembersError(null)
      try {
        const response = await leadService.getListMembers(listId, {
          page,
          per_page: MEMBERS_PER_PAGE,
        })
        setMembers(response.members)
        setMembersTotalPages(response.pages)
        setMembersTotal(response.total ?? response.members.length)
      } catch (err: any) {
        setMembersError(err.message || 'Failed to load list members.')
      } finally {
        setMembersLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    fetchLists()
  }, [fetchLists])

  useEffect(() => {
    if (selectedList) {
      fetchMembers(selectedList.id, membersPage)
    }
  }, [selectedList, membersPage, fetchMembers])

  // ---------------------------------------------------------------------------
  // List CRUD handlers
  // ---------------------------------------------------------------------------

  const openCreateDialog = () => {
    setDialogMode('create')
    setDialogListId(null)
    setDialogName('')
    setDialogError(null)
    setDialogOpen(true)
  }

  const openFilterDialog = () => {
    setDialogMode('filter')
    setDialogListId(null)
    setDialogName('')
    setFilterPropertyType('')
    setFilterCity('')
    setFilterState('')
    setFilterZip('')
    setFilterScoreMin('')
    setFilterScoreMax('')
    setDialogError(null)
    setDialogOpen(true)
  }

  const openRenameDialog = (list: MarketingList) => {
    setDialogMode('rename')
    setDialogListId(list.id)
    setDialogName(list.name)
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleDialogClose = () => {
    setDialogOpen(false)
    setDialogError(null)
  }

  const handleDialogSave = async () => {
    const trimmedName = dialogName.trim()
    if (!trimmedName) {
      setDialogError('Name is required.')
      return
    }

    setDialogSaving(true)
    setDialogError(null)
    try {
      if (dialogMode === 'create') {
        await leadService.createMarketingList({ name: trimmedName })
        setSuccessMessage(`List "${trimmedName}" created.`)
      } else if (dialogMode === 'rename' && dialogListId !== null) {
        await leadService.renameMarketingList(dialogListId, trimmedName)
        setSuccessMessage(`List renamed to "${trimmedName}".`)
        // Update selected list name if it's the one being renamed
        if (selectedList?.id === dialogListId) {
          setSelectedList((prev) => (prev ? { ...prev, name: trimmedName } : prev))
        }
      } else if (dialogMode === 'filter') {
        const criteria: Record<string, any> = {}
        if (filterPropertyType) criteria.property_type = filterPropertyType
        if (filterCity.trim()) criteria.city = filterCity.trim()
        if (filterState.trim()) criteria.state = filterState.trim()
        if (filterZip.trim()) criteria.zip = filterZip.trim()
        if (filterScoreMin) criteria.score_min = Number(filterScoreMin)
        if (filterScoreMax) criteria.score_max = Number(filterScoreMax)
        await leadService.createMarketingList({
          name: trimmedName,
          filter_criteria: Object.keys(criteria).length > 0 ? criteria : undefined,
        })
        setSuccessMessage(`List "${trimmedName}" created from filters.`)
      }
      setDialogOpen(false)
      await fetchLists()
    } catch (err: any) {
      setDialogError(err.message || 'Operation failed.')
    } finally {
      setDialogSaving(false)
    }
  }

  const openDeleteDialog = (list: MarketingList) => {
    setDeleteListId(list.id)
    setDeleteListName(list.name)
    setDeleteDialogOpen(true)
  }

  const handleDelete = async () => {
    if (deleteListId === null) return
    setDeleting(true)
    try {
      await leadService.deleteMarketingList(deleteListId)
      setSuccessMessage(`List "${deleteListName}" deleted.`)
      if (selectedList?.id === deleteListId) {
        setSelectedList(null)
        setMembers([])
      }
      setDeleteDialogOpen(false)
      await fetchLists()
    } catch (err: any) {
      setListsError(err.message || 'Failed to delete list.')
    } finally {
      setDeleting(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Member status handler
  // ---------------------------------------------------------------------------

  const handleStatusChange = async (
    listId: number,
    leadId: number,
    newStatus: OutreachStatus,
  ) => {
    setStatusUpdating(leadId)
    try {
      await leadService.updateOutreachStatus(listId, leadId, newStatus)
      // Update local state
      setMembers((prev) =>
        prev.map((m) =>
          m.lead_id === leadId
            ? { ...m, outreach_status: newStatus, status_updated_at: new Date().toISOString() }
            : m,
        ),
      )
    } catch (err: any) {
      setMembersError(err.message || 'Failed to update outreach status.')
    } finally {
      setStatusUpdating(null)
    }
  }

  // ---------------------------------------------------------------------------
  // View: list selection
  // ---------------------------------------------------------------------------

  const handleSelectList = (list: MarketingList) => {
    setSelectedList(list)
    setMembersPage(1)
    setMembersError(null)
    setSuccessMessage(null)
  }

  const handleBackToLists = () => {
    setSelectedList(null)
    setMembers([])
    setMembersError(null)
    setSuccessMessage(null)
  }

  // ---------------------------------------------------------------------------
  // Render: member detail view
  // ---------------------------------------------------------------------------

  if (selectedList) {
    return (
      <Box component="section" aria-labelledby="member-list-heading" sx={{ px: { xs: 1, sm: 2 } }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
          <IconButton onClick={handleBackToLists} aria-label="Back to marketing lists" size="small">
            <ArrowBackIcon />
          </IconButton>
          <Box>
            <Typography variant="h5" id="member-list-heading" component="h2">
              {selectedList.name}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {membersTotal} member{membersTotal !== 1 ? 's' : ''}
            </Typography>
          </Box>
        </Box>

        {membersError && (
          <Alert severity="error" sx={{ mb: 2 }} role="alert" onClose={() => setMembersError(null)}>
            {membersError}
          </Alert>
        )}

        <TableContainer
          component={Paper}
          sx={{ overflowX: 'auto' }}
          role="region"
          aria-labelledby="member-list-heading"
        >
          <Table size="small" aria-label="Marketing list members table">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 200 }} scope="col">
                  Address
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 140 }} scope="col">
                  Owner
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 90 }} align="center" scope="col">
                  Score
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 160 }} scope="col">
                  Contact
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 180 }} scope="col">
                  Outreach Status
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} scope="col">
                  Added
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {membersLoading && members.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} align="center" sx={{ py: 6 }}>
                    <CircularProgress size={32} aria-label="Loading members" />
                  </TableCell>
                </TableRow>
              ) : members.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} align="center" sx={{ py: 6 }}>
                    <Typography variant="body2" color="text.secondary">
                      No members in this list yet.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                members.map((member) => {
                  const lead = member.lead
                  return (
                    <TableRow key={member.id} hover>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {lead?.property_street || `Lead #${member.lead_id}`}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {lead ? `${lead.owner_first_name} ${lead.owner_last_name}` : '—'}
                        </Typography>
                      </TableCell>
                      <TableCell align="center">
                        <Chip
                          label={lead?.lead_score?.toFixed(1) ?? '—'}
                          size="small"
                          color={
                            lead?.lead_score != null
                              ? lead.lead_score >= 70
                                ? 'success'
                                : lead.lead_score >= 40
                                  ? 'warning'
                                  : lead.lead_score > 0
                                    ? 'error'
                                    : 'default'
                              : 'default'
                          }
                          aria-label={`Score ${lead?.lead_score?.toFixed(1) ?? 'unknown'}`}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                          {[
                            lead?.mailing_city,
                            lead?.mailing_state,
                            lead?.mailing_zip,
                          ]
                            .filter(Boolean)
                            .join(', ') || '—'}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <FormControl size="small" sx={{ minWidth: 150 }}>
                          <Select
                            value={member.outreach_status}
                            onChange={(e) =>
                              handleStatusChange(
                                selectedList.id,
                                member.lead_id,
                                e.target.value as OutreachStatus,
                              )
                            }
                            disabled={statusUpdating === member.lead_id}
                            aria-label={`Outreach status for ${lead?.property_street || `Lead #${member.lead_id}`}`}
                            renderValue={(value) => (
                              <Chip
                                label={
                                  OUTREACH_STATUS_OPTIONS.find((o) => o.value === value)?.label ??
                                  value
                                }
                                size="small"
                                color={statusColor(value)}
                              />
                            )}
                          >
                            {OUTREACH_STATUS_OPTIONS.map((opt) => (
                              <MenuItem key={opt.value} value={opt.value}>
                                {opt.label}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">{formatDate(member.added_at)}</Typography>
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </TableContainer>

        {membersTotalPages > 1 && (
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
            <Pagination
              count={membersTotalPages}
              page={membersPage}
              onChange={(_e, value) => setMembersPage(value)}
              color="primary"
              showFirstButton
              showLastButton
              aria-label="Member list pagination"
            />
          </Box>
        )}
      </Box>
    )
  }

  // ---------------------------------------------------------------------------
  // Render: marketing lists overview
  // ---------------------------------------------------------------------------

  return (
    <Box component="section" aria-labelledby="marketing-lists-heading" sx={{ px: { xs: 1, sm: 2 } }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5" id="marketing-lists-heading" component="h2">
          Marketing Lists
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            startIcon={<FilterListIcon />}
            onClick={openFilterDialog}
            aria-label="Create list from filter criteria"
          >
            From Filters
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={openCreateDialog}
            aria-label="Create new marketing list"
          >
            New List
          </Button>
        </Box>
      </Box>

      {listsError && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert" onClose={() => setListsError(null)}>
          {listsError}
        </Alert>
      )}

      {successMessage && (
        <Alert severity="success" sx={{ mb: 2 }} role="status" onClose={() => setSuccessMessage(null)}>
          {successMessage}
        </Alert>
      )}

      {listsLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress aria-label="Loading marketing lists" />
        </Box>
      ) : lists.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <GroupIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
          <Typography variant="body1" color="text.secondary">
            No marketing lists yet. Create one to start organizing your leads.
          </Typography>
        </Paper>
      ) : (
        <TableContainer
          component={Paper}
          sx={{ overflowX: 'auto' }}
          role="region"
          aria-labelledby="marketing-lists-heading"
        >
          <Table size="small" aria-label="Marketing lists table">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 200 }} scope="col">
                  Name
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="center" scope="col">
                  Members
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }} scope="col">
                  Created
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }} scope="col">
                  Updated
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right" scope="col">
                  Actions
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {lists.map((list) => (
                <TableRow
                  key={list.id}
                  hover
                  sx={{ cursor: 'pointer' }}
                  onClick={() => handleSelectList(list)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      handleSelectList(list)
                    }
                  }}
                  aria-label={`Marketing list: ${list.name}, ${list.member_count} members`}
                >
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {list.name}
                      </Typography>
                      {list.filter_criteria && Object.keys(list.filter_criteria).length > 0 && (
                        <Tooltip title="Created from filter criteria" arrow>
                          <FilterListIcon fontSize="small" color="action" />
                        </Tooltip>
                      )}
                    </Box>
                  </TableCell>
                  <TableCell align="center">
                    <Chip label={list.member_count} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{formatDate(list.created_at)}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{formatDate(list.updated_at)}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Rename" arrow>
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation()
                          openRenameDialog(list)
                        }}
                        aria-label={`Rename list ${list.name}`}
                      >
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete" arrow>
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation()
                          openDeleteDialog(list)
                        }}
                        aria-label={`Delete list ${list.name}`}
                        color="error"
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Create / Rename / Filter Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={handleDialogClose}
        maxWidth="sm"
        fullWidth
        aria-labelledby="list-dialog-title"
      >
        <DialogTitle id="list-dialog-title">
          {dialogMode === 'create'
            ? 'Create Marketing List'
            : dialogMode === 'rename'
              ? 'Rename Marketing List'
              : 'Create List from Filters'}
        </DialogTitle>
        <DialogContent>
          {dialogError && (
            <Alert severity="error" sx={{ mb: 2 }} role="alert">
              {dialogError}
            </Alert>
          )}
          <TextField
            autoFocus
            label="List Name"
            value={dialogName}
            onChange={(e) => setDialogName(e.target.value)}
            fullWidth
            size="small"
            sx={{ mt: 1 }}
            required
            aria-required="true"
          />

          {dialogMode === 'filter' && (
            <>
              <Divider sx={{ my: 2 }} />
              <Typography variant="subtitle2" gutterBottom>
                Filter Criteria
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
                Leads matching these criteria will be added. Leads with "opted out" status are
                excluded automatically.
              </Typography>
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
                  gap: 2,
                }}
              >
                <FormControl size="small" fullWidth>
                  <InputLabel id="filter-dialog-property-type-label">Property Type</InputLabel>
                  <Select
                    labelId="filter-dialog-property-type-label"
                    value={filterPropertyType}
                    label="Property Type"
                    onChange={(e) => setFilterPropertyType(e.target.value)}
                  >
                    <MenuItem value="">Any</MenuItem>
                    <MenuItem value="Single Family">Single Family</MenuItem>
                    <MenuItem value="Multi Family">Multi Family</MenuItem>
                    <MenuItem value="Commercial">Commercial</MenuItem>
                    <MenuItem value="Condo">Condo</MenuItem>
                    <MenuItem value="Townhouse">Townhouse</MenuItem>
                    <MenuItem value="Land">Land</MenuItem>
                  </Select>
                </FormControl>
                <TextField
                  size="small"
                  label="City"
                  value={filterCity}
                  onChange={(e) => setFilterCity(e.target.value)}
                  fullWidth
                />
                <TextField
                  size="small"
                  label="State"
                  value={filterState}
                  onChange={(e) => setFilterState(e.target.value)}
                  fullWidth
                />
                <TextField
                  size="small"
                  label="Zip Code"
                  value={filterZip}
                  onChange={(e) => setFilterZip(e.target.value)}
                  fullWidth
                />
                <TextField
                  size="small"
                  label="Min Score"
                  type="number"
                  value={filterScoreMin}
                  onChange={(e) => setFilterScoreMin(e.target.value)}
                  inputProps={{ min: 0, max: 100 }}
                  fullWidth
                />
                <TextField
                  size="small"
                  label="Max Score"
                  type="number"
                  value={filterScoreMax}
                  onChange={(e) => setFilterScoreMax(e.target.value)}
                  inputProps={{ min: 0, max: 100 }}
                  fullWidth
                />
              </Box>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleDialogClose} disabled={dialogSaving}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleDialogSave}
            disabled={dialogSaving || !dialogName.trim()}
            startIcon={dialogSaving ? <CircularProgress size={18} color="inherit" /> : undefined}
          >
            {dialogSaving
              ? 'Saving…'
              : dialogMode === 'rename'
                ? 'Rename'
                : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        aria-labelledby="delete-dialog-title"
      >
        <DialogTitle id="delete-dialog-title">Delete Marketing List</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete <strong>{deleteListName}</strong>? This action cannot be
            undone and will remove all member associations.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)} disabled={deleting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleDelete}
            disabled={deleting}
            startIcon={deleting ? <CircularProgress size={18} color="inherit" /> : <DeleteIcon />}
          >
            {deleting ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
