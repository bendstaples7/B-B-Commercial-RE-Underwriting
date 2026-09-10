import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

/** sessionStorage key — one auto-reload per tab after a deploy chunk miss. */
export const CHUNK_RELOAD_STORAGE_KEY = 'bb.spa.chunk-reload'

const CHUNK_LOAD_ERROR_RE =
  /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk [\d]+ failed|ChunkLoadError|error loading dynamically imported module/i

/**
 * True when a dynamic import failed because the hashed asset is gone
 * (typical after deploy) or the network blipped mid-fetch.
 */
export function isChunkLoadError(error: unknown): boolean {
  if (!error) return false
  const message =
    error instanceof Error
      ? error.message
      : typeof error === 'string'
        ? error
        : String((error as { message?: unknown })?.message ?? error)
  return CHUNK_LOAD_ERROR_RE.test(message)
}

/**
 * Reload once to pick up the current index.html chunk manifest.
 * Returns true if a reload was scheduled.
 */
export function reloadOnceForStaleChunk(reason = 'chunk-load'): boolean {
  if (typeof window === 'undefined') return false
  try {
    if (sessionStorage.getItem(CHUNK_RELOAD_STORAGE_KEY) === '1') {
      return false
    }
    sessionStorage.setItem(CHUNK_RELOAD_STORAGE_KEY, '1')
  } catch {
    // private mode / quota — still attempt a single reload via URL marker
    const url = new URL(window.location.href)
    if (url.searchParams.get('_chunk_reload') === '1') return false
    url.searchParams.set('_chunk_reload', '1')
    window.location.replace(url.toString())
    return true
  }
  console.warn(`[spa] stale or failed chunk (${reason}) — reloading once for fresh assets`)
  window.location.reload()
  return true
}

/** Clear the reload guard after a successful navigation/import. */
export function clearChunkReloadGuard(): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.removeItem(CHUNK_RELOAD_STORAGE_KEY)
  } catch {
    // ignore
  }
  try {
    const url = new URL(window.location.href)
    if (url.searchParams.has('_chunk_reload')) {
      url.searchParams.delete('_chunk_reload')
      window.history.replaceState(window.history.state, '', url.toString())
    }
  } catch {
    // ignore
  }
}

export type ImportWithRetryOptions = {
  retries?: number
  retryDelayMs?: number
  /** Injected for tests — defaults to window.location.reload path. */
  onStaleChunk?: (reason: string) => boolean
}

/**
 * Retry a dynamic import(); on persistent chunk miss, reload once so the
 * browser picks up the post-deploy index.html manifest instead of blanking.
 */
export async function importWithRetry<T>(
  factory: () => Promise<T>,
  options?: ImportWithRetryOptions,
): Promise<T> {
  const retries = options?.retries ?? 1
  const retryDelayMs = options?.retryDelayMs ?? 400
  const onStaleChunk = options?.onStaleChunk ?? reloadOnceForStaleChunk

  let lastError: unknown
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const mod = await factory()
      clearChunkReloadGuard()
      return mod
    } catch (error) {
      lastError = error
      if (!isChunkLoadError(error) || attempt >= retries) break
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs * (attempt + 1)))
    }
  }

  if (isChunkLoadError(lastError) && onStaleChunk('lazy-import')) {
    // Suspend forever while the reload navigates away.
    return new Promise<T>(() => {})
  }
  throw lastError
}

/**
 * React.lazy wrapper: retry transient import failures, then hard-reload once
 * when a hashed chunk 404s after deploy so users are not left on a blank page.
 */
// Match React.lazy's permissive component typing (props vary per route).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyWithRetry<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
  options?: ImportWithRetryOptions,
): LazyExoticComponent<T> {
  return lazy(() => importWithRetry(factory, options))
}

/**
 * Install window-level listeners so uncaught chunk failures (outside React.lazy)
 * still recover with a single reload instead of a blank main pane.
 */
export function installChunkLoadRecovery(): () => void {
  if (typeof window === 'undefined') return () => {}

  const onRejection = (event: PromiseRejectionEvent) => {
    if (!isChunkLoadError(event.reason)) return
    if (reloadOnceForStaleChunk('unhandledrejection')) {
      event.preventDefault()
    }
  }

  const onError = (event: ErrorEvent) => {
    if (!isChunkLoadError(event.error ?? event.message)) return
    if (reloadOnceForStaleChunk('window-error')) {
      event.preventDefault()
    }
  }

  window.addEventListener('unhandledrejection', onRejection)
  window.addEventListener('error', onError)
  return () => {
    window.removeEventListener('unhandledrejection', onRejection)
    window.removeEventListener('error', onError)
  }
}
