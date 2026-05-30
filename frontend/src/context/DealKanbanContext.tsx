/**
 * DealKanbanContext — React context for the Kanban board state.
 *
 * Manages pipeline stages, deals organized by stage, filters, sorting,
 * and drag-and-drop state transitions.
 */
import React, { createContext, useContext, useCallback, useReducer, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { multifamilyService, pipelineConfigService } from '@/services/api'
import type {
  PipelineStage,
  DealKanbanCard,
  KanbanFilters,
  KanbanSortField,
  KanbanState,
} from '@/types'

// ---------------------------------------------------------------------------
// Action types
// ---------------------------------------------------------------------------

type KanbanAction =
  | { type: 'SET_STAGES'; stages: PipelineStage[] }
  | { type: 'SET_DEALS_FOR_STAGE'; stageName: string; deals: DealKanbanCard[] }
  | { type: 'MOVE_DEAL'; dealId: number; fromStage: string; toStage: string }
  | { type: 'SET_FILTERS'; filters: KanbanFilters }
  | { type: 'SET_SORT'; field: KanbanSortField; direction: 'asc' | 'desc' }
  | { type: 'SET_LOADING'; isLoading: boolean }
  | { type: 'SET_ERROR'; error: string | null }

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const initialState: KanbanState = {
  stages: [],
  dealsByStage: {},
  filters: {},
  sortField: 'priority_score',
  sortDirection: 'desc',
  isLoading: false,
  error: null,
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

function kanbanReducer(state: KanbanState, action: KanbanAction): KanbanState {
  switch (action.type) {
    case 'SET_STAGES':
      return { ...state, stages: action.stages }
    case 'SET_DEALS_FOR_STAGE': {
      const { stageName, deals } = action
      return {
        ...state,
        dealsByStage: { ...state.dealsByStage, [stageName]: deals },
      }
    }
    case 'MOVE_DEAL': {
      const { dealId, fromStage, toStage } = action
      const fromDeals = (state.dealsByStage[fromStage] ?? []).filter(
        (d) => d.id !== dealId
      )
      const movedDeal = (state.dealsByStage[fromStage] ?? []).find(
        (d) => d.id === dealId
      )
      const toDeals = movedDeal
        ? [
            ...(state.dealsByStage[toStage] ?? []),
            { ...movedDeal, status: toStage },
          ]
        : state.dealsByStage[toStage] ?? []

      return {
        ...state,
        dealsByStage: {
          ...state.dealsByStage,
          [fromStage]: fromDeals,
          [toStage]: toDeals,
        },
      }
    }
    case 'SET_FILTERS':
      return { ...state, filters: action.filters }
    case 'SET_SORT':
      return {
        ...state,
        sortField: action.field,
        sortDirection: action.direction,
      }
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

interface DealKanbanContextValue {
  state: KanbanState
  moveDeal: (dealId: number, fromStage: string, toStage: string) => void
  setFilters: (filters: KanbanFilters) => void
  setSort: (field: KanbanSortField, direction: 'asc' | 'desc') => void
  refetchAll: () => void
  isLoading: boolean
  error: string | null
}

const DealKanbanContext = createContext<DealKanbanContextValue | null>(null)

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function DealKanbanProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(kanbanReducer, initialState)
  const queryClient = useQueryClient()

  // Fetch pipeline stages
  const {
    data: stages,
    isError: stagesError,
    error: stagesErrorObj,
  } = useQuery({
    queryKey: ['pipeline-stages'],
    queryFn: () => pipelineConfigService.getStages(),
    staleTime: 5 * 60 * 1000,
  })

  // When stages load, store them and fetch deals for each stage
  const stageNames = useMemo(() => stages?.map((s) => s.stage_name) ?? [], [stages])

  // Fetch deals for each stage individually
  useQuery({
    queryKey: ['kanban-deals', stageNames],
    queryFn: async () => {
      if (stageNames.length === 0) return {}
      const results = await Promise.all(
        stageNames.map(async (name) => {
          try {
            const deals = await multifamilyService.listDealsByStatus(name)
            return { stageName: name, deals }
          } catch {
            return { stageName: name, deals: [] }
          }
        })
      )
      const dealsByStage: Record<string, DealKanbanCard[]> = {}
      for (const { stageName, deals } of results) {
        dealsByStage[stageName] = deals
      }
      return dealsByStage
    },
    onSuccess: (dealsByStage) => {
      if (stages) dispatch({ type: 'SET_STAGES', stages })
      if (dealsByStage) {
        for (const [stageName, deals] of Object.entries(dealsByStage)) {
          dispatch({ type: 'SET_DEALS_FOR_STAGE', stageName, deals })
        }
      }
    },
    onError: (err: Error) => {
      dispatch({ type: 'SET_ERROR', error: err.message })
    },
    enabled: stageNames.length > 0,
    staleTime: 30 * 1000,
  })

  // Handle stages load separately
  if (stages && state.stages.length === 0) {
    dispatch({ type: 'SET_STAGES', stages })
  }

  // Move deal mutation
  const moveMutation = useMutation({
    mutationFn: ({
      dealId,
      newStatus,
    }: {
      dealId: number
      newStatus: string
    }) => multifamilyService.updateDeal(dealId, { status: newStatus }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kanban-deals'] })
    },
  })

  const moveDeal = useCallback(
    (dealId: number, fromStage: string, toStage: string) => {
      // Optimistic update
      dispatch({ type: 'MOVE_DEAL', dealId, fromStage, toStage })
      // Fire mutation
      moveMutation.mutate({ dealId, newStatus: toStage })
    },
    [moveMutation]
  )

  const setFilters = useCallback((filters: KanbanFilters) => {
    dispatch({ type: 'SET_FILTERS', filters })
  }, [])

  const setSort = useCallback(
    (field: KanbanSortField, direction: 'asc' | 'desc') => {
      dispatch({ type: 'SET_SORT', field, direction })
    },
    []
  )

  const refetchAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['pipeline-stages'] })
    queryClient.invalidateQueries({ queryKey: ['kanban-deals'] })
  }, [queryClient])

  const value = useMemo<DealKanbanContextValue>(
    () => ({
      state,
      moveDeal,
      setFilters,
      setSort,
      refetchAll,
      isLoading: moveMutation.isPending,
      error: stagesError ? (stagesErrorObj as Error)?.message ?? 'Failed to load stages' : state.error,
    }),
    [state, moveDeal, setFilters, setSort, refetchAll, moveMutation.isPending, stagesError, stagesErrorObj]
  )

  return (
    <DealKanbanContext.Provider value={value}>
      {children}
    </DealKanbanContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useDealKanban(): DealKanbanContextValue {
  const ctx = useContext(DealKanbanContext)
  if (!ctx) {
    throw new Error('useDealKanban must be used within a DealKanbanProvider')
  }
  return ctx
}

export default DealKanbanContext
