/**
 * LeadTimeline — paginated, reverse-chronological activity timeline for a lead.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
 */
import { useState, useEffect, useRef, type KeyboardEvent, type MouseEvent } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  IconButton,
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
import { scopeRowsToLead, scopeRowsToLeadWithTotal } from '@/utils/leadScopedRows'
import { stripHtmlTags } from '@/utils/helpers'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Number of characters before the summary is considered "long" and gets a
// collapse toggle.
const SUMMARY_COLLAPSE_THRESHOLD = 120

/** Entries shown before "Show older activity" inside the accordion. */
export const TIMELINE_PREVIEW_COUNT = 5

/**
 * Derive display text for a timeline entry, falling back to metadata when summary is empty.
 * HubSpot bodies often include HTML wrappers — always show plain text.
 * Plain-text notes keep their original newlines; HTML is stripped with newlines preserved from <br>.
 */
function getEntryDisplayText(entry: LeadTimelineEntry): string {
  const candidates = [
    entry.summary,
    entry.metadata?.body,
    entry.metadata?.notes,
  ]
  for (const raw of candidates) {
    if (typeof raw !== 'string' || !raw.trim()) continue
    // Plain text (no tags / entities): preserve multi-line notes as authored
    if (!/<[^>]*>|&[a-zA-Z#]+;/i.test(raw)) {
      return raw.trim()
    }
    return stripHtmlTags(raw, { preserveNewlines: true })
  }
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
  if (typeof body === 'string' && body.trim()) {
    return stripHtmlTags(body, { preserveNewlines: true })
  }
  return stripHtmlTags(entry.summary?.trim() ?? '', { preserveNewlines: true })
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
    rows.push({ label: 'Subject', value: stripHtmlTags(subject) })
  }
  const message = body ? extractEmailMessageBody(body) : ''
  if (message) {
    rows.push({ label: 'Message', value: stripHtmlTags(message) })
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
      rows.push({ label: 'Notes', value: stripHtmlTags(metadata.notes) })
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
    if (body && body.length > SUMMARY_COLLAPSE_THRESHOLD) {
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

  const handleToggleDetails = (event: MouseEvent | KeyboardEvent) => {
    event.stopPropagation()
    if (hasExpandableDetails) {
      setDetailsExpanded((v) => !v)
    }
  }

  return (
    <ListItem
      alignItems="flex-start"
      data-testid={`timeline-entry-${entry.id}`}
      sx={{
        px: 0,
        minWidth: 0,
        maxWidth: '100%',
        overflow: 'hidden',
        borderRadius: 1,
        transition: 'background-color 0.3s ease',
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
        sx={{ minWidth: 0, overflow: 'hidden' }}
        primary={
          <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap sx={{ maxWidth: '100%' }}>
            <Typography variant="body2" fontWeight="medium" data-testid={`entry-event-type-${entry.id}`} sx={{ overflowWrap: 'anywhere' }}>
              {getTimelineEventLabel(entry)}
            </Typography>
            <Typography variant="caption" color="text.secondary" data-testid={`entry-timestamp-${entry.id}`} sx={{ flexShrink: 0 }}>
              {formatLocalTimestamp(entry.occurred_at)}
            </Typography>
            <Typography variant="caption" color="text.secondary" data-testid={`entry-actor-${entry.id}`} sx={{ overflowWrap: 'anywhere' }}>
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
              <IconButton
                size="small"
                onClick={handleToggleDetails}
                aria-expanded={detailsExpanded}
                aria-label={detailsExpanded ? 'Hide details' : 'Show details'}
                data-testid={`entry-details-toggle-${entry.id}`}
                sx={{ ml: 'auto', color: 'text.secondary' }}
              >
                {detailsExpanded ? (
                  <ExpandLessIcon fontSize="small" />
                ) : (
                  <ExpandMoreIcon fontSize="small" />
                )}
              </IconButton>
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
                    sx={{
                      mt: 0.25,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      cursor: 'pointer',
                      '&:hover': { color: 'text.primary' },
                    }}
                    onClick={handleToggleDetails}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        handleToggleDetails(event)
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    aria-expanded={detailsExpanded}
                    aria-label={detailsExpanded ? 'Hide details' : 'Show details'}
                    data-testid={`entry-summary-${entry.id}`}
                  >
                    {previewText}
                  </Typography>
                )}
                <Collapse in={detailsExpanded}>
                  <Box
                    sx={{
                      mt: 0.5,
                      pl: 0.5,
                      borderLeft: 2,
                      borderColor: 'divider',
                    }}
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

function mergeTimelineEntries(
  refreshedEntries: LeadTimelineEntry[],
  existingEntries: LeadTimelineEntry[],
): LeadTimelineEntry[] {
  const seen = new Set<number>()
  const merged: LeadTimelineEntry[] = []
  const append = (entry: LeadTimelineEntry) => {
    if (seen.has(entry.id)) return
    seen.add(entry.id)
    merged.push(entry)
  }
  refreshedEntries.forEach(append)
  existingEntries.forEach(append)
  return merged
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
  leadId,
  initialEntries,
  initialTotal,
  onLoadMore,
  highlightEntryId = null,
}: LeadTimelineProps) {
  const initialScopedRef = useRef<ReturnType<typeof scopeRowsToLeadWithTotal<LeadTimelineEntry>> | null>(null)
  if (initialScopedRef.current === null) {
    initialScopedRef.current = scopeRowsToLeadWithTotal(
      initialEntries,
      leadId,
      'timeline',
      initialTotal,
    )
  }
  const [entries, setEntries] = useState<LeadTimelineEntry[]>(() => initialScopedRef.current!.rows)
  const [total, setTotal] = useState(() => initialScopedRef.current!.total)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAllLoaded, setShowAllLoaded] = useState(false)
  const leadIdRef = useRef(leadId)
  const previousLeadIdRef = useRef(leadId)
  const requestSeqRef = useRef(0)
  leadIdRef.current = leadId

  // Fail-closed at the prop boundary (standalone use + defense when parent
  // already scoped). Same-lead refreshes merge into loaded pages so activity
  // logs do not collapse pagination back to page 1.
  useEffect(() => {
    const scoped = scopeRowsToLeadWithTotal(
      initialEntries,
      leadId,
      'timeline',
      initialTotal,
    )
    const leadChanged = previousLeadIdRef.current !== leadId
    setEntries((prev) => {
      if (leadChanged) return scoped.rows
      return mergeTimelineEntries(
        scoped.rows,
        scopeRowsToLead(prev, leadId, 'timeline'),
      )
    })
    setTotal((prevTotal) => leadChanged ? scoped.total : Math.max(prevTotal, scoped.total))
    previousLeadIdRef.current = leadId
  }, [leadId, initialEntries, initialTotal])

  // Only collapse the expanded timeline when navigating to a different lead —
  // not when the same lead's entries refresh after an activity log.
  useEffect(() => {
    requestSeqRef.current += 1
    setShowAllLoaded(false)
    setPage(1)
    setLoading(false)
    setError(null)
  }, [leadId])

  const hasMore = entries.length < total
  const inPreview = !showAllLoaded && total > TIMELINE_PREVIEW_COUNT
  const visibleEntries = inPreview
    ? entries.slice(0, TIMELINE_PREVIEW_COUNT)
    : entries
  const olderRemaining = Math.max(0, total - TIMELINE_PREVIEW_COUNT)

  const handleLoadMore = async () => {
    if (!onLoadMore || loading) return
    setLoading(true)
    setError(null)
    const requestedLeadId = leadId
    const requestSeq = ++requestSeqRef.current
    const isActiveRequest = () =>
      requestSeq === requestSeqRef.current && requestedLeadId === leadIdRef.current
    try {
      const nextPage = page + 1
      const result = await onLoadMore(nextPage)
      // Drop late responses after queue advance to another lead.
      if (!isActiveRequest()) return
      const scoped = scopeRowsToLeadWithTotal(
        result.entries,
        requestedLeadId,
        'timeline',
        result.total,
      )
      // Append new entries (do NOT replace existing ones); re-scope prev in case
      // of a race, then adopt the adjusted total from this page response.
      setEntries((prev) => [
        ...scopeRowsToLead(prev, requestedLeadId, 'timeline'),
        ...scoped.rows,
      ])
      setTotal(scoped.total)
      setPage(nextPage)
      setShowAllLoaded(true)
    } catch (err) {
      if (!isActiveRequest()) return
      setError(err instanceof Error ? err.message : 'Failed to load more entries.')
    } finally {
      if (isActiveRequest()) {
        setLoading(false)
      }
    }
  }

  const handleShowOlder = () => {
    setShowAllLoaded(true)
  }

  return (
    <Box data-testid="lead-timeline">
      <Accordion
        defaultExpanded
        disableGutters
        elevation={0}
        sx={{
          bgcolor: 'transparent',
          '&:before': { display: 'none' },
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
        }}
        data-testid="timeline-accordion"
      >
        <AccordionSummary
          expandIcon={<ExpandMoreIcon />}
          aria-controls="lead-timeline-content"
          id="lead-timeline-header"
          sx={{ minHeight: 44, px: 1.5, '& .MuiAccordionSummary-content': { my: 1 } }}
        >
          <Typography variant="subtitle1" fontWeight="bold" component="span">
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
        </AccordionSummary>
        <AccordionDetails sx={{ px: 1.5, pt: 0, pb: 1.5 }}>
          {entries.length === 0 && (
            <Typography
              variant="body2"
              color="text.secondary"
              data-testid="timeline-empty"
            >
              No timeline entries yet.
            </Typography>
          )}

          {entries.length > 0 && (
            <List dense disablePadding data-testid="timeline-list">
              {visibleEntries.map((entry, index) => (
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

          {inPreview && (
            <Box sx={{ mt: 1, textAlign: 'center' }}>
              <Button
                size="small"
                onClick={handleShowOlder}
                data-testid="timeline-show-older-btn"
              >
                Show older activity ({olderRemaining} more)
              </Button>
            </Box>
          )}

          {!inPreview && hasMore && onLoadMore && (
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

          {entries.length > 0 && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ mt: 1, display: 'block' }}
              data-testid="timeline-showing"
            >
              Showing {visibleEntries.length} of {total}
            </Typography>
          )}

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
        </AccordionDetails>
      </Accordion>
    </Box>
  )
}

export default LeadTimeline
