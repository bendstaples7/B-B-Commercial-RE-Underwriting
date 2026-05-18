/**
 * TimelinePanel — chronological list of Interactions and Tasks for a lead or organization.
 *
 * Displays a merged, date-descending timeline of all activity associated with
 * a given lead or organization. Supports filtering by entry type, subtype, and
 * date range.
 *
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Box,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  InputLabel,
  List,
  ListItem,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import NoteIcon from '@mui/icons-material/Note'
import PhoneIcon from '@mui/icons-material/Phone'
import EmailIcon from '@mui/icons-material/Email'
import TaskIcon from '@mui/icons-material/Task'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import { Fragment } from 'react'
import { timelineService } from '@/services/api'
import type { TimelineEntry } from '@/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TimelinePanelProps {
  targetType: 'lead' | 'organization'
  targetId: number
}

// ---------------------------------------------------------------------------
// Filter state
// ---------------------------------------------------------------------------

interface TimelineFilters {
  entry_type: string
  subtype: string
  date_from: string
  date_to: string
}

const EMPTY_FILTERS: TimelineFilters = {
  entry_type: '',
  subtype: '',
  date_from: '',
  date_to: '',
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format an ISO date string for display. Falls back to the raw value. */
function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Return the MUI icon component for a given subtype. */
function EntryIcon({ subtype }: { subtype: string }) {
  switch (subtype) {
    case 'note':
      return (
        <Tooltip title="Note">
          <NoteIcon fontSize="small" color="action" />
        </Tooltip>
      )
    case 'call':
      return (
        <Tooltip title="Call">
          <PhoneIcon fontSize="small" color="action" />
        </Tooltip>
      )
    case 'email':
      return (
        <Tooltip title="Email">
          <EmailIcon fontSize="small" color="action" />
        </Tooltip>
      )
    case 'task':
      return (
        <Tooltip title="Task">
          <TaskIcon fontSize="small" color="action" />
        </Tooltip>
      )
    default:
      return (
        <Tooltip title={subtype}>
          <HelpOutlineIcon fontSize="small" color="action" />
        </Tooltip>
      )
  }
}

/** Human-readable label for a subtype. */
function subtypeLabel(subtype: string): string {
  if (!subtype) return ''
  return subtype.charAt(0).toUpperCase() + subtype.slice(1)
}

/** Source badge colour: manual → blue, hubspot_import → orange. */
function sourceBadgeColor(
  source: string
): 'primary' | 'warning' | 'default' {
  if (source === 'manual') return 'primary'
  if (source === 'hubspot_import') return 'warning'
  return 'default'
}

/** Human-readable source label. */
function sourceLabel(source: string): string {
  if (source === 'manual') return 'Manual'
  if (source === 'hubspot_import') return 'HubSpot'
  return source
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

interface FilterBarProps {
  filters: TimelineFilters
  onChange: (filters: TimelineFilters) => void
}

function FilterBar({ filters, onChange }: FilterBarProps) {
  function set<K extends keyof TimelineFilters>(key: K, value: string) {
    onChange({ ...filters, [key]: value })
  }

  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={2}
      flexWrap="wrap"
      useFlexGap
      sx={{ mb: 2 }}
    >
      {/* Entry type filter */}
      <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel id="timeline-entry-type-label">Type</InputLabel>
        <Select
          labelId="timeline-entry-type-label"
          label="Type"
          value={filters.entry_type}
          onChange={(e) => set('entry_type', e.target.value)}
        >
          <MenuItem value="">All</MenuItem>
          <MenuItem value="interaction">Interaction</MenuItem>
          <MenuItem value="task">Task</MenuItem>
        </Select>
      </FormControl>

      {/* Subtype filter */}
      <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel id="timeline-subtype-label">Subtype</InputLabel>
        <Select
          labelId="timeline-subtype-label"
          label="Subtype"
          value={filters.subtype}
          onChange={(e) => set('subtype', e.target.value)}
        >
          <MenuItem value="">All</MenuItem>
          <MenuItem value="note">Note</MenuItem>
          <MenuItem value="call">Call</MenuItem>
          <MenuItem value="email">Email</MenuItem>
          <MenuItem value="task">Task</MenuItem>
        </Select>
      </FormControl>

      {/* Date from */}
      <TextField
        size="small"
        label="From"
        type="date"
        value={filters.date_from}
        onChange={(e) => set('date_from', e.target.value)}
        InputLabelProps={{ shrink: true }}
        sx={{ minWidth: 160 }}
      />

      {/* Date to */}
      <TextField
        size="small"
        label="To"
        type="date"
        value={filters.date_to}
        onChange={(e) => set('date_to', e.target.value)}
        InputLabelProps={{ shrink: true }}
        sx={{ minWidth: 160 }}
      />
    </Stack>
  )
}

// ---------------------------------------------------------------------------
// Timeline entry row
// ---------------------------------------------------------------------------

interface EntryRowProps {
  entry: TimelineEntry
}

function EntryRow({ entry }: EntryRowProps) {
  return (
    <ListItem
      disableGutters
      sx={{ display: 'block', py: 1.5 }}
      data-testid="timeline-entry"
    >
      <Stack direction="row" spacing={1.5} alignItems="flex-start">
        {/* Icon */}
        <Box sx={{ pt: 0.25, flexShrink: 0 }}>
          <EntryIcon subtype={entry.subtype} />
        </Box>

        {/* Content */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {/* Top row: subtype label + date */}
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            flexWrap="wrap"
            useFlexGap
            sx={{ mb: 0.5 }}
          >
            <Typography
              variant="subtitle2"
              component="span"
              data-testid="timeline-entry-subtype"
            >
              {subtypeLabel(entry.subtype)}
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              data-testid="timeline-entry-date"
            >
              {formatDate(entry.date)}
            </Typography>
          </Stack>

          {/* Body / title text */}
          <Typography
            variant="body2"
            sx={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              mb: 0.75,
            }}
            data-testid="timeline-entry-body"
          >
            {entry.body_or_title}
          </Typography>

          {/* Badges row */}
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {/* Source badge */}
            <Chip
              label={sourceLabel(entry.source)}
              color={sourceBadgeColor(entry.source)}
              size="small"
              variant="outlined"
              data-testid="timeline-entry-source"
            />

            {/* HubSpot engagement ID badge */}
            {entry.hubspot_engagement_id && (
              <Chip
                label={`HS: ${entry.hubspot_engagement_id}`}
                size="small"
                variant="outlined"
                color="default"
                data-testid="timeline-entry-hs-id"
              />
            )}
          </Stack>
        </Box>
      </Stack>
    </ListItem>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * TimelinePanel renders a filterable, date-descending list of Interactions
 * and Tasks for a lead or organization.
 *
 * Requirements: 4.1 (chronological list), 4.2 (filter bar), 4.3 (entry display),
 * 4.4 (empty state), 4.5 (React Query data fetching)
 */
export function TimelinePanel({ targetType, targetId }: TimelinePanelProps) {
  const [filters, setFilters] = useState<TimelineFilters>(EMPTY_FILTERS)

  // Build the query params — omit empty strings so the backend doesn't
  // receive blank filter values.
  const queryFilters = Object.fromEntries(
    Object.entries(filters).filter(([, v]) => v !== '')
  ) as Partial<TimelineFilters>

  // Req 4.5 — React Query with queryKey: ['timeline', targetType, targetId]
  const { data, isLoading, isError, error } = useQuery<TimelineEntry[], Error>({
    queryKey: ['timeline', targetType, targetId, queryFilters],
    queryFn: () =>
      targetType === 'lead'
        ? timelineService.getLeadTimeline(targetId, queryFilters)
        : timelineService.getOrganizationTimeline(targetId, queryFilters),
    enabled: targetId > 0,
  })

  return (
    <Box data-testid="timeline-panel">
      {/* Filter bar — Req 4.2 */}
      <FilterBar filters={filters} onChange={setFilters} />

      {/* Loading state */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={32} />
        </Box>
      )}

      {/* Error state */}
      {isError && (
        <Typography color="error" variant="body2" sx={{ py: 2 }}>
          Failed to load timeline: {error?.message ?? 'Unknown error'}
        </Typography>
      )}

      {/* Empty state — Req 4.4 */}
      {!isLoading && !isError && data?.length === 0 && (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ py: 4, textAlign: 'center' }}
          data-testid="timeline-empty"
        >
          No timeline entries yet
        </Typography>
      )}

      {/* Timeline list — Req 4.1, 4.3 */}
      {!isLoading && !isError && data && data.length > 0 && (
        <List dense disablePadding data-testid="timeline-list">
          {data.map((entry, idx) => (
            <Fragment key={`${entry.entry_type}-${entry.date}-${idx}`}>
              <EntryRow entry={entry} />
              {idx < data.length - 1 && <Divider component="li" />}
            </Fragment>
          ))}
        </List>
      )}
    </Box>
  )
}

export default TimelinePanel
