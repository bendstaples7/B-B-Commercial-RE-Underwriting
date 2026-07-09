/**
 * MissingPropertyMatchQueue — card-based property match review.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Box, Snackbar, Typography } from '@mui/material'
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
import { computeTotalPages, clampPage } from '@/utils/pagination'

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

  const { data } = useQuery({
    queryKey: ['queue-missing-property-match', page],
    queryFn: () => queueService.getMissingPropertyMatch(page, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)

  useEffect(() => {
    if (!focusLeadId || rows.length === 0) return
    const idx = rows.findIndex((r) => String(r.id) === focusLeadId)
    if (idx >= 0) setCardIndex(idx)
  }, [focusLeadId, rows])

  const currentRow = rows[cardIndex] ?? null
  const currentLeadId = currentRow?.id

  const { data: preview, isLoading: previewLoading, refetch: refetchPreview } = useQuery<PropertyMatchPreview>({
    queryKey: ['property-match-preview', currentLeadId],
    queryFn: () => propertyMatchService.preview(currentLeadId!),
    enabled: currentLeadId != null,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['queue-missing-property-match'] })
    queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
  }

  const advanceAfterAction = () => {
    if (cardIndex < rows.length - 1) {
      setCardIndex((i) => i + 1)
    } else if (page < totalPages) {
      setPage((p) => p + 1)
      setCardIndex(0)
    } else {
      setCardIndex(0)
      setPage(1)
    }
    invalidate()
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
    if (total === 0) return 'No leads waiting for property match review.'
    if (!currentRow) return 'Loading…'
    return null
  }, [total, currentRow])

  return (
    <Box data-testid="missing-property-match-queue">
      <Typography variant="h6" gutterBottom>
        Missing Property Match
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Review GIS-recommended addresses and approve or reject matches. Total: <strong>{total}</strong>
      </Typography>

      {emptyMessage ? (
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
