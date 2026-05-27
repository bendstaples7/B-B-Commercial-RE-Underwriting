/**
 * Bug Condition Exploration Tests — Task 1 (Polling Optimization Bugfix)
 *
 * **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**
 *
 * These tests encode the EXPECTED (fixed) behavior.
 * On UNFIXED code they are expected to FAIL — failure confirms the bugs exist.
 * On FIXED code they should PASS — confirming the bugs are resolved.
 *
 * Sub-property A — PipelineStatusContext unconditional poll
 * Sub-property B — HubSpotImportArea duplicate poll
 * Sub-property C — App.tsx duplicate queue counts poll
 * Sub-property D — Queue page background poll
 *
 * Testing approach:
 * - Sub-property A: Timer-based test (8s interval is manageable with fake timers)
 * - Sub-properties B, C, D: Source code inspection (static analysis)
 *   The source inspection approach is reliable and directly encodes the property.
 *   It fails on unfixed code (source doesn't have the fix) and passes on fixed code.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@/test/testUtils'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as fs from 'fs'
import * as path from 'path'

// ---------------------------------------------------------------------------
// Top-level mocks (Vitest requires vi.mock at module scope)
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  hubSpotService: {
    getPipelineStatus: vi.fn(),
    getHubSpotConfig: vi.fn(),
    listImportRuns: vi.fn(),
    getReviewQueue: vi.fn(),
    saveHubSpotConfig: vi.fn(),
    testHubSpotConnection: vi.fn(),
    triggerHubSpotImport: vi.fn(),
    triggerBackupExport: vi.fn(),
    downloadBackupExport: vi.fn(),
    confirmMatch: vi.fn(),
    rejectMatch: vi.fn(),
    markMatchAsNewRecord: vi.fn(),
  },
  queueService: {
    getCounts: vi.fn(),
    getTodaysAction: vi.fn(),
  },
  callLogService: {
    logCall: vi.fn(),
    logNote: vi.fn(),
  },
  leadTaskService: {
    createTask: vi.fn(),
  },
}))

vi.mock('@/components/WebhookSyncPanel', () => ({
  WebhookSyncPanel: () => <div data-testid="webhook-sync-panel" />,
}))

// ---------------------------------------------------------------------------
// Imports after mocks
// ---------------------------------------------------------------------------

import { hubSpotService, queueService } from '@/services/api'
import { PipelineStatusProvider } from '@/context/PipelineStatusContext'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
}

const defaultPipelineStatus = {
  pipeline_running: false,
  matches: { total: 0, high: 0, medium: 0, unmatched: 0 },
  interactions: 0,
  tasks: 0,
  signals: 0,
}

const defaultQueueCounts = {
  todays_action: 0,
  previously_warm: 0,
  follow_up_overdue: 0,
  no_next_action: 0,
  needs_review: 0,
  do_not_contact: 0,
  missing_property_match: 0,
}

// Source file paths for static analysis
const COMPONENTS_DIR = path.resolve(__dirname)
const CONTEXT_DIR = path.resolve(__dirname, '../context')

function readSource(filename: string): string {
  return fs.readFileSync(path.join(COMPONENTS_DIR, filename), 'utf-8')
}

function readContextSource(filename: string): string {
  return fs.readFileSync(path.join(CONTEXT_DIR, filename), 'utf-8')
}

// ---------------------------------------------------------------------------
// Sub-property A — PipelineStatusContext unconditional poll
// ---------------------------------------------------------------------------

describe('Sub-property A — PipelineStatusContext unconditional poll', () => {
  /**
   * Property: For any PipelineStatus where pipeline_running is false,
   * the refetchInterval function must return false (no polling).
   *
   * On unfixed code: refetchInterval is the fixed number 8000, so it always
   * fires regardless of pipeline_running. Over 24 seconds, 3 fetches occur.
   *
   * On fixed code: refetchInterval is a function that returns false when
   * pipeline_running is false, so only 1 fetch occurs (the initial fetch).
   */

  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(hubSpotService.getPipelineStatus).mockResolvedValue(defaultPipelineStatus)
    vi.mocked(queueService.getCounts).mockResolvedValue(defaultQueueCounts)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('should call getPipelineStatus exactly 1 time when pipeline_running is false over 24 seconds', async () => {
    /**
     * Mount PipelineStatusProvider with pipeline_running: false.
     * Advance fake timers 24 seconds (3 × 8s intervals on unfixed code).
     * Assert fetch is called exactly 1 time (initial fetch only).
     *
     * On UNFIXED code: 3 calls observed (fires every 8s unconditionally) — FAILS.
     * On FIXED code: 1 call (initial fetch, then interval stops) — PASSES.
     */
    const queryClient = makeQueryClient()

    render(
      <QueryClientProvider client={queryClient}>
        <PipelineStatusProvider>
          <div data-testid="child">child</div>
        </PipelineStatusProvider>
      </QueryClientProvider>
    )

    // Wait for initial fetch to complete
    await act(async () => {
      await vi.runAllTimersAsync()
    })

    // Advance 24 seconds (covers 3 × 8s intervals)
    await act(async () => {
      vi.advanceTimersByTime(24_000)
      await vi.runAllTimersAsync()
    })

    const totalCalls = vi.mocked(hubSpotService.getPipelineStatus).mock.calls.length

    // On FIXED code: 1 call (initial fetch only, interval stops because pipeline_running=false)
    // On UNFIXED code: 3+ calls (fires every 8s unconditionally)
    expect(totalCalls).toBe(1)
  })

  it('property: PipelineStatusContext source must use a function for refetchInterval, not a fixed number', () => {
    /**
     * Static analysis: inspect PipelineStatusContext.tsx source.
     *
     * On UNFIXED code: source contains 'refetchInterval: 8000' (fixed number) — FAILS.
     * On FIXED code: source contains 'refetchInterval: (query)' (function) — PASSES.
     *
     * The property: for any PipelineStatus where pipeline_running is false,
     * refetchInterval must return false. This is only possible if refetchInterval
     * is a function, not a fixed number.
     */
    const source = readContextSource('PipelineStatusContext.tsx')

    // On UNFIXED code: this line exists — the test FAILS because we assert it must NOT exist
    const hasFixedNumber = /refetchInterval:\s*8000/.test(source)

    // On FIXED code: refetchInterval is a function, not a bare number
    // On UNFIXED code: refetchInterval is 8000 — this assertion FAILS
    expect(hasFixedNumber).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Sub-property B — HubSpotImportArea duplicate poll
// ---------------------------------------------------------------------------

describe('Sub-property B — HubSpotImportArea duplicate poll', () => {
  /**
   * Property: HubSpotImportArea must NOT register its own useQuery for
   * pipeline status with a refetchInterval. It must consume from context.
   *
   * On unfixed code: HubSpotImportArea has:
   *   useQuery({ queryKey: ['hubspot', 'pipeline', 'status'], refetchInterval: 8000 })
   * This is a duplicate of PipelineStatusContext's query, causing 2 requests per cycle.
   *
   * On fixed code: HubSpotImportArea uses usePipelineStatus() from context,
   * so only PipelineStatusContext's single query fires.
   */

  it('property: HubSpotImportArea source must NOT contain a useQuery for pipeline status with refetchInterval', () => {
    /**
     * Static analysis: inspect HubSpotImportArea.tsx source.
     *
     * On UNFIXED code: source contains both:
     *   queryKey: ['hubspot', 'pipeline', 'status']
     *   refetchInterval: 8000
     * in the same useQuery block — FAILS.
     *
     * On FIXED code: the duplicate useQuery is removed and replaced with
     * usePipelineStatus() from context — PASSES.
     */
    const source = readSource('HubSpotImportArea.tsx')

    // Check if HubSpotImportArea has a useQuery for pipeline status with refetchInterval
    // The bug pattern: useQuery with queryKey containing 'pipeline' and 'status'
    // AND a refetchInterval in the same component
    const hasDuplicatePipelineQuery = (
      /queryKey:\s*\[['"]hubspot['"],\s*['"]pipeline['"],\s*['"]status['"]\]/.test(source) &&
      /refetchInterval:\s*8000/.test(source)
    )

    // On UNFIXED code: both patterns exist — hasDuplicatePipelineQuery is true — FAILS
    // On FIXED code: the duplicate query is removed — hasDuplicatePipelineQuery is false — PASSES
    expect(hasDuplicatePipelineQuery).toBe(false)
  })

  it('property: HubSpotImportArea source must import or use usePipelineStatus from context', () => {
    /**
     * On FIXED code: HubSpotImportArea uses usePipelineStatus() from context.
     * On UNFIXED code: it uses its own useQuery — FAILS.
     */
    const source = readSource('HubSpotImportArea.tsx')

    // On FIXED code: source imports usePipelineStatus
    const usesContextHook = source.includes('usePipelineStatus')

    // On UNFIXED code: usePipelineStatus is not used — FAILS
    expect(usesContextHook).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Sub-property C — App.tsx duplicate queue counts poll
// ---------------------------------------------------------------------------

describe('Sub-property C — App.tsx duplicate queue counts poll', () => {
  /**
   * Property: App.tsx must NOT register a useQuery with refetchInterval for
   * ['queue-counts']. Only QueueSidebar should own this query.
   *
   * On unfixed code: App.tsx has:
   *   useQuery({ queryKey: ['queue-counts'], refetchInterval: 60_000 })
   * This is a duplicate of QueueSidebar's query.
   *
   * On fixed code: App.tsx reads from cache via getQueryData (no polling).
   */

  it('property: App.tsx source must NOT contain a useQuery with refetchInterval for queue-counts', () => {
    /**
     * Static analysis: inspect App.tsx source.
     *
     * On UNFIXED code: source contains:
     *   queryKey: ['queue-counts']
     *   refetchInterval: 60_000
     * in the same useQuery block — FAILS.
     *
     * On FIXED code: the duplicate useQuery is replaced with getQueryData — PASSES.
     */
    const appSource = fs.readFileSync(
      path.resolve(__dirname, '../App.tsx'),
      'utf-8'
    )

    // Check if App.tsx has a useQuery for queue-counts with refetchInterval
    const hasQueueCountsWithInterval = (
      /queryKey:\s*\[['"]queue-counts['"]\]/.test(appSource) &&
      /refetchInterval:\s*60_000/.test(appSource)
    )

    // On UNFIXED code: both patterns exist — FAILS
    // On FIXED code: the duplicate query is removed — PASSES
    expect(hasQueueCountsWithInterval).toBe(false)
  })

  it('property: QueueSidebar source must use refetchInterval of 5 minutes (5 * 60_000), not 60 seconds', () => {
    /**
     * Static analysis: inspect QueueSidebar.tsx source.
     *
     * On UNFIXED code: source contains 'refetchInterval: 60_000' — FAILS.
     * On FIXED code: source contains 'refetchInterval: 5 * 60_000' — PASSES.
     *
     * The design specifies QueueSidebar should use 5 minutes as the single
     * owner of the queue-counts query.
     */
    const source = readSource('QueueSidebar.tsx')

    // On UNFIXED code: uses 60_000 (60 seconds) — FAILS
    const hasShortInterval = /refetchInterval:\s*60_000/.test(source)

    // On FIXED code: uses 5 * 60_000 (5 minutes)
    // On UNFIXED code: uses 60_000 — this assertion FAILS
    expect(hasShortInterval).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Sub-property D — Queue page background poll
// ---------------------------------------------------------------------------

describe('Sub-property D — Queue page background poll', () => {
  /**
   * Property: Queue page components must have refetchIntervalInBackground: false
   * so polling pauses when the browser tab is hidden.
   *
   * On unfixed code: TodaysActionQueue uses refetchInterval: 60_000 with no
   * refetchIntervalInBackground: false guard. React Query fires the interval
   * even when the tab is hidden.
   *
   * On fixed code: refetchIntervalInBackground: false is added, so React Query
   * pauses the interval when document.visibilityState === 'hidden'.
   */

  it('property: TodaysActionQueue source must contain refetchIntervalInBackground: false', () => {
    /**
     * Static analysis: inspect TodaysActionQueue.tsx source.
     *
     * On UNFIXED code: source does NOT contain 'refetchIntervalInBackground: false' — FAILS.
     * On FIXED code: source contains 'refetchIntervalInBackground: false' — PASSES.
     */
    const source = readSource('TodaysActionQueue.tsx')

    // On FIXED code: source contains this option
    // On UNFIXED code: source does NOT contain this — FAILS
    expect(source).toContain('refetchIntervalInBackground: false')
  })

  it('property: all seven queue page components must have refetchIntervalInBackground: false', () => {
    /**
     * Static analysis: inspect all 7 queue component sources.
     *
     * On UNFIXED code: none of them have refetchIntervalInBackground: false — FAILS.
     * On FIXED code: all of them have it — PASSES.
     */
    const queueComponents = [
      'TodaysActionQueue.tsx',
      'PreviouslyWarmQueue.tsx',
      'FollowUpOverdueQueue.tsx',
      'NoNextActionQueue.tsx',
      'NeedsReviewQueue.tsx',
      'DoNotContactQueue.tsx',
      'MissingPropertyMatchQueue.tsx',
    ]

    const missing: string[] = []

    for (const filename of queueComponents) {
      const source = readSource(filename)
      if (!source.includes('refetchIntervalInBackground: false')) {
        missing.push(filename)
      }
    }

    // On UNFIXED code: all 7 are missing — FAILS with list of missing files
    // On FIXED code: none are missing — PASSES
    expect(missing).toEqual([])
  })

  it('property: QueueSidebar source must contain refetchIntervalInBackground: false', () => {
    /**
     * QueueSidebar is always mounted and owns the queue-counts query.
     * It should also stop polling when the tab is hidden.
     *
     * On UNFIXED code: source does NOT contain 'refetchIntervalInBackground: false' — FAILS.
     * On FIXED code: source contains it — PASSES.
     */
    const source = readSource('QueueSidebar.tsx')

    // On FIXED code: source contains this option
    // On UNFIXED code: source does NOT contain this — FAILS
    expect(source).toContain('refetchIntervalInBackground: false')
  })
})
