/**
 * LeadTimeline — paginated, reverse-chronological activity timeline for a lead.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
 */
import { useState, useEffect } from 'react'
import {
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'
import HistoryIcon from '@mui/icons-material/History'
import type { LeadTimelineEntry } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format a UTC ISO timestamp for display.
 * Shows date + time in UTC so the value is unambiguous.
 */
function formatUtcTimestamp(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toUTCString().replace(' GMT', ' UTC')
  } catch {
    return iso
  }
}

/**
 * Convert a snake_case event_type to a human-readable label.
 */
function formatEventType(eventType: string): string {
  return eventType
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// ---------------------------------------------------------------------------
// HubSpot "H" chip icon
// ---------------------------------------------------------------------------

function HubSpotChip() {
  return (
    <Chip
      label="H"
      size="small"
      data-testid="hubspot-icon"
      sx={{
        bgcolor: '#ff7a59',
        color: '#fff',
        fontWeight: 'bold',
        fontSize: '0.65rem',
        height: 20,
        width: 20,
        borderRadius: '50%',
        '& .MuiChip-label': { px: 0 },
      }}
    />
  )
}

// ---------------------------------------------------------------------------
// Single timeline entry row
// ---------------------------------------------------------------------------

interface TimelineEntryRowProps {
  entry: LeadTimelineEntry
}

function TimelineEntryRow({ entry }: TimelineEntryRowProps) {
  const isHubSpot = entry.source === 'hubspot' || entry.source === 'hubspot_import'

  return (
    <ListItem
      alignItems="flex-start"
      data-testid={`timeline-entry-${entry.id}`}
      sx={{ px: 0 }}
    >
      <ListItemAvatar sx={{ minWidth: 40 }}>
        {isHubSpot ? (
          <Box
            sx={{ mt: 0.5 }}
            data-testid={`hubspot-avatar-${entry.id}`}
          >
            <HubSpotChip />
          </Box>
        ) : (
          <Avatar sx={{ width: 28, height: 28, bgcolor: 'primary.light', mt: 0.5 }}>
            <HistoryIcon sx={{ fontSize: 16 }} />
          </Avatar>
        )}
      </ListItemAvatar>

      <ListItemText
        primary={
          <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
            <Typography variant="body2" fontWeight="medium" data-testid={`entry-event-type-${entry.id}`}>
              {formatEventType(entry.event_type)}
            </Typography>
            <Typography variant="caption" color="text.secondary" data-testid={`entry-timestamp-${entry.id}`}>
              {formatUtcTimestamp(entry.occurred_at)}
            </Typography>
            <Typography variant="caption" color="text.secondary" data-testid={`entry-actor-${entry.id}`}>
              — {entry.actor}
            </Typography>
          </Stack>
        }
        secondary={
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ mt: 0.25 }}
            data-testid={`entry-summary-${entry.id}`}
          >
            {entry.summary}
          </Typography>
        }
      />
    </ListItem>
  )
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface LeadTimelineProps {
  leadId: number
  initialEntries: LeadTimelineEntry[]
  initialTotal: number
  onLoadMore?: (page: number) => Promise<{ entries: LeadTimelineEntry[]; total: number }>
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25

/**
 * LeadTimeline renders a paginated, reverse-chronological activity timeline.
 * - Entries are displayed newest-first (the backend returns them in that order).
 * - "Load more" appends the next page without replacing existing entries.
 * - HubSpot-sourced entries show an orange "H" chip and have no edit/delete controls.
 */
export function LeadTimeline({
  initialEntries,
  initialTotal,
  onLoadMore,
}: LeadTimelineProps) {
  const [entries, setEntries] = useState<LeadTimelineEntry[]>(initialEntries)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setEntries(initialEntries)
    setTotal(initialTotal)
  }, [initialEntries, initialTotal])

  const hasMore = entries.length < total

  const handleLoadMore = async () => {
    if (!onLoadMore || loading) return
    setLoading(true)
    setError(null)
    try {
      const nextPage = page + 1
      const result = await onLoadMore(nextPage)
      // Append new entries (do NOT replace existing ones)
      setEntries((prev) => [...prev, ...result.entries])
      setTotal(result.total)
      setPage(nextPage)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load more entries.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box data-testid="lead-timeline">
      {/* Section header */}
      <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 1 }}>
        Timeline
        {total > 0 && (
          <Chip
            label={total}
            size="small"
            sx={{ ml: 1 }}
            data-testid="timeline-total-badge"
          />
        )}
      </Typography>

      {/* Empty state */}
      {entries.length === 0 && (
        <Typography
          variant="body2"
          color="text.secondary"
          data-testid="timeline-empty"
        >
          No timeline entries yet.
        </Typography>
      )}

      {/* Entry list */}
      {entries.length > 0 && (
        <List dense disablePadding data-testid="timeline-list">
          {entries.map((entry, index) => (
            <Box key={entry.id}>
              {index > 0 && <Divider component="li" />}
              <TimelineEntryRow entry={entry} />
            </Box>
          ))}
        </List>
      )}

      {/* Load more */}
      {hasMore && onLoadMore && (
        <Box sx={{ mt: 1, textAlign: 'center' }} data-testid="load-more-container">
          <Button
            size="small"
            variant="outlined"
            onClick={handleLoadMore}
            disabled={loading}
            startIcon={loading ? <CircularProgress size={14} color="inherit" /> : undefined}
            data-testid="load-more-btn"
          >
            {loading ? 'Loading…' : `Load more (${total - entries.length} remaining)`}
          </Button>
        </Box>
      )}

      {/* Pagination info */}
      {entries.length > 0 && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ mt: 1, display: 'block' }}
          data-testid="timeline-showing"
        >
          Showing {entries.length} of {total}
        </Typography>
      )}

      {/* Load more error */}
      {error && (
        <Typography
          variant="caption"
          color="error"
          sx={{ mt: 1, display: 'block' }}
          data-testid="load-more-error"
        >
          {error}
        </Typography>
      )}
    </Box>
  )
}

export default LeadTimeline
