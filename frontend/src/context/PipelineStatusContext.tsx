/**
 * PipelineStatusContext — global polling for the HubSpot post-import pipeline.
 *
 * Polls GET /api/hubspot/pipeline/status every 8 seconds and exposes the
 * result to any component via usePipelineStatus().
 *
 * The AppBar uses this to show a spinner when pipeline_running is true.
 */
import { createContext, useContext, ReactNode, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { hubSpotService } from '@/services/api'
import { useAuth } from '@/context/AuthContext'

interface PipelineStatus {
  pipeline_running: boolean
  pipeline_stage?: string | null
  pipeline_stage_label?: string | null
  pipeline_stage_index?: number | null
  pipeline_stage_total?: number | null
  matches: { total: number; high: number; medium: number; unmatched: number }
  interactions: number
  tasks: number
  signals: number
}

const PipelineStatusContext = createContext<PipelineStatus | null>(null)
const PIPELINE_STATUS_QUERY_KEY = ['hubspot', 'pipeline', 'status', 'global'] as const

export function usePipelineStatus(): PipelineStatus | null {
  return useContext(PipelineStatusContext)
}

interface PipelineStatusProviderProps {
  children: ReactNode
}

export function PipelineStatusProvider({ children }: PipelineStatusProviderProps) {
  const { user } = useAuth()
  const userKey = user?.user_id ?? user?.email ?? null
  const queryClient = useQueryClient()
  const previousUserKeyRef = useRef<string | null | undefined>(undefined)

  useEffect(() => {
    if (previousUserKeyRef.current === undefined) {
      previousUserKeyRef.current = userKey
      return
    }
    if (previousUserKeyRef.current !== userKey) {
      queryClient.removeQueries({ queryKey: PIPELINE_STATUS_QUERY_KEY })
      previousUserKeyRef.current = userKey
    }
  }, [queryClient, userKey])

  const { data } = useQuery({
    queryKey: [...PIPELINE_STATUS_QUERY_KEY, userKey],
    queryFn: () => hubSpotService.getPipelineStatus(),
    enabled: Boolean(user),
    refetchInterval: (query) => {
      const data = query.state.data as PipelineStatus | undefined
      return data?.pipeline_running ? 8000 : false
    },
    retry: false,
    // Don't throw on error — pipeline status is non-critical
    throwOnError: false,
  })

  return (
    <PipelineStatusContext.Provider value={data ?? null}>
      {children}
    </PipelineStatusContext.Provider>
  )
}
