/**
 * KanbanColumn — renders a single kanban column with action label, icon, and count header.
 *
 * Acts as a drop target for dragged DealCards.
 * Supports pagination with a "Load all X more" button at the bottom.
 *
 * Header shows one count chip only: total when fully loaded, or "N of total" when
 * the column is still paginated (bottom button covers loading the rest).
 */
import { useDroppable } from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { Box, Paper, Typography, Chip, Button } from '@mui/material'
import type { LeadKanbanColumn } from '@/types'
import { DealCard } from './DealCard'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface KanbanColumnProps {
  column: LeadKanbanColumn
  onDealClick?: (dealId: number) => void
  onLoadMore?: (columnId: string) => void
  totalCount: number
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function KanbanColumn({ column, onDealClick, onLoadMore, totalCount }: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${column.id}`,
    data: { stageName: column.id },
  })

  const visibleCount = column.leads.length
  const remaining = totalCount - visibleCount
  const hasMore = remaining > 0
  const countLabel = hasMore
    ? `${visibleCount.toLocaleString()} of ${totalCount.toLocaleString()}`
    : totalCount.toLocaleString()

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
        borderStyle: 'solid',
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
          gap: 1,
          backgroundColor: 'grey.50',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <Typography variant="body1" sx={{ lineHeight: 1 }} aria-hidden>
            {column.icon}
          </Typography>
          <Typography variant="subtitle2" fontWeight={600} noWrap>
            {column.label}
          </Typography>
        </Box>
        <Chip
          label={countLabel}
          size="small"
          variant="outlined"
          aria-label={
            hasMore
              ? `${visibleCount} of ${totalCount} leads loaded in ${column.label}`
              : `${totalCount} leads in ${column.label}`
          }
          sx={{ fontWeight: 600, flexShrink: 0 }}
        />
      </Box>

      {/* Lead Cards */}
      <Box
        sx={{
          p: 1,
          overflowY: 'auto',
          flex: 1,
          minHeight: 80,
        }}
      >
        <SortableContext
          items={column.leads.map((d) => `deal-${d.id}`)}
          strategy={verticalListSortingStrategy}
        >
          {column.leads.length === 0 ? (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: 80,
                color: 'text.disabled',
              }}
            >
              <Typography variant="caption">No leads</Typography>
            </Box>
          ) : (
            column.leads.map((lead) => (
              <DealCard key={lead.id} deal={lead} onClick={onDealClick} />
            ))
          )}
        </SortableContext>
      </Box>

      {/* Load More Button — shown when there are more leads not displayed */}
      {hasMore && onLoadMore && (
        <Box sx={{ p: 1, borderTop: 1, borderColor: 'divider' }}>
          <Button
            fullWidth
            size="small"
            variant="text"
            onClick={() => onLoadMore(column.id)}
            sx={{ textTransform: 'none', fontWeight: 500 }}
          >
            Load all {remaining.toLocaleString()} more
          </Button>
        </Box>
      )}
    </Paper>
  )
}

export default KanbanColumn
