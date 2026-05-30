/**
 * KanbanColumn — renders a single pipeline stage column with deal count header.
 *
 * Acts as a drop target for dragged DealCards.
 */
import React from 'react'
import { useDroppable } from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { Box, Paper, Typography, Chip } from '@mui/material'
import { DealCard } from './DealCard'
import type { DealKanbanCard } from '@/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface KanbanColumnProps {
  stageName: string
  deals: DealKanbanCard[]
  onDealClick?: (dealId: number) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function KanbanColumn({ stageName, deals, onDealClick }: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${stageName}`,
    data: { stageName },
  })

  return (
    <Paper
      ref={setNodeRef}
      variant="outlined"
      sx={{
        minWidth: 280,
        maxWidth: 320,
        flex: '1 1 0',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: isOver ? 'action.hover' : 'background.paper',
        borderColor: isOver ? 'primary.main' : 'divider',
        borderStyle: isOver ? 'solid' : 'solid',
        borderWidth: isOver ? 2 : 1,
        transition: 'background-color 0.2s, border-color 0.2s',
        maxHeight: 'calc(100vh - 200px)',
      }}
    >
      {/* Column Header */}
      <Box
        sx={{
          px: 2,
          py: 1.5,
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          backgroundColor: 'grey.50',
        }}
      >
        <Typography variant="subtitle2" fontWeight={600}>
          {stageName}
        </Typography>
        <Chip
          label={deals.length}
          size="small"
          color={deals.length > 0 ? 'primary' : 'default'}
          variant="outlined"
          sx={{ fontWeight: 600, minWidth: 28 }}
        />
      </Box>

      {/* Deal Cards */}
      <Box
        sx={{
          p: 1,
          overflowY: 'auto',
          flex: 1,
          minHeight: 80,
        }}
      >
        <SortableContext
          items={deals.map((d) => `deal-${d.id}`)}
          strategy={verticalListSortingStrategy}
        >
          {deals.length === 0 ? (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: 80,
                color: 'text.disabled',
              }}
            >
              <Typography variant="caption">No deals</Typography>
            </Box>
          ) : (
            deals.map((deal) => (
              <DealCard key={deal.id} deal={deal} onClick={onDealClick} />
            ))
          )}
        </SortableContext>
      </Box>
    </Paper>
  )
}

export default KanbanColumn
