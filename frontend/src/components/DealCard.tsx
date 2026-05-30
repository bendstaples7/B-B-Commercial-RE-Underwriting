/**
 * DealCard — draggable card for the Kanban board.
 *
 * Displays deal name, value, city/state, and priority score.
 */
import React from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import {
  Card,
  CardContent,
  Typography,
  Chip,
  Box,
  Tooltip,
} from '@mui/material'
import type { DealKanbanCard } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCurrency(value: string | number | null | undefined): string {
  if (value == null) return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

function formatCityState(
  city: string | null | undefined,
  state: string | null | undefined
): string {
  const parts = [city, state].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : ''
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return '#bdbdbd'
  if (score >= 8) return '#2e7d32' // high
  if (score >= 5) return '#f57c00' // medium
  if (score >= 1) return '#d32f2f' // low
  return '#9e9e9e' // zero
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DealCardProps {
  deal: DealKanbanCard
  onClick?: (dealId: number) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DealCard({ deal, onClick }: DealCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({
      id: `deal-${deal.id}`,
      data: { deal },
    })

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : 1,
    cursor: 'grab',
    marginBottom: 8,
    userSelect: 'none',
  }

  const score = deal.priority_score ? parseFloat(deal.priority_score) : null
  const location = formatCityState(deal.property_city, deal.property_state)

  const handleClick = (e: React.MouseEvent) => {
    if (!isDragging && onClick) {
      e.stopPropagation()
      onClick(deal.id)
    }
  }

  return (
    <Card
      ref={setNodeRef}
      style={style}
      variant="outlined"
      onClick={handleClick}
      sx={{
        '&:hover': { boxShadow: 2, borderColor: 'primary.light' },
        borderLeft: score != null ? `4px solid ${scoreColor(score)}` : undefined,
      }}
      {...listeners}
      {...attributes}
    >
      <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Typography variant="body2" fontWeight={600} noWrap gutterBottom>
          {deal.property_address}
        </Typography>

        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            mb: 0.5,
          }}
        >
          <Typography variant="body2" color="text.secondary">
            {formatCurrency(deal.purchase_price)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {deal.unit_count} unit{deal.unit_count !== 1 ? 's' : ''}
          </Typography>
        </Box>

        {location && (
          <Typography variant="caption" color="text.secondary" display="block" gutterBottom>
            {location}
          </Typography>
        )}

        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mt: 0.5 }}>
          <Tooltip title={`Priority score: ${score ?? 0}`}>
            <Chip
              label={score != null ? score.toFixed(1) : '—'}
              size="small"
              sx={{
                fontWeight: 600,
                fontSize: '0.7rem',
                backgroundColor: scoreColor(score),
                color: '#fff',
                minWidth: 36,
              }}
            />
          </Tooltip>
          <Typography variant="caption" color="text.secondary">
            {deal.created_by_user_id.slice(0, 8)}
          </Typography>
        </Box>
      </CardContent>
    </Card>
  )
}

export default DealCard
