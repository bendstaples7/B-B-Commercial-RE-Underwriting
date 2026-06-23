/**
 * SearchResultsPage — full-page paginated search results for leads and sessions.
 */
import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  InputBase,
  Link,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  ListSubheader,
  Pagination,
  Paper,
  Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import { searchService } from '@/services/api'
import { LeadStatusChip } from '@/components/LeadStatusChip'
import { highlightMatch, matchTypeLabel } from '@/utils/searchResultDisplay'
import { clampPage, computeTotalPages } from '@/utils/pagination'

const PER_PAGE = 25

export function SearchResultsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const q = (searchParams.get('q') ?? '').trim()
  const page = Math.max(1, parseInt(searchParams.get('page') ?? '1', 10) || 1)
  const [draftQuery, setDraftQuery] = useState(q)

  useEffect(() => {
    setDraftQuery(q)
  }, [q])

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['search-results', q, page],
    queryFn: () => searchService.search({ q, page, per_page: PER_PAGE }),
    enabled: q.length >= 2,
  })

  const totalPages = computeTotalPages(data?.leads_total ?? 0, PER_PAGE)
  const safePage = clampPage(page, totalPages)

  useEffect(() => {
    if (totalPages > 0 && page !== safePage) {
      setSearchParams({ q, page: String(safePage) }, { replace: true })
    }
  }, [page, safePage, totalPages, q, setSearchParams])

  const submitSearch = (raw: string) => {
    const trimmed = raw.trim()
    if (trimmed.length < 2) return
    navigate(`/search?q=${encodeURIComponent(trimmed)}&page=1`)
  }

  const handlePageChange = (_: React.ChangeEvent<unknown>, newPage: number) => {
    setSearchParams({ q, page: String(newPage) })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const hasLeads = (data?.leads.length ?? 0) > 0
  const hasSessions = (data?.sessions.length ?? 0) > 0
  const isEmpty = !isLoading && !isError && data && !hasLeads && !hasSessions

  return (
    <Box sx={{ maxWidth: 960, mx: 'auto', py: 3, px: 2 }} data-testid="search-results-page">
      <Typography variant="h5" gutterBottom>
        Search
      </Typography>

      <Paper
        component="form"
        elevation={0}
        sx={{
          display: 'flex',
          alignItems: 'center',
          px: 2,
          py: 0.5,
          mb: 3,
          border: 1,
          borderColor: 'divider',
        }}
        onSubmit={(e) => {
          e.preventDefault()
          submitSearch(draftQuery)
        }}
      >
        <SearchIcon color="action" sx={{ mr: 1 }} />
        <InputBase
          value={draftQuery}
          onChange={(e) => setDraftQuery(e.target.value)}
          placeholder="Search name, address, phone, email…"
          inputProps={{ maxLength: 200, 'data-testid': 'search-page-input' }}
          sx={{ flex: 1 }}
          autoFocus
        />
      </Paper>

      {q.length < 2 && (
        <Typography color="text.secondary" data-testid="search-query-hint">
          Enter at least 2 characters to search.
        </Typography>
      )}

      {q.length >= 2 && isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      )}

      {q.length >= 2 && isError && (
        <Alert severity="error" data-testid="search-error">
          {error instanceof Error ? error.message : 'Search failed. Please try again.'}
        </Alert>
      )}

      {q.length >= 2 && data && !isLoading && !isError && (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {data.leads_total === 0 && data.sessions_total === 0 ? (
              <>No results for &ldquo;{q}&rdquo;</>
            ) : (
              <>
                Results for &ldquo;{q}&rdquo; — {data.leads_total} lead
                {data.leads_total === 1 ? '' : 's'}
                {data.sessions_total > 0 && (
                  <>
                    , {data.sessions_total} analysis session
                    {data.sessions_total === 1 ? '' : 's'}
                  </>
                )}
              </>
            )}
          </Typography>

          {isEmpty && (
            <Typography color="text.secondary" data-testid="search-empty">
              No leads or analysis sessions matched your query.
            </Typography>
          )}

          {hasLeads && (
            <Paper variant="outlined" sx={{ mb: 3 }}>
              <List disablePadding data-testid="search-leads-list">
                <ListSubheader component="div" sx={{ bgcolor: 'background.paper', lineHeight: '40px' }}>
                  Leads
                </ListSubheader>
                {data.leads.map((lead) => (
                  <ListItem key={`lead-${lead.id}`} disablePadding divider>
                    <ListItemButton
                      component={RouterLink}
                      to={`/leads/${lead.id}`}
                      data-testid={`search-lead-${lead.id}`}
                    >
                      <ListItemText
                        primary={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                            <Typography variant="body1">{lead.label}</Typography>
                            {lead.lead_score != null && (
                              <Chip
                                label={lead.lead_score}
                                size="small"
                                variant="outlined"
                                sx={{ height: 22 }}
                              />
                            )}
                            {lead.lead_status && <LeadStatusChip status={lead.lead_status} />}
                          </Box>
                        }
                        secondary={
                          lead.match_context ? (
                            <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
                              <Box
                                component="span"
                                sx={{
                                  color: 'text.disabled',
                                  fontWeight: 600,
                                  textTransform: 'uppercase',
                                  letterSpacing: '0.05em',
                                  fontSize: '0.65rem',
                                }}
                              >
                                {matchTypeLabel(lead.match_context.type)}:&nbsp;
                              </Box>
                              <Box component="span" sx={{ fontSize: '0.85rem', color: 'text.secondary' }}>
                                {highlightMatch(lead.match_context.value, q)}
                              </Box>
                            </Box>
                          ) : undefined
                        }
                        secondaryTypographyProps={{ component: 'span' }}
                      />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            </Paper>
          )}

          {totalPages > 1 && (
            <Box sx={{ display: 'flex', justifyContent: 'center', mb: 3 }}>
              <Pagination
                count={totalPages}
                page={safePage}
                onChange={handlePageChange}
                color="primary"
                data-testid="search-pagination"
              />
            </Box>
          )}

          {hasSessions && (
            <Paper variant="outlined">
              <List disablePadding data-testid="search-sessions-list">
                <ListSubheader component="div" sx={{ bgcolor: 'background.paper', lineHeight: '40px' }}>
                  Analysis Sessions
                </ListSubheader>
                {data.sessions.map((session) => (
                  <ListItem key={`session-${session.id}`} disablePadding divider>
                    <ListItemButton
                      component={RouterLink}
                      to={session.nav_path}
                      data-testid={`search-session-${session.id}`}
                    >
                      <ListItemText
                        primary={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography variant="body1">{session.label}</Typography>
                            {session.status && (
                              <Chip
                                label={session.status}
                                size="small"
                                color={session.status === 'Complete' ? 'success' : 'default'}
                                sx={{ height: 22 }}
                              />
                            )}
                          </Box>
                        }
                        secondary={
                          session.created_at
                            ? new Date(session.created_at).toLocaleDateString('en-US', {
                                month: 'short',
                                day: 'numeric',
                                year: 'numeric',
                              })
                            : undefined
                        }
                      />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
              {data.sessions_total > data.sessions.length && (
                <Box sx={{ px: 2, py: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    Showing {data.sessions.length} of {data.sessions_total} sessions.
                  </Typography>
                </Box>
              )}
            </Paper>
          )}

          {hasLeads && (
            <Box sx={{ mt: 2 }}>
              <Link component={RouterLink} to="/properties" variant="body2">
                Browse all properties →
              </Link>
            </Box>
          )}
        </>
      )}
    </Box>
  )
}

export default SearchResultsPage
