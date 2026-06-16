import React, { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useTheme,
  useMediaQuery,
  Box,
  InputBase,
  IconButton,
  Paper,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  ListSubheader,
  CircularProgress,
  Chip,
  Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import type { SearchResponse, SearchMatchContext } from '@/types'
import { searchService } from '@/services/api'

// ---------------------------------------------------------------------------
// Match context rendering helpers
// ---------------------------------------------------------------------------

/** Returns a label like "Phone" | "Email" for the match type badge. */
function matchTypeLabel(type: SearchMatchContext['type']): string {
  switch (type) {
    case 'phone': return 'Phone'
    case 'email': return 'Email'
    case 'address': return 'Address'
    case 'name': return 'Name'
  }
}

/**
 * Renders a value string with the query substring highlighted in bold.
 * Uses an explicit fontWeight span so MUI Typography doesn't strip bold styling.
 */
function highlightMatch(value: string, query: string): React.ReactNode {
  if (!query) return value
  // For phone searches the query might be digits-only (e.g. "0106") but the
  // stored value has formatting ("(773) 454-0106"). Try the raw query first,
  // then fall back to matching just the digit run.
  const lv = value.toLowerCase()
  const lq = query.toLowerCase()
  let idx = lv.indexOf(lq)

  if (idx === -1) {
    // digits-only query: find the digit sequence within the formatted value
    const digits = query.replace(/\D/g, '')
    if (digits.length >= 4) {
      // Find position in value where the digit run of the query appears
      let di = 0
      let vi = 0
      let startVi = -1
      while (vi < value.length && di < digits.length) {
        if (/\d/.test(value[vi])) {
          if (value[vi] === digits[di]) {
            if (di === 0) startVi = vi
            di++
            if (di === digits.length) { idx = startVi; break }
          } else {
            di = 0; startVi = -1
          }
        }
        vi++
      }
      if (idx !== -1) {
        // Bold from startVi through the end of the digit run (skip formatting chars)
        let endVi = vi
        // Extend end to include trailing formatting chars like last digit position
        return (
          <>
            {value.slice(0, idx)}
            <Box component="span" sx={{ fontWeight: 700, color: 'text.primary' }}>
              {value.slice(idx, endVi + 1)}
            </Box>
            {value.slice(endVi + 1)}
          </>
        )
      }
    }
    return value
  }

  const matchLen = lq.length
  return (
    <>
      {value.slice(0, idx)}
      <Box component="span" sx={{ fontWeight: 700, color: 'text.primary' }}>
        {value.slice(idx, idx + matchLen)}
      </Box>
      {value.slice(idx + matchLen)}
    </>
  )
}

const GlobalSearchBar = () => {
  const navigate = useNavigate()
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'))

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [focusedIndex, setFocusedIndex] = useState(-1)
  const [mobileExpanded, setMobileExpanded] = useState(false)

  // Refs for debounce, AbortController, and input element
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleQueryChange = useCallback((newQuery: string) => {
    setQuery(newQuery)
    setFocusedIndex(-1)

    // Cancel any pending debounce timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }

    // Cancel any in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    const trimmed = newQuery.trim()

    if (trimmed.length < 2) {
      setResults(null)
      setIsOpen(false)
      setError(null)
      return
    }

    // Debounce: dispatch search after 300ms
    debounceTimerRef.current = setTimeout(async () => {
      const controller = new AbortController()
      abortControllerRef.current = controller

      setIsLoading(true)
      setIsOpen(true)
      setError(null)

      try {
        const data = await searchService.search(trimmed, controller.signal)
        if (!controller.signal.aborted) {
          setResults(data)
          setIsOpen(true)
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Cancelled — ignore silently
          return
        }
        // Also handle Axios CanceledError
        if (err instanceof Error && err.name === 'CanceledError') {
          return
        }
        if (!controller.signal.aborted) {
          setError('Search failed. Please try again.')
          setIsOpen(true)
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      }
    }, 300)
  }, [])

  const clearSearch = useCallback(() => {
    setQuery('')
    setResults(null)
    setIsOpen(false)
    setError(null)
    setFocusedIndex(-1)

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
      if (abortControllerRef.current) abortControllerRef.current.abort()
    }
  }, [])

  // Build a flat list of all result items for keyboard navigation
  const allItems = [
    ...(results?.leads ?? []),
    ...(results?.sessions ?? []),
  ]

  // Determine dropdown content
  const hasLeads = results?.leads && results.leads.length > 0
  const hasSessions = results?.sessions && results.sessions.length > 0
  const isEmpty = !isLoading && !error && !hasLeads && !hasSessions

  return (
    <Box
      sx={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
      }}
      data-testid="global-search-bar"
    >
      {/* Desktop input — shown when not mobile OR when mobile and expanded */}
      {(!isMobile || mobileExpanded) && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'rgba(255,255,255,0.15)',
            borderRadius: 1,
            px: 1,
            '&:hover': { backgroundColor: 'rgba(255,255,255,0.25)' },
          }}
        >
          <SearchIcon sx={{ color: 'inherit', mr: 0.5, opacity: 0.7 }} />
          <InputBase
            inputRef={inputRef}
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Search name, address, phone, email…"
            inputProps={{ maxLength: 200 }}
            sx={{
              color: 'inherit',
              '& .MuiInputBase-input': {
                padding: '4px 4px',
                width: isMobile ? '100%' : '200px',
                transition: 'width 200ms ease',
                '&:focus': { width: isMobile ? '100%' : '260px' },
              },
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                clearSearch()
                if (isMobile) setMobileExpanded(false)
                inputRef.current?.blur()
                return
              }

              if (!isOpen || allItems.length === 0) return

              switch (e.key) {
                case 'ArrowDown':
                  e.preventDefault()
                  setFocusedIndex(prev => Math.min(prev + 1, allItems.length - 1))
                  break
                case 'ArrowUp':
                  e.preventDefault()
                  setFocusedIndex(prev => Math.max(prev - 1, 0))
                  break
                case 'Enter':
                  if (focusedIndex >= 0 && focusedIndex < allItems.length) {
                    e.preventDefault()
                    const item = allItems[focusedIndex]
                    if (!item.nav_path) {
                      setError('Search failed. Please try again.')
                      return
                    }
                    navigate(item.nav_path)
                    clearSearch()
                    if (isMobile) setMobileExpanded(false)
                  }
                  break
              }
            }}
            onBlur={() => {
              if (isMobile && !query) {
                setMobileExpanded(false)
              }
            }}
            data-testid="search-input"
          />
        </Box>
      )}

      {/* Mobile collapsed icon button — shown when mobile and not expanded */}
      {isMobile && !mobileExpanded && (
        <IconButton
          color="inherit"
          onClick={() => {
            setMobileExpanded(true)
            // Auto-focus the input after state update
            setTimeout(() => inputRef.current?.focus(), 0)
          }}
          data-testid="search-icon-button"
          aria-label="Open search"
        >
          <SearchIcon />
        </IconButton>
      )}

      {/* Results dropdown */}
      {isOpen && (
        <Paper
          elevation={8}
          sx={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 1300,
            maxHeight: 400,
            overflowY: 'auto',
            minWidth: 280,
          }}
          data-testid="search-dropdown"
        >
          {/* Loading state */}
          {isLoading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
              <CircularProgress size={24} color="inherit" />
            </Box>
          )}

          {/* Error state */}
          {!isLoading && error && (
            <Box sx={{ p: 2 }}>
              <Typography variant="body2" color="error">
                Search failed. Please try again.
              </Typography>
            </Box>
          )}

          {/* Empty state */}
          {isEmpty && isOpen && (
            <Box sx={{ p: 2 }}>
              <Typography variant="body2" color="text.secondary">
                No results found
              </Typography>
            </Box>
          )}

          {/* Results grouped by section */}
          {!isLoading && !error && (hasLeads || hasSessions) && (
            <List dense disablePadding>
              {/* Leads section */}
              {results?.leads && results.leads.length > 0 && (
                <>
                  <ListSubheader>Leads</ListSubheader>
                  {results.leads.map((lead, idx) => (
                    <ListItem key={`lead-${lead.id}`} disablePadding>
                      <ListItemButton
                        selected={idx === focusedIndex}
                        sx={idx === focusedIndex ? { backgroundColor: 'action.selected' } : {}}
                        onClick={() => {
                          navigate(lead.nav_path)
                          clearSearch()
                          if (isMobile) setMobileExpanded(false)
                        }}
                        data-testid={`lead-result-${lead.id}`}
                      >
                        <ListItemText
                          primary={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography variant="body2">{lead.label}</Typography>
                              {lead.lead_score != null && (
                                <Chip
                                  label={lead.lead_score}
                                  size="small"
                                  variant="outlined"
                                  sx={{ height: 18, fontSize: '0.7rem' }}
                                />
                              )}
                            </Box>
                          }
                          secondary={
                            lead.match_context ? (
                              <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
                                <Box
                                  component="span"
                                  sx={{ color: 'text.disabled', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: '0.6rem' }}
                                >
                                  {matchTypeLabel(lead.match_context.type)}:&nbsp;
                                </Box>
                                <Box component="span" sx={{ fontSize: '0.75rem', color: 'text.secondary' }}>
                                  {highlightMatch(lead.match_context.value, query)}
                                </Box>
                              </Box>
                            ) : undefined
                          }
                          secondaryTypographyProps={{ component: 'span' }}
                        />
                      </ListItemButton>
                    </ListItem>
                  ))}
                </>
              )}

              {/* Analysis Sessions section */}
              {results?.sessions && results.sessions.length > 0 && (
                <>
                  <ListSubheader>Analysis Sessions</ListSubheader>
                  {results.sessions.map((session, idx) => {
                    const sessionIdx = (results?.leads?.length ?? 0) + idx
                    return (
                    <ListItem key={`session-${session.id}`} disablePadding>
                      <ListItemButton
                        selected={sessionIdx === focusedIndex}
                        sx={sessionIdx === focusedIndex ? { backgroundColor: 'action.selected' } : {}}
                        onClick={() => {
                          navigate(session.nav_path)
                          clearSearch()
                          if (isMobile) setMobileExpanded(false)
                        }}
                        data-testid={`session-result-${session.id}`}
                      >
                        <ListItemText
                          primary={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography variant="body2">{session.label}</Typography>
                              {session.status && (
                                <Chip
                                  label={session.status}
                                  size="small"
                                  color={session.status === 'Complete' ? 'success' : 'default'}
                                  sx={{ height: 18, fontSize: '0.7rem' }}
                                />
                              )}
                            </Box>
                          }
                          secondary={
                            session.created_at
                              ? new Date(session.created_at).toLocaleDateString('en-US', {
                                  month: '2-digit',
                                  day: '2-digit',
                                  year: 'numeric',
                                })
                              : undefined
                          }
                        />
                      </ListItemButton>
                    </ListItem>
                    )
                  })}
                </>
              )}
            </List>
          )}
        </Paper>
      )}
    </Box>
  )
}

export default GlobalSearchBar
