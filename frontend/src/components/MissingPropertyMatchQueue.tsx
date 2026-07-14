/**
 * MissingPropertyMatchQueue — card-based property match review.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Box, Button, Snackbar, Typography } from '@mui/material'
import { useSearchParams } from 'react-router-dom'
import {
  queueService,
  commandCenterService,
  propertyMatchService,
} from '@/services/api'
import type { PropertyMatchPreview, QueueRow } from '@/types'
import { PropertyMatchReviewCard } from './PropertyMatchReviewCard'
import { PropertyMatchRejectDialog } from './PropertyMatchRejectDialog'
import { PropertyAddressEditDialog } from './PropertyAddressEditDialog'
import { SuppressLeadDialog } from './SuppressLeadDialog'
import { QueueLoadingState } from './QueueLoadingState'
import { computeTotalPages } from '@/utils/pagination'
import { queueListRefetchDefaults } from '@/utils/queueQueryDefaults'

export function MissingPropertyMatchQueue() {
  const [page, setPage] = useState(1)
  const [cardIndex, setCardIndex] = useState(0)
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const focusLeadId = searchParams.get('leadId')

  const [suppressTarget, setSuppressTarget] = useState<QueueRow | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [actionPending, setActionPending] = useState(false)
  const [snackbar, setSnackbar] = useState<string | null>(null)

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['queue-missing-property-match', page],
    queryFn: () => queueService.getMissingPropertyMatch(page, 20),
    // Card workflow mutates the current lead — do not keep previous page data
    // or an already-handled card can reappear as actionable during page advance.
    ...queueListRefetchDefaults,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const isInitialLoading = isLoading && !data
  const loadFailed = !isInitialLoading && (isError || data == null)

  const focusAppliedRef = useRef(false)

  useEffect(() => {
    focusAppliedRef.current = false
  }, [focusLeadId])

  useEffect(() => {
    if (!focusLeadId || rows.length === 0 || focusAppliedRef.current) return
    const idx = rows.findIndex((r) => String(r.id) === focusLeadId)
    if (idx >= 0) {
      setCardIndex(idx)
      focusAppliedRef.current = true
    }
  }, [focusLeadId, rows])

  const currentRow = rows[cardIndex] ?? null
  const currentLeadId = currentRow?.id

  const { data: preview, isLoading: previewLoading, refetch: refetchPreview } = useQuery<PropertyMatchPreview>({
    queryKey: ['property-match-preview', currentLeadId],
    queryFn: () => propertyMatchService.preview(currentLeadId!),
    enabled: currentLeadId != null,
  })

  useEffect(() => {
    if (rows.length === 0) return
    if (cardIndex >= rows.length) {
      setCardIndex(Math.max(0, rows.length - 1))
    }
  }, [rows.length, cardIndex])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['queue-missing-property-match'] })
    queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
  }

  const advanceAfterAction = () => {
    const wasLastOnPage = cardIndex >= rows.length - 1
    invalidate()
    if (wasLastOnPage) {
      if (page < totalPages) {
        setPage((p) => p + 1)
        setCardIndex(0)
      } else if (cardIndex > 0) {
        setCardIndex((i) => i - 1)
      }
    }
  }

  const handleApprove = async () => {
    if (!currentRow) return
    setActionPending(true)
    try {
      const result = await propertyMatchService.approve(currentRow.id)
      setSnackbar(
        result.recommended_action
          ? `Match confirmed — next action updated`
          : 'Match confirmed',
      )
      advanceAfterAction()
    } catch (err) {
      console.error('[MissingPropertyMatchQueue] Approve failed:', err)
      setSnackbar(err instanceof Error ? err.message : 'Approve failed. Please try again.')
    } finally {
      setActionPending(false)
    }
  }

  const handleRejectAction = async (action: string) => {
    if (!currentRow) return
    setRejectOpen(false)
    setActionPending(true)
    try {
      await propertyMatchService.reject(currentRow.id, action)
      setSnackbar('Match rejected')
      advanceAfterAction()
    } catch (err) {
      console.error('[MissingPropertyMatchQueue] Reject failed:', err)
      setSnackbar(err instanceof Error ? err.message : 'Reject failed. Please try again.')
    } finally {
      setActionPending(false)
    }
  }

  const handleSaveAddress = async (address: {
    property_street: string
    property_city: string
    property_state: string
    property_zip: string
  }) => {
    if (!currentRow) return
    await propertyMatchService.updateAddress(currentRow.id, address)
    await refetchPreview()
    setSnackbar('Address updated — review the new match')
  }

  const handleSuppressConfirm = async () => {
    if (!suppressTarget) return
    await commandCenterService.suppress(suppressTarget.id)
    setSuppressTarget(null)
    advanceAfterAction()
  }

  const emptyMessage = useMemo(() => {
    if (isInitialLoading || loadFailed) return null
    if (total === 0) return 'No leads waiting for property match review.'
    if (!currentRow) return 'Loading…'
    return null
  }, [isInitialLoading, loadFailed, total, currentRow])

  return (
    <Box
      data-testid="missing-property-match-queue"
      sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
    >
      <Typography variant="h6" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        Missing Property Match
      </Typography>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ mb: 2, overflowWrap: 'anywhere', wordBreak: 'break-word' }}
      >
        Review GIS-recommended addresses and approve or reject matches. Total:{' '}
        <strong>{data != null ? total : '—'}</strong>
      </Typography>

      {isInitialLoading ? (
        <QueueLoadingState />
      ) : loadFailed ? (
        <Alert
          severity="error"
          data-testid="missing-property-match-error"
          action={
            <Button color="inherit" size="small" onClick={() => refetch()}>
              Retry
            </Button>
          }
        >
          {error instanceof Error
            ? error.message
            : 'Unable to load leads waiting for property match review. Please try again.'}
        </Alert>
      ) : emptyMessage ? (
        <Alert severity="info">{emptyMessage}</Alert>
      ) : currentRow ? (
        <PropertyMatchReviewCard
          row={currentRow}
          preview={preview ?? null}
          previewLoading={previewLoading}
          index={cardIndex}
          total={rows.length}
          onApprove={handleApprove}
          onReject={() => setRejectOpen(true)}
          onSuppress={() => setSuppressTarget(currentRow)}
          onPrev={() => setCardIndex((i) => Math.max(0, i - 1))}
          onNext={() => setCardIndex((i) => Math.min(rows.length - 1, i + 1))}
          actionPending={actionPending}
        />
      ) : null}

      <PropertyMatchRejectDialog
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        onSkipTrace={() => handleRejectAction('skip_trace')}
        onEditAddress={() => {
          setRejectOpen(false)
          setEditOpen(true)
        }}
        onResearchPin={() => handleRejectAction('research_pin')}
      />

      <PropertyAddressEditDialog
        open={editOpen}
        row={currentRow}
        onClose={() => setEditOpen(false)}
        onSave={handleSaveAddress}
      />

      <SuppressLeadDialog
        open={suppressTarget !== null}
        onClose={() => setSuppressTarget(null)}
        onConfirm={handleSuppressConfirm}
      />

      <Snackbar
        open={snackbar !== null}
        autoHideDuration={4000}
        onClose={() => setSnackbar(null)}
        message={snackbar}
      />
    </Box>
  )
}

export default MissingPropertyMatchQueue
