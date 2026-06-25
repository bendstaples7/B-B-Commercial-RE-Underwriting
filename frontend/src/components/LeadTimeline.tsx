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
  Collapse,
  Divider,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import HistoryIcon from '@mui/icons-material/History'
import type { LeadTimelineEntry } from '@/types'
import { formatPhoneNumber } from '@/utils/phone'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Number of characters before the summary is considered "long" and gets a
// collapse toggle.
const SUMMARY_COLLAPSE_THRESHOLD = 120

/**
 * Derive display text for a timeline entry, falling back to metadata when summary is empty.
 */
function getEntryDisplayText(entry: LeadTimelineEntry): string {
  if (entry.summary?.trim()) return entry.summary
  const metadata = entry.metadata
  if (!metadata) return ''
  const body = metadata.body
  if (typeof body === 'string' && body.trim()) return body
  const notes = metadata.notes
  if (typeof notes === 'string' && notes.trim()) return notes
  return ''
}

function getContactContextLine(entry: LeadTimelineEntry): string | null {
  const metadata = entry.metadata
  if (!metadata) return null

  const contactName = typeof metadata.contact_name === 'string' ? metadata.contact_name : null

  if (entry.event_type === 'call_logged') {
    const phone = typeof metadata.phone_number === 'string' ? metadata.phone_number : null
    const phoneLabel = typeof metadata.phone_label === 'string' ? metadata.phone_label : null
    if (!contactName && !phone) return null
    const parts: string[] = []
    if (contactName) parts.push(contactName)
    if (phone) {
      const formatted = formatPhoneNumber(phone)
      parts.push(phoneLabel ? `${formatted} (${phoneLabel})` : formatted)
    }
    return `With: ${parts.join(' · ')}`
  }

  if (isEmailEntry(entry)) {
    const email = typeof metadata.email_address === 'string' ? metadata.email_address : null
    const emailLabel = typeof metadata.email_label === 'string' ? metadata.email_label : null
    if (!contactName && !email) return null
    const parts: string[] = []
    if (contactName) parts.push(contactName)
    if (email) {
      parts.push(emailLabel ? `${email} (${emailLabel})` : email)
    }
    return `To: ${parts.join(' · ')}`
  }

  return null
}

/**
 * Human-readable label for a call outcome value.
 */
function humanizeOutcome(outcome: string): string {
  return outcome.replace(/_/g, ' ')
}

/**
 * Parse subject from a formatted email note body ([Email] Subject).
 */
function parseEmailSubjectFromBody(body: string): string | null {
  if (!body.startsWith('[Email]')) return null
  const firstLine = body.split('\n', 1)[0]
  const subject = firstLine.replace(/^\[Email\]\s*/, '').trim()
  return subject || null
}

/**
 * Extract the message body from a formatted email note string.
 */
function extractEmailMessageBody(body: string): string {
  if (!body.startsWith('[Email]')) return body
  const parts = body.split('\n')
  if (parts.length <= 1) return ''
  const afterHeader = parts.slice(1).join('\n').trim()
  // Drop leading blank line between subject header and message body
  return afterHeader.replace(/^\n+/, '').trim()
}

/**
 * Full note/email body from metadata when available.
 */
function getFullNoteBody(entry: LeadTimelineEntry): string {
  const body = entry.metadata?.body
  if (typeof body === 'string' && body.trim()) return body
  return entry.summary?.trim() ?? ''
}

function isEmailEntry(entry: LeadTimelineEntry): boolean {
  if (entry.event_type === 'email_logged') return true
  const metadata = entry.metadata
  if (!metadata) return false
  if (typeof metadata.email_address === 'string' && metadata.email_address.trim()) return true
  const body = metadata.body
  return typeof body === 'string' && body.startsWith('[Email]')
}

function buildEmailDetailRows(metadata: Record<string, unknown>): TimelineDetailRow[] {
  const rows: TimelineDetailRow[] = []
  if (metadata.contact_name) {
    rows.push({ label: 'Contact', value: String(metadata.contact_name) })
  }
  if (metadata.email_address) {
    const emailLabel = metadata.email_label ? ` (${metadata.email_label})` : ''
    rows.push({ label: 'Email', value: `${metadata.email_address}${emailLabel}` })
  }
  const body = typeof metadata.body === 'string' ? metadata.body : ''
  const subject =
    (typeof metadata.subject === 'string' && metadata.subject.trim())
      ? metadata.subject
      : (body ? parseEmailSubjectFromBody(body) : null)
  if (subject) {
    rows.push({ label: 'Subject', value: subject })
  }
  const message = body ? extractEmailMessageBody(body) : ''
  if (message) {
    rows.push({ label: 'Message', value: message })
  }
  return rows
}

export interface TimelineDetailRow {
  label: string
  value: string
}

/**
 * Build structured detail rows for the expanded timeline accordion.
 */
export function buildTimelineDetailRows(entry: LeadTimelineEntry): TimelineDetailRow[] {
  const metadata = entry.metadata ?? {}
  const rows: TimelineDetailRow[] = []

  if (entry.event_type === 'call_logged') {
    if (metadata.outcome) {
      rows.push({ label: 'Outcome', value: humanizeOutcome(String(metadata.outcome)) })
    }
    if (metadata.duration_minutes != null && metadata.duration_minutes !== '') {
      rows.push({ label: 'Duration', value: `${metadata.duration_minutes} minutes` })
    }
    if (metadata.contact_name) {
      rows.push({ label: 'Contact', value: String(metadata.contact_name) })
    }
    if (metadata.phone_number) {
      const phoneLabel = metadata.phone_label ? ` (${metadata.phone_label})` : ''
      rows.push({
        label: 'Phone',
        value: `${formatPhoneNumber(String(metadata.phone_number))}${phoneLabel}`,
      })
    }
    if (typeof metadata.notes === 'string' && metadata.notes.trim()) {
      rows.push({ label: 'Notes', value: metadata.notes })
    }
    if (rows.length === 0) {
      const displayText = getEntryDisplayText(entry)
      if (displayText) rows.push({ label: 'Details', value: displayText })
    }
    return rows
  }

  if (isEmailEntry(entry)) {
    return buildEmailDetailRows(metadata)
  }

  if (entry.event_type === 'note_added') {
    const body = getFullNoteBody(entry)
    if (body) {
      rows.push({ label: 'Note', value: body })
    }
    return rows
  }

  const displayText = getEntryDisplayText(entry)
  if (displayText) {
    rows.push({ label: 'Details', value: displayText })
  }

  return rows
}

export function entryHasExpandableDetails(entry: LeadTimelineEntry): boolean {
  if (buildTimelineDetailRows(entry).length > 0) return true
  return getEntryDisplayText(entry).length > SUMMARY_COLLAPSE_THRESHOLD
}

function getPreviewText(entry: LeadTimelineEntry): string {
  const fullText = getEntryDisplayText(entry)
  if (fullText.length <= SUMMARY_COLLAPSE_THRESHOLD) return fullText
  return fullText.slice(0, SUMMARY_COLLAPSE_THRESHOLD).trimEnd() + '…'
}

/**
 * Format an ISO timestamp in the browser's local timezone.
 * Returns "—" for empty or invalid timestamps.
 */
function formatLocalTimestamp(iso: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return '—'
  }
}

/**
 * Human-readable label for a timeline entry type.
 */
export function getTimelineEventLabel(entry: LeadTimelineEntry): string {
  if (entry.event_type === 'email_logged' || isEmailEntry(entry)) return 'Email Logged'
  if (entry.event_type === 'call_logged') return 'Call Logged'
  if (entry.event_type === 'note_added') return 'Note Added'
  return formatEventType(entry.event_type)
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
  highlighted?: boolean
}

function TimelineEntryRow({ entry, highlighted = false }: TimelineEntryRowProps) {
  const isHubSpot = entry.source === 'hubspot' || entry.source === 'hubspot_import'
  const summaryText = getEntryDisplayText(entry)
  const contactContextLine = getContactContextLine(entry)
  const hasExpandableDetails = entryHasExpandableDetails(entry)
  const detailRows = buildTimelineDetailRows(entry)
  const [detailsExpanded, setDetailsExpanded] = useState(false)

  const previewText = hasExpandableDetails ? getPreviewText(entry) : summaryText

  const handleToggleDetails = () => {
    if (hasExpandableDetails) {
      setDetailsExpanded((v) => !v)
    }
  }

  return (
    <ListItem
      alignItems="flex-start"
      data-testid={`timeline-entry-${entry.id}`}
      onClick={hasExpandableDetails ? handleToggleDetails : undefined}
      sx={{
        px: 0,
        borderRadius: 1,
        transition: 'background-color 0.3s ease',
        ...(hasExpandableDetails && {
          cursor: 'pointer',
          '&:hover': { bgcolor: 'action.hover' },
        }),
        ...(highlighted && {
          bgcolor: 'success.light',
          animation: 'timelineHighlightFade 2s ease-out forwards',
          '@keyframes timelineHighlightFade': {
            '0%': { bgcolor: 'success.light' },
            '100%': { bgcolor: 'transparent' },
          },
        }),
      }}
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
              {getTimelineEventLabel(entry)}
            </Typography>
            <Typography variant="caption" color="text.secondary" data-testid={`entry-timestamp-${entry.id}`}>
              {formatLocalTimestamp(entry.occurred_at)}
            </Typography>
            <Typography variant="caption" color="text.secondary" data-testid={`entry-actor-${entry.id}`}>
              — {entry.actor}
            </Typography>
            {isHubSpot && (
              <Chip
                label="Imported from HubSpot"
                size="small"
                variant="outlined"
                data-testid={`hubspot-badge-${entry.id}`}
                sx={{ fontSize: '0.65rem', height: 18, color: 'text.secondary', borderColor: 'divider', ml: 1 }}
              />
            )}
            {hasExpandableDetails && (
              <Box
                component="span"
                data-testid={`entry-details-toggle-${entry.id}`}
                sx={{ display: 'inline-flex', alignItems: 'center', color: 'text.secondary', ml: 'auto' }}
              >
                {detailsExpanded ? (
                  <ExpandLessIcon fontSize="small" aria-hidden />
                ) : (
                  <ExpandMoreIcon fontSize="small" aria-hidden />
                )}
              </Box>
            )}
          </Stack>
        }
        secondary={
          <Box component="span" display="block">
            {contactContextLine && !detailsExpanded && (
              <Typography
                variant="caption"
                color="text.secondary"
                display="block"
                sx={{ mt: 0.25 }}
                data-testid={`entry-contact-context-${entry.id}`}
              >
                {contactContextLine}
              </Typography>
            )}
            {hasExpandableDetails ? (
              <>
                {!detailsExpanded && previewText && (
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ mt: 0.25, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                    data-testid={`entry-summary-${entry.id}`}
                  >
                    {previewText}
                  </Typography>
                )}
                <Collapse in={detailsExpanded}>
                  <Box
                    sx={{ mt: 0.5, pl: 0.5, borderLeft: 2, borderColor: 'divider' }}
                    data-testid={`entry-details-${entry.id}`}
                  >
                    {detailRows.map((row) => (
                      <Box key={row.label} sx={{ mb: 1.25, '&:last-child': { mb: 0 } }}>
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          fontWeight="medium"
                          display="block"
                          data-testid={`entry-detail-label-${entry.id}-${row.label.toLowerCase().replace(/\s+/g, '-')}`}
                        >
                          {row.label}
                        </Typography>
                        <Typography
                          variant="body2"
                          color="text.secondary"
                          sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                          data-testid={`entry-detail-value-${entry.id}-${row.label.toLowerCase().replace(/\s+/g, '-')}`}
                        >
                          {row.value}
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                </Collapse>
              </>
            ) : (
              summaryText && (
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ mt: 0.25, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                  data-testid={`entry-summary-${entry.id}`}
                >
                  {summaryText}
                </Typography>
              )
            )}
          </Box>
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
  highlightEntryId?: number | null
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

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
  highlightEntryId = null,
}: LeadTimelineProps) {
  const [entries, setEntries] = useState<LeadTimelineEntry[]>(initialEntries)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setEntries(initialEntries)
    setTotal(initialTotal)
    setPage(1)
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
              <TimelineEntryRow
                entry={entry}
                highlighted={highlightEntryId != null && entry.id === highlightEntryId}
              />
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
