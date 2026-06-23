import { useRef, useState, useEffect } from 'react'
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import { useTheme, useMediaQuery, Box, InputBase, IconButton } from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'

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
  const [mobileExpanded, setMobileExpanded] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (onSearchPage) {
      setQuery(urlQuery)
    }
  }, [onSearchPage, urlQuery])

  const submitSearch = () => {
    const trimmed = query.trim()
    if (trimmed.length < 2) return
    navigate(`/search?q=${encodeURIComponent(trimmed)}&page=1`)
    if (isMobile) setMobileExpanded(false)
    inputRef.current?.blur()
  }

  const clearSearch = () => {
    setQuery('')
    if (isMobile) setMobileExpanded(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
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
            onChange={(e) => setQuery(e.target.value)}
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
            onKeyDown={handleKeyDown}
            onBlur={() => {
              if (isMobile && !query) setMobileExpanded(false)
            }}
            data-testid="search-input"
          />
        </Box>
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
