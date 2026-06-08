/**
 * DealKanbanContext — React context for the Kanban board state.
 *
 * Now reads from the leads table via /api/kanban/leads, grouping leads
 * by recommended_action instead of deal pipeline stages.
 *
 * Supports pagination: loads 50 leads per column by default, with
 * "Load all" expand functionality for individual columns.
 */
import React, { createContext, useContext, useCallback, useReducer, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { leadKanbanService } from '@/services/api'
import type {
  LeadKanbanColumn,
  KanbanFilters,
  KanbanSortField,
} from '@/types'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_LIMIT = 50

// ---------------------------------------------------------------------------
// Action types
// ---------------------------------------------------------------------------

type KanbanAction =
  | { type: 'SET_COLUMNS'; columns: LeadKanbanColumn[] }
  | { type: 'MERGE_COLUMNS'; expandedColumns: LeadKanbanColumn[] }
  | { type: 'MOVE_LEAD'; leadId: number; fromColId: string; toColId: string }
  | { type: 'SET_FILTERS'; filters: KanbanFilters }
  | { type: 'SET_SORT'; field: KanbanSortField; direction: 'asc' | 'desc' }
  | { type: 'SET_LOADING'; isLoading: boolean }
  | { type: 'SET_ERROR'; error: string | null }

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

interface KanbanState {
  columns: LeadKanbanColumn[]
  filters: KanbanFilters
  sortField: KanbanSortField
  sortDirection: 'asc' | 'desc'
  isLoading: boolean
  error: string | null
  total_counts: Record<string, number>
}

const initialState: KanbanState = {
  columns: [],
  filters: {},
  sortField: 'lead_score',
  sortDirection: 'desc',
  isLoading: false,
  error: null,
  total_counts: {},
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

function kanbanReducer(state: KanbanState, action: KanbanAction): KanbanState {
  switch (action.type) {
    case 'SET_COLUMNS':
      return { ...state, columns: action.columns }
    case 'MERGE_COLUMNS': {
      // Only replace columns that were returned by the expanded fetch,
      // keeping existing columns untouched
      const merged = state.columns.map((col) => {
        const expanded = action.expandedColumns.find((c) => c.id === col.id)
        return expanded ?? col
      })
      return { ...state, columns: merged }
    }
    case 'MOVE_LEAD': {
      const { leadId, fromColId, toColId } = action
      const newColumns = state.columns.map((col) => {
        if (col.id === fromColId) {
          return {
            ...col,
            leads: col.leads.filter((l) => l.id !== leadId),
            count: col.count - 1,
          }
        }
        if (col.id === toColId) {
          const moved = state.columns
            .find((c) => c.id === fromColId)
            ?.leads.find((l) => l.id === leadId)
          if (moved) {
            return {
              ...col,
              leads: [
                ...col.leads,
                { ...moved, recommended_action: toColId },
              ],
              count: col.count + 1,
            }
          }
        }
        return col
      })
      return { ...state, columns: newColumns }
    }
    case 'SET_FILTERS':
      return { ...state, filters: action.filters }
    case 'SET_SORT':
      return { ...state, sortField: action.field, sortDirection: action.direction }
    case 'SET_LOADING':
      return { ...state, isLoading: action.isLoading }
    case 'SET_ERROR':
      return { ...state, error: action.error }
    default:
      return state
  }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface LeadKanbanContextValue {
  state: KanbanState
  moveLead: (leadId: number, fromColId: string, toColId: string) => void
  setFilters: (filters: KanbanFilters) => void
  setSort: (field: KanbanSortField, direction: 'asc' | 'desc') => void
  refetchAll: () => void
  isLoading: boolean
  error: string | null
  expandColumn: (columnId: string) => void
  expandedColumns: Set<string>
  total_counts: Record<string, number>
}

const LeadKanbanContext = createContext<LeadKanbanContextValue | null>(null)

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function LeadKanbanProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(kanbanReducer, initialState)
  const [expandedColumns, setExpandedColumns] = useState<Set<string>>(new Set())
  const queryClient = useQueryClient()

  // Fetch kanban columns from the leads API — default limited fetch
  const {
    data: columnsData,
    isLoading,
    error: fetchError,
  } = useQuery({
    queryKey: ['kanban-leads', { limit: DEFAULT_LIMIT }],
    queryFn: async () => {
      try {
        const response = await leadKanbanService.getKanbanLeads({ limit: DEFAULT_LIMIT })
        return response
      } catch (err) {
        dispatch({
          type: 'SET_ERROR',
          error: (err as Error)?.message ?? 'An unknown error occurred',
        })
        return { columns: [] as LeadKanbanColumn[], total_counts: {} }
      }
    },
    staleTime: 30 * 1000,
  })

  // Sync columns and total_counts from query into reducer state
  React.useEffect(() => {
    if (columnsData) {
      dispatch({ type: 'SET_COLUMNS', columns: columnsData.columns })
      // Store total_counts in state via a SET_TOTAL_COUNTS-like approach,
      // but we'll just store it alongside columns
      setStoredTotalCounts(columnsData.total_counts)
    }
  }, [columnsData])

  // We need a separate state for total_counts since it's not in the reducer
  const [storedTotalCounts, setStoredTotalCounts] = useState<Record<string, number>>({})

  React.useEffect(() => {
    dispatch({ type: 'SET_LOADING', isLoading })
  }, [isLoading])

  // Move lead mutation
  const moveMutation = useMutation({
    mutationFn: ({
      leadId,
      targetAction,
    }: {
      leadId: number
      targetAction: string
    }) => leadKanbanService.moveKanbanLead(leadId, targetAction),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kanban-leads'] })
    },
  })

  const moveLead = useCallback(
    (leadId: number, fromColId: string, toColId: string) => {
      // Optimistic update
      dispatch({ type: 'MOVE_LEAD', leadId, fromColId, toColId })
      // Fire mutation with rollback on error
      moveMutation.mutate(
        { leadId, targetAction: toColId },
        {
          onError: () => {
            // Revert optimistic update: move lead back to original column
            dispatch({ type: 'MOVE_LEAD', leadId, fromColId: toColId, toColId: fromColId })
          },
        },
      )
    },
    [moveMutation],
  )

  const setFilters = useCallback((filters: KanbanFilters) => {
    dispatch({ type: 'SET_FILTERS', filters })
  }, [])

  const setSort = useCallback(
    (field: KanbanSortField, direction: 'asc' | 'desc') => {
      dispatch({ type: 'SET_SORT', field, direction })
    },
    [],
  )

  const refetchAll = useCallback(() => {
    setExpandedColumns(new Set())
    queryClient.invalidateQueries({ queryKey: ['kanban-leads'] })
  }, [queryClient])

  const expandColumn = useCallback(
    (columnId: string) => {
      // Mark this column as expanded
      setExpandedColumns((prev) => {
        const next = new Set(prev)
        next.add(columnId)
        return next
      })

      // Refetch with column_id to get all leads for that column
      queryClient.fetchQuery({
        queryKey: ['kanban-leads-expand', columnId],
        queryFn: async () => {
          const response = await leadKanbanService.getKanbanLeads({
            column_id: columnId,
          })
          return response
        },
      }).then((response) => {
        // Merge the expanded column's leads into the existing columns
        // (only replaces the matching column, keeps others intact)
        dispatch({ type: 'MERGE_COLUMNS', expandedColumns: response.columns })
        setStoredTotalCounts(response.total_counts)
      })
    },
    [queryClient],
  )

  const value = useMemo<LeadKanbanContextValue>(
    () => ({
      state: { ...state, total_counts: storedTotalCounts },
      moveLead,
      setFilters,
      setSort,
      refetchAll,
      expandColumn,
      expandedColumns,
      total_counts: storedTotalCounts,
      isLoading: moveMutation.isPending || isLoading,
      error: fetchError
        ? (fetchError as Error)?.message ?? 'Failed to load leads'
        : state.error,
    }),
    [
      state,
      moveLead,
      setFilters,
      setSort,
      refetchAll,
      expandColumn,
      expandedColumns,
      storedTotalCounts,
      moveMutation.isPending,
      isLoading,
      fetchError,
    ],
  )

  return (
    <LeadKanbanContext.Provider value={value}>
      {children}
    </LeadKanbanContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useLeadKanban(): LeadKanbanContextValue {
  const ctx = useContext(LeadKanbanContext)
  if (!ctx) {
    throw new Error('useLeadKanban must be used within a LeadKanbanProvider')
  }
  return ctx
}

export default LeadKanbanContext