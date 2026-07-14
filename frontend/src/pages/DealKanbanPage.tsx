/**
 * DealKanbanPage — main Kanban board view for managing leads with drag-and-drop.
 *
 * Displays lead_status columns, fetches leads per column, and supports
 * filtering and sorting with pagination.
 */
import { useNavigate } from 'react-router-dom'
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  IconButton,
  Tooltip,
  Collapse,
  Stack,
} from '@mui/material'
import FilterListIcon from '@mui/icons-material/FilterList'
import SortIcon from '@mui/icons-material/Sort'
import RefreshIcon from '@mui/icons-material/Refresh'
import ViewKanbanIcon from '@mui/icons-material/ViewKanban'
import { LeadKanbanProvider, useLeadKanban } from '@/context/DealKanbanContext'
import { KanbanColumn } from '@/components/KanbanColumn'
import { DealCard } from '@/components/DealCard'
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import type { LeadKanbanCard, KanbanFilters, KanbanSortField } from '@/types'
import { useState, useMemo, useCallback } from 'react';

// ---------------------------------------------------------------------------
// Filter/sort bar
// ---------------------------------------------------------------------------

interface FilterBarProps {
  filters: KanbanFilters
  sortField: KanbanSortField
  sortDirection: 'asc' | 'desc'
  onFiltersChange: (filters: KanbanFilters) => void
  onSortChange: (field: KanbanSortField, direction: 'asc' | 'desc') => void
}

function FilterBar({
  filters,
  sortField,
  sortDirection,
  onFiltersChange,
  onSortChange,
}: FilterBarProps) {
  const [showFilters, setShowFilters] = useState(false)

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          gap: 1,
          alignItems: 'center',
          mb: 1,
          flexWrap: 'wrap',
        }}
      >
        <Tooltip title="Toggle filters">
          <IconButton
            size="small"
            onClick={() => setShowFilters((v) => !v)}
            color={showFilters ? 'primary' : 'default'}
          >
            <FilterListIcon />
          </IconButton>
        </Tooltip>

        <FormControl size="small" sx={{ minWidth: { xs: 120, sm: 140 }, flex: { xs: '1 1 auto', sm: '0 0 auto' } }}>
          <InputLabel id="kanban-sort-label">Sort by</InputLabel>
          <Select
            labelId="kanban-sort-label"
            value={sortField}
            label="Sort by"
            onChange={(e) =>
              onSortChange(e.target.value as KanbanSortField, sortDirection)
            }
          >
            <MenuItem value="lead_score">Lead Score</MenuItem>
          </Select>
        </FormControl>

        <Tooltip title="Toggle sort direction">
          <IconButton
            size="small"
            onClick={() =>
              onSortChange(
                sortField,
                sortDirection === 'asc' ? 'desc' : 'asc'
              )
            }
          >
            <SortIcon
              sx={{
                transform:
                  sortDirection === 'desc' ? 'scaleY(-1)' : 'scaleY(1)',
              }}
            />
          </IconButton>
        </Tooltip>
      </Box>

      <Collapse in={showFilters}>
        <Stack direction="row" spacing={2} useFlexGap sx={{ mb: 2 }} flexWrap="wrap">
          <TextField
            size="small"
            label="Min Score"
            type="number"
            value={filters.valueMin ?? ''}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                valueMin: e.target.value ? Number(e.target.value) : undefined,
              })
            }
            sx={{ minWidth: 120, flex: { xs: '1 1 120px', sm: '0 0 auto' } }}
          />
          <TextField
            size="small"
            label="Max Score"
            type="number"
            value={filters.valueMax ?? ''}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                valueMax: e.target.value ? Number(e.target.value) : undefined,
              })
            }
            sx={{ minWidth: 120, flex: { xs: '1 1 120px', sm: '0 0 auto' } }}
          />
        </Stack>
      </Collapse>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Inner board component (consumes context)
// ---------------------------------------------------------------------------

function KanbanBoardInner() {
  const navigate = useNavigate()
  const { state, moveLead, setFilters, setSort, refetchAll, isLoading, error, expandColumn, total_counts } =
    useLeadKanban()
  const [activeLead, setActiveLead] = useState<LeadKanbanCard | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  // Apply filters and sorting to leads before passing to columns
  const filteredColumns = useMemo(() => {
    return state.columns.map((col) => {
      let filtered = [...col.leads]

      // Apply score range filter
      if (state.filters.valueMin != null) {
        filtered = filtered.filter(
          (l) => (l.lead_score ?? 0) >= (state.filters.valueMin ?? 0)
        )
      }
      if (state.filters.valueMax != null) {
        filtered = filtered.filter(
          (l) => (l.lead_score ?? 0) <= (state.filters.valueMax ?? 0)
        )
      }

      // Apply sorting
      filtered.sort((a, b) => {
        let cmp = 0
        if (state.sortField === 'lead_score') {
          cmp = (a.lead_score ?? 0) - (b.lead_score ?? 0)
        }
        return state.sortDirection === 'asc' ? cmp : -cmp
      })

      return { ...col, leads: filtered, count: filtered.length }
    })
  }, [state.columns, state.filters, state.sortField, state.sortDirection])

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const lead = event.active.data.current?.deal as LeadKanbanCard | undefined
      if (lead) setActiveLead(lead)
    },
    []
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveLead(null)
      const { active, over } = event
      if (!over) return

      const leadData = active.data.current?.deal as LeadKanbanCard | undefined
      const fromColId = leadData?.lead_status ?? ''
      const toColId = over.data.current?.stageName as string | undefined

      if (!fromColId || !toColId || fromColId === toColId) return

      const leadId = Number(active.id.toString().replace('deal-', ''))
      if (!isNaN(leadId)) {
        moveLead(leadId, fromColId, toColId)
      }
    },
    [moveLead]
  )

  const handleLeadClick = useCallback(
    (leadId: number) => {
      navigate(`/properties/${leadId}`)
    },
    [navigate]
  )

  const handleLoadMore = useCallback(
    (columnId: string) => {
      expandColumn(columnId)
    },
    [expandColumn]
  )

  if (error) {
    return (
      <Alert severity="error" sx={{ m: 2 }}>
        {error}
      </Alert>
    )
  }

  if (state.columns.length === 0 && isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress aria-label="Loading kanban board" />
      </Box>
    )
  }

  if (state.columns.length === 0) {
    return (
      <Box sx={{ p: 4, textAlign: 'center' }}>
        <Typography color="text.secondary">
          No leads found. Import leads to get started.
        </Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ width: '100%', maxWidth: '100%', minWidth: 0, overflow: 'hidden' }}>
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: { xs: 'flex-start', sm: 'center' },
          mb: 2,
          flexWrap: 'wrap',
          gap: 1,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, flex: 1 }}>
          <ViewKanbanIcon color="primary" />
          <Typography
            variant="h5"
            component="h1"
            fontWeight={600}
            sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
          >
            Lead Pipeline Kanban
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Tooltip title="Refresh">
            <IconButton onClick={refetchAll} size="small">
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      {/* Filter/Sort Bar */}
      <FilterBar
        filters={state.filters}
        sortField={state.sortField}
        sortDirection={state.sortDirection}
        onFiltersChange={setFilters}
        onSortChange={setSort}
      />

      {/* Kanban Columns */}
      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <Box
          sx={{
            display: 'flex',
            gap: 2,
            overflowX: 'auto',
            overflowY: 'auto',
            pb: 2,
            flexWrap: 'nowrap',
            WebkitOverflowScrolling: 'touch',
            maxWidth: '100%',
            minWidth: 0,
            maxHeight: {
              xs: 'calc(100vh - 220px)',
              sm: 'calc(100vh - 200px)',
            },
          }}
        >
          {filteredColumns
            .sort((a, b) => a.sort_order - b.sort_order)
            .map((col) => (
              <KanbanColumn
                key={col.id}
                column={col}
                onDealClick={handleLeadClick}
                onLoadMore={handleLoadMore}
                totalCount={total_counts[col.id] ?? col.count}
              />
            ))}
        </Box>

        <DragOverlay>
          {activeLead ? (
            <Box sx={{ opacity: 0.8, maxWidth: 280 }}>
              <DealCard deal={activeLead} />
            </Box>
          ) : null}
        </DragOverlay>
      </DndContext>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Page component (wraps with provider)
// ---------------------------------------------------------------------------

export function DealKanbanPage() {
  return (
    <LeadKanbanProvider>
      <KanbanBoardInner />
    </LeadKanbanProvider>
  )
}

export default DealKanbanPage