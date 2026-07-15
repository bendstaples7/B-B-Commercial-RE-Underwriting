import { useRef, useState, useEffect, useMemo } from 'react'
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import {
  useTheme,
  useMediaQuery,
  Box,
  CircularProgress,
  Divider,
  IconButton,
  InputBase,
  List,
  ListItemButton,
  ListItemText,
  ListSubheader,
  Paper,
  Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import { searchService } from '@/services/api'
import type { SearchResponse, SearchResultItem } from '@/types'
import { highlightMatch, matchTypeLabel } from '@/utils/searchResultDisplay'

const SEARCH_DEBOUNCE_MS = 300

/**
 * GlobalSearchBar — header search input that navigates to the full search results page.
 */
const GlobalSearchBar = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'))

  const onSearchPage = location.pathname === '/search'
  const urlQuery = onSearchPage ? (searchParams.get('q') ?? '') : ''

  const [query, setQuery] = useState(urlQuery)
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [searchData, setSearchData] = useState<SearchResponse | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState(false)
  const [focused, setFocused] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const [mobileExpanded, setMobileExpanded] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const trimmedQuery = query.trim()

  useEffect(() => {
    if (onSearchPage) {
      setQuery(urlQuery)
    }
  }, [onSearchPage, urlQuery])

  useEffect(() => {
    if (!focused || trimmedQuery.length < 2) {
      setDebouncedQuery('')
      setSearchData(null)
      setSearchLoading(false)
      setSearchError(false)
      setHighlightedIndex(-1)
      return
    }
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => {
      setDebouncedQuery(trimmedQuery)
      setSearchLoading(true)
      setSearchError(false)
      void searchService
        .search({ q: trimmedQuery, page: 1, per_page: 10, signal: controller.signal })
        .then((response) => {
          if (!controller.signal.aborted) setSearchData(response)
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setSearchData(null)
            setSearchError(true)
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearchLoading(false)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [focused, trimmedQuery])

  const resultItems = useMemo(
    () => [...(searchData?.leads ?? []), ...(searchData?.sessions ?? [])],
    [searchData?.leads, searchData?.sessions],
  )
  const isDebouncing = trimmedQuery.length >= 2 && debouncedQuery !== trimmedQuery
  const dropdownOpen = focused && trimmedQuery.length >= 2

  useEffect(() => {
    setHighlightedIndex(-1)
  }, [debouncedQuery])

  const navigateToResult = (item: SearchResultItem) => {
    if (!item.nav_path) return
    navigate(item.nav_path)
    setQuery('')
    setDebouncedQuery('')
    setSearchData(null)
    setFocused(false)
    setHighlightedIndex(-1)
    if (isMobile) setMobileExpanded(false)
  }

  const submitSearch = () => {
    const trimmed = query.trim()
    if (trimmed.length < 2) return
    navigate(`/search?q=${encodeURIComponent(trimmed)}&page=1`)
    if (isMobile) setMobileExpanded(false)
    inputRef.current?.blur()
  }

  const clearSearch = () => {
    setQuery('')
    setDebouncedQuery('')
    setFocused(false)
    setHighlightedIndex(-1)
    if (isMobile) setMobileExpanded(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' && resultItems.length > 0) {
      e.preventDefault()
      setHighlightedIndex((current) => Math.min(current + 1, resultItems.length - 1))
      return
    }
    if (e.key === 'ArrowUp' && resultItems.length > 0) {
      e.preventDefault()
      setHighlightedIndex((current) => Math.max(current - 1, 0))
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      if (highlightedIndex >= 0 && resultItems[highlightedIndex]) {
        navigateToResult(resultItems[highlightedIndex])
        return
      }
      submitSearch()
      return
    }
    if (e.key === 'Escape') {
      clearSearch()
      inputRef.current?.blur()
    }
  }

  return (
    <Box
      sx={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
      }}
      onBlur={(event) => {
        const nextTarget = event.relatedTarget as Node | null
        if (!nextTarget || !event.currentTarget.contains(nextTarget)) {
          setFocused(false)
          if (isMobile && !query) setMobileExpanded(false)
        }
      }}
      data-testid="global-search-bar"
    >
      {(!isMobile || mobileExpanded) && (
        <Box
          component="form"
          onSubmit={(e) => {
            e.preventDefault()
            submitSearch()
          }}
          sx={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'rgba(255,255,255,0.15)',
            borderRadius: 1,
            px: 1,
            '&:hover': { backgroundColor: 'rgba(255,255,255,0.25)' },
          }}
        >
          <IconButton
            type="submit"
            size="small"
            color="inherit"
            aria-label="Search"
            sx={{ opacity: 0.85, p: 0.5 }}
            data-testid="search-submit-button"
          >
            <SearchIcon fontSize="small" />
          </IconButton>
          <InputBase
            inputRef={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setFocused(true)
            }}
            onFocus={() => setFocused(true)}
            placeholder="Search name, address, phone, email…"
            inputProps={{
              maxLength: 200,
              role: 'combobox',
              'aria-autocomplete': 'list',
              'aria-expanded': dropdownOpen,
              'aria-controls': dropdownOpen ? 'global-search-results' : undefined,
              'aria-activedescendant':
                highlightedIndex >= 0 ? `global-search-result-${highlightedIndex}` : undefined,
            }}
            sx={{
              color: 'inherit',
              '& .MuiInputBase-input': {
                padding: '4px 4px',
                width: isMobile ? '100%' : '200px',
                transition: 'width 200ms ease',
                '&:focus': { width: isMobile ? '100%' : '260px' },
              },
            }}
            onKeyDown={handleKeyDown}
            data-testid="search-input"
          />
        </Box>
      )}

      {dropdownOpen && (
        <Paper
          id="global-search-results"
          role="listbox"
          elevation={8}
          data-testid="search-dropdown"
          sx={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            right: 0,
            zIndex: 1500,
            width: isMobile ? 'min(92vw, 420px)' : 420,
            maxWidth: '92vw',
            maxHeight: 440,
            overflowY: 'auto',
            color: 'text.primary',
          }}
        >
          {(isDebouncing || searchLoading) && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 2 }}>
              <CircularProgress size={18} />
              <Typography variant="body2" color="text.secondary">
                Searching…
              </Typography>
            </Box>
          )}
          {!isDebouncing && !searchLoading && searchError && (
            <Typography variant="body2" color="error" sx={{ p: 2 }}>
              Search failed. Please try again.
            </Typography>
          )}
          {!isDebouncing && !searchLoading && !searchError && searchData && resultItems.length === 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
              No results found
            </Typography>
          )}
          {!isDebouncing && !searchLoading && !searchError && searchData && resultItems.length > 0 && (
            <List dense disablePadding>
              {searchData.leads.length > 0 && (
                <>
                  <ListSubheader component="div">Leads</ListSubheader>
                  {searchData.leads.slice(0, 10).map((item) => {
                    const index = resultItems.indexOf(item)
                    return (
                      <ListItemButton
                        key={`lead-${item.id}`}
                        id={`global-search-result-${index}`}
                        role="option"
                        selected={highlightedIndex === index}
                        onMouseEnter={() => setHighlightedIndex(index)}
                        onClick={() => navigateToResult(item)}
                      >
                        <ListItemText
                          primary={item.label}
                          secondary={
                            item.match_context
                              ? `${matchTypeLabel(item.match_context.type)}: ${item.match_context.value}`
                              : item.property_street
                          }
                          primaryTypographyProps={{ noWrap: true }}
                          secondaryTypographyProps={{ noWrap: true }}
                        />
                      </ListItemButton>
                    )
                  })}
                </>
              )}
              {searchData.leads.length > 0 && searchData.sessions.length > 0 && <Divider />}
              {searchData.sessions.length > 0 && (
                <>
                  <ListSubheader component="div">Analysis Sessions</ListSubheader>
                  {searchData.sessions.slice(0, 5).map((item) => {
                    const index = resultItems.indexOf(item)
                    return (
                      <ListItemButton
                        key={`session-${item.id}`}
                        id={`global-search-result-${index}`}
                        role="option"
                        selected={highlightedIndex === index}
                        onMouseEnter={() => setHighlightedIndex(index)}
                        onClick={() => navigateToResult(item)}
                      >
                        <ListItemText
                          primary={highlightMatch(item.label, trimmedQuery)}
                          secondary={item.status}
                          primaryTypographyProps={{ noWrap: true }}
                        />
                      </ListItemButton>
                    )
                  })}
                </>
              )}
            </List>
          )}
        </Paper>
      )}

      {isMobile && !mobileExpanded && (
        <IconButton
          color="inherit"
          onClick={() => {
            setMobileExpanded(true)
            setTimeout(() => inputRef.current?.focus(), 0)
          }}
          data-testid="search-icon-button"
          aria-label="Open search"
        >
          <SearchIcon />
        </IconButton>
      )}
    </Box>
  )
}

export default GlobalSearchBar
