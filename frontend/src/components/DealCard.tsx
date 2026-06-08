/**
 * DealCard — draggable card for the Kanban board.
 *
 * Updated to show lead-relevant fields:
 * - Property address
 * - Owner name
 * - Lead score
 * - Recommended action badge
 * - Contact completeness indicators (has_phone, has_email)
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
import PhoneIcon from '@mui/icons-material/Phone'
import EmailIcon from '@mui/icons-material/Email'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import type { LeadKanbanCard } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number | null | undefined): string {
  if (score == null) return '#bdbdbd'
  if (score >= 8) return '#2e7d32' // high
  if (score >= 5) return '#f57c00' // medium
  if (score >= 1) return '#d32f2f' // low
  return '#9e9e9e' // zero
}

function actionBadgeColor(action: string | null): string {
  switch (action) {
    case 'add_contact_info': return '#6366f1'
    case 'resolve_match': return '#8b5cf6'
    case 'enrich_data': return '#a855f7'
    case 'analyze_property': return '#06b6d4'
    case 'ready_for_outreach': return '#10b981'
    case 'follow_up_now': return '#f59e0b'
    case 'create_task': return '#f97316'
    case 'nurture': return '#6366f1'
    case 'suppress': return '#6b7280'
    default: return '#9e9e9e'
  }
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + '…' : str
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DealCardProps {
  deal: LeadKanbanCard
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

  const handleClick = (e: React.MouseEvent) => {
    if (!isDragging && onClick) {
      e.stopPropagation()
      onClick(deal.id)
    }
  }

  const score = deal.lead_score

  return (
    <Card
      ref={setNodeRef}
      style={style}
      variant="outlined"
      onClick={handleClick}
      sx={{
        '&:hover': { boxShadow: 2, borderColor: 'primary.light' },
        borderLeft: `4px solid ${scoreColor(score)}`,
      }}
      {...listeners}
      {...attributes}
    >
      <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
        {/* Property Address */}
        <Typography variant="body2" fontWeight={600} noWrap gutterBottom>
          {deal.property_address || 'No address'}
        </Typography>

        {/* Owner Name */}
        {deal.owner_name && (
          <Typography variant="caption" color="text.secondary" display="block" noWrap gutterBottom>
            {deal.owner_name}
          </Typography>
        )}

        {/* Contact Completeness & Analysis Icons */}
        <Box sx={{ display: 'flex', gap: 0.5, mb: 0.5 }}>
          {deal.has_phone ? (
            <Tooltip title="Has phone">
              <PhoneIcon sx={{ fontSize: 14, color: 'success.main' }} />
            </Tooltip>
          ) : (
            <Tooltip title="No phone">
              <PhoneIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
            </Tooltip>
          )}
          {deal.has_email ? (
            <Tooltip title="Has email">
              <EmailIcon sx={{ fontSize: 14, color: 'success.main' }} />
            </Tooltip>
          ) : (
            <Tooltip title="No email">
              <EmailIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
            </Tooltip>
          )}
          {deal.analysis_complete && (
            <Tooltip title="Analysis complete">
              <CheckCircleIcon sx={{ fontSize: 14, color: 'info.main' }} />
            </Tooltip>
          )}
        </Box>

        {/* Bottom row: score + action badge */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mt: 0.5 }}>
          <Tooltip title={`Lead score: ${score}`}>
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
          {deal.recommended_action && (
            <Chip
              label={truncate(deal.recommended_action.replace(/_/g, ' '), 14)}
              size="small"
              sx={{
                fontSize: '0.65rem',
                backgroundColor: actionBadgeColor(deal.recommended_action),
                color: '#fff',
                maxWidth: 100,
                height: 20,
                '& .MuiChip-label': { px: 0.75 },
              }}
            />
          )}
        </Box>
      </CardContent>
    </Card>
  )
}

export default DealCard