/**
 * DealKanbanPage — main Kanban board view for managing deals with drag-and-drop.
 *
 * Displays pipeline stages as columns, fetches deals per stage, and supports
 * filtering (by user, value range, closing date) and sorting (by value, priority score).
 */
import React, { useMemo, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  Button,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  IconButton,
  Tooltip,
  Collapse,
  Stack,
  Grid,
} from '@mui/material'
import FilterListIcon from '@mui/icons-material/FilterList'
import SortIcon from '@mui/icons-material/Sort'
import RefreshIcon from '@mui/icons-material/Refresh'
import ViewKanbanIcon from '@mui/icons-material/ViewKanban'
import SettingsIcon from '@mui/icons-material/Settings'
import { DealKanbanProvider, useDealKanban } from '@/context/DealKanbanContext'
import { KanbanColumn } from '@/components/KanbanColumn'
import { DealCard } from '@/components/DealCard'
import type { DealKanbanCard, KanbanFilters, KanbanSortField } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseValue(value: string | null | undefined): number {
  if (!value) return 0
  const num = parseFloat(value)
  return isNaN(num) ? 0 : num
}

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
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1 }}>
        <Tooltip title="Toggle filters">
          <IconButton
            size="small"
            onClick={() => setShowFilters((v) => !v)}
            color={showFilters ? 'primary' : 'default'}
          >
            <FilterListIcon />
          </IconButton>
        </Tooltip>

        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel id="kanban-sort-label">Sort by</InputLabel>
          <Select
            labelId="kanban-sort-label"
            value={sortField}
            label="Sort by"
            onChange={(e) =>
              onSortChange(e.target.value as KanbanSortField, sortDirection)
            }
          >
            <MenuItem value="priority_score">Priority Score</MenuItem>
            <MenuItem value="purchase_price">Deal Value</MenuItem>
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
        <Stack direction="row" spacing={2} sx={{ mb: 2 }} flexWrap="wrap">
          <TextField
            size="small"
            label="Min Value ($)"
            type="number"
            value={filters.valueMin ?? ''}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                valueMin: e.target.value ? Number(e.target.value) : undefined,
              })
            }
            sx={{ minWidth: 120 }}
          />
          <TextField
            size="small"
            label="Max Value ($)"
            type="number"
            value={filters.valueMax ?? ''}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                valueMax: e.target.value ? Number(e.target.value) : undefined,
              })
            }
            sx={{ minWidth: 120 }}
          />
          <TextField
            size="small"
            label="Closes After"
            type="date"
            value={filters.closingDateFrom ?? ''}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                closingDateFrom: e.target.value || undefined,
              })
            }
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 140 }}
          />
          <TextField
            size="small"
            label="Closes Before"
            type="date"
            value={filters.closingDateTo ?? ''}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                closingDateTo: e.target.value || undefined,
              })
            }
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 140 }}
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
  const { state, moveDeal, setFilters, setSort, refetchAll, isLoading, error } =
    useDealKanban()
  const [activeDeal, setActiveDeal] = useState<DealKanbanCard | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 },
    })
  )

  // Apply filters and sorting to deals before passing to columns
  const filteredDealsByStage = useMemo(() => {
    const result: Record<string, DealKanbanCard[]> = {}

    for (const [stageName, deals] of Object.entries(state.dealsByStage)) {
      let filtered = [...deals]

      // Apply value range filter
      if (state.filters.valueMin != null) {
        filtered = filtered.filter(
          (d) => parseValue(d.purchase_price) >= (state.filters.valueMin ?? 0) * 1000
        )
      }
      if (state.filters.valueMax != null) {
        filtered = filtered.filter(
          (d) => parseValue(d.purchase_price) <= (state.filters.valueMax ?? 0) * 1000
        )
      }

      // Apply closing date range filter
      if (state.filters.closingDateFrom) {
        const from = new Date(state.filters.closingDateFrom)
        filtered = filtered.filter((d) => {
          if (!d.close_date) return true
          return new Date(d.close_date) >= from
        })
      }
      if (state.filters.closingDateTo) {
        const to = new Date(state.filters.closingDateTo)
        filtered = filtered.filter((d) => {
          if (!d.close_date) return true
          return new Date(d.close_date) <= to
        })
      }

      // Apply sorting
      filtered.sort((a, b) => {
        let cmp = 0
        if (state.sortField === 'priority_score') {
          const aScore = a.priority_score ? parseFloat(a.priority_score) : 0
          const bScore = b.priority_score ? parseFloat(b.priority_score) : 0
          cmp = aScore - bScore
        } else {
          const aVal = parseValue(a.purchase_price)
          const bVal = parseValue(b.purchase_price)
          cmp = aVal - bVal
        }
        return state.sortDirection === 'asc' ? cmp : -cmp
      })

      result[stageName] = filtered
    }

    return result
  }, [state.dealsByStage, state.filters, state.sortField, state.sortDirection])

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const deal = event.active.data.current?.deal as DealKanbanCard | undefined
      if (deal) setActiveDeal(deal)
    },
    []
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveDeal(null)
      const { active, over } = event
      if (!over) return

      const fromStage = active.data.current?.deal?.status as string | undefined
      const toStage = over.data.current?.stageName as string | undefined

      if (!fromStage || !toStage || fromStage === toStage) return

      const dealId = Number(active.id.toString().replace('deal-', ''))
      if (!isNaN(dealId)) {
        moveDeal(dealId, fromStage, toStage)
      }
    },
    [moveDeal]
  )

  const handleDealClick = useCallback(
    (dealId: number) => {
      navigate(`/multifamily/deals/${dealId}`)
    },
    [navigate]
  )

  if (error) {
    return (
      <Alert severity="error" sx={{ m: 2 }}>
        {error}
      </Alert>
    )
  }

  if (state.stages.length === 0 && isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress aria-label="Loading kanban board" />
      </Box>
    )
  }

  if (state.stages.length === 0) {
    return (
      <Box sx={{ p: 4, textAlign: 'center' }}>
        <Typography color="text.secondary">
          No pipeline stages configured. Run the seed command to set up initial
          stages.
        </Typography>
      </Box>
    )
  }

  return (
    <Box>
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          mb: 2,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <ViewKanbanIcon color="primary" />
          <Typography variant="h5" component="h1" fontWeight={600}>
            Pipeline Kanban
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Tooltip title="Refresh">
            <IconButton onClick={refetchAll} size="small">
              <RefreshIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="Configure pipeline stages">
            <IconButton onClick={() => navigate('/admin/pipeline-stages')} size="small">
              <SettingsIcon />
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
            pb: 2,
          }}
        >
          {state.stages
            .sort((a, b) => a.order - b.order)
            .map((stage) => (
              <KanbanColumn
                key={stage.stage_name}
                stageName={stage.stage_name}
                deals={filteredDealsByStage[stage.stage_name] ?? []}
                onDealClick={handleDealClick}
              />
            ))}
        </Box>

        <DragOverlay>
          {activeDeal ? (
            <Box sx={{ opacity: 0.8, maxWidth: 280 }}>
              <DealCard deal={activeDeal} />
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
    <DealKanbanProvider>
      <KanbanBoardInner />
    </DealKanbanProvider>
  )
}

export default DealKanbanPage