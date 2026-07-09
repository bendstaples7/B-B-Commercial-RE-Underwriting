/**
 * LeadStatusSelector — clickable status chip that opens a menu to change lead status.
 */
import { useState, useEffect } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Menu,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material'
import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown'
import type { LeadStatus } from '@/types'
import { LEAD_STATUS_LABELS, getLeadStatusColor } from '@/components/LeadStatusChip'
import { commandCenterService } from '@/services/api'

export interface LeadStatusSelectorProps {
  leadId: number
  status: LeadStatus
  allStatuses: LeadStatus[]
  onStatusChanged: () => void | Promise<void>
}

export function LeadStatusSelector({
  leadId,
  status,
  allStatuses,
  onStatusChanged,
}: LeadStatusSelectorProps) {
  const [displayStatus, setDisplayStatus] = useState(status)
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [pendingStatus, setPendingStatus] = useState<LeadStatus | null>(null)
  const [statusReason, setStatusReason] = useState('')
  const [statusChanging, setStatusChanging] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)

  useEffect(() => {
    setDisplayStatus(status)
  }, [status, leadId])

  const label = LEAD_STATUS_LABELS[displayStatus] ?? displayStatus
  const bgcolor = getLeadStatusColor(displayStatus)
  const otherStatuses = allStatuses.filter((s) => s !== displayStatus)

  const handleOpenMenu = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
    setStatusError(null)
  }

  const handleCloseMenu = () => {
    setAnchorEl(null)
  }

  const handlePickStatus = (newStatus: LeadStatus) => {
    handleCloseMenu()
    setPendingStatus(newStatus)
    setStatusReason('')
    setStatusError(null)
  }

  const handleCancelChange = () => {
    setPendingStatus(null)
    setStatusReason('')
    setStatusError(null)
  }

  const handleConfirmChange = async () => {
    if (!pendingStatus) return
    setStatusChanging(true)
    setStatusError(null)
    let saved = false
    try {
      const result = await commandCenterService.updateStatus(
        leadId,
        pendingStatus,
        statusReason || undefined,
      ) as { lead_status?: LeadStatus }
      const nextStatus = result.lead_status ?? pendingStatus
      setDisplayStatus(nextStatus)
      setPendingStatus(null)
      setStatusReason('')
      saved = true
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Failed to update status')
    } finally {
      setStatusChanging(false)
    }

    if (saved) {
      try {
        await onStatusChanged()
      } catch {
        // Status is saved; parent queue refresh failures are non-blocking here.
      }
    }
  }

  return (
    <>
      <Chip
        label={label}
        size="small"
        onClick={handleOpenMenu}
        deleteIcon={<ArrowDropDownIcon />}
        onDelete={handleOpenMenu}
        aria-label={`Lead status: ${label}. Click to change.`}
        data-testid="lead-status-selector"
        sx={{
          bgcolor,
          color: '#fff',
          fontWeight: 700,
          whiteSpace: 'nowrap',
          cursor: 'pointer',
          '& .MuiChip-deleteIcon': { color: '#fff', opacity: 0.85 },
        }}
      />

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleCloseMenu}
        data-testid="lead-status-menu"
      >
        {otherStatuses.map((s) => (
          <MenuItem
            key={s}
            onClick={() => handlePickStatus(s)}
            data-testid={`lead-status-option-${s}`}
          >
            {LEAD_STATUS_LABELS[s]}
          </MenuItem>
        ))}
      </Menu>

      {pendingStatus && (
        <Box
          sx={{
            position: 'fixed',
            inset: 0,
            bgcolor: 'rgba(0,0,0,0.4)',
            zIndex: 1300,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            p: 2,
          }}
          data-testid="lead-status-change-dialog"
          onClick={handleCancelChange}
        >
          <Box
            sx={{ bgcolor: 'background.paper', borderRadius: 1, p: 3, maxWidth: 420, width: '100%' }}
            onClick={(e) => e.stopPropagation()}
          >
            <Typography variant="subtitle1" gutterBottom>
              Change status to {LEAD_STATUS_LABELS[pendingStatus]}?
            </Typography>
            <TextField
              label="Reason (optional)"
              multiline
              rows={3}
              fullWidth
              inputProps={{ maxLength: 500 }}
              value={statusReason}
              onChange={(e) => setStatusReason(e.target.value)}
              sx={{ mb: 2, mt: 1 }}
            />
            {statusError && (
              <Alert severity="error" sx={{ mb: 2 }}>{statusError}</Alert>
            )}
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              <Button variant="outlined" onClick={handleCancelChange} disabled={statusChanging}>
                Cancel
              </Button>
              <Button
                variant="contained"
                onClick={handleConfirmChange}
                disabled={statusChanging}
                data-testid="status-submit-btn"
              >
                {statusChanging ? 'Saving…' : 'Confirm'}
              </Button>
            </Box>
          </Box>
        </Box>
      )}
    </>
  )
}
