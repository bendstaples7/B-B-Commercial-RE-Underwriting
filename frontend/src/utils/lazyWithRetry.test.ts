import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CHUNK_RELOAD_STORAGE_KEY,
  clearChunkReloadGuard,
  importWithRetry,
  isChunkLoadError,
  reloadOnceForStaleChunk,
} from './lazyWithRetry'

describe('isChunkLoadError', () => {
  it('matches Vite / Chrome dynamic import failures', () => {
    expect(
      isChunkLoadError(
        new TypeError(
          'Failed to fetch dynamically imported module: https://example.com/assets/MarketingHub-abc.js',
        ),
      ),
    ).toBe(true)
  })

  it('matches Safari and webpack-style messages', () => {
    expect(isChunkLoadError(new Error('Importing a module script failed.'))).toBe(true)
    expect(isChunkLoadError(new Error('Loading chunk 7 failed.'))).toBe(true)
    expect(isChunkLoadError(new Error('ChunkLoadError: Loading chunk failed'))).toBe(true)
  })

  it('ignores unrelated errors', () => {
    expect(isChunkLoadError(new Error('Cannot read properties of undefined'))).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
  })
})

describe('reloadOnceForStaleChunk', () => {
  const reload = vi.fn()

  beforeEach(() => {
    sessionStorage.clear()
    reload.mockReset()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { reload, href: 'http://localhost/', search: '' },
    })
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  it('reloads once then refuses a second reload', () => {
    expect(reloadOnceForStaleChunk('test')).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem(CHUNK_RELOAD_STORAGE_KEY)).toBe('1')

    expect(reloadOnceForStaleChunk('test')).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })
})

describe('clearChunkReloadGuard', () => {
  it('removes the sessionStorage flag', () => {
    sessionStorage.setItem(CHUNK_RELOAD_STORAGE_KEY, '1')
    clearChunkReloadGuard()
    expect(sessionStorage.getItem(CHUNK_RELOAD_STORAGE_KEY)).toBeNull()
  })
})

describe('importWithRetry', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    sessionStorage.clear()
  })

  it('returns the module on first success and clears the reload guard', async () => {
    sessionStorage.setItem(CHUNK_RELOAD_STORAGE_KEY, '1')
    const mod = { default: () => null }
    await expect(importWithRetry(() => Promise.resolve(mod))).resolves.toBe(mod)
    expect(sessionStorage.getItem(CHUNK_RELOAD_STORAGE_KEY)).toBeNull()
  })

  it('retries a chunk miss then calls onStaleChunk', async () => {
    const err = new TypeError(
      'Failed to fetch dynamically imported module: https://example.com/assets/X.js',
    )
    const factory = vi.fn().mockRejectedValue(err)
    const onStaleChunk = vi.fn().mockReturnValue(true)

    const pending = importWithRetry(factory, {
      retries: 1,
      retryDelayMs: 10,
      onStaleChunk,
    })

    await vi.advanceTimersByTimeAsync(50)
    // Promise stays pending when reload is scheduled
    let settled = false
    void pending.then(
      () => {
        settled = true
      },
      () => {
        settled = true
      },
    )
    await vi.advanceTimersByTimeAsync(0)
    expect(factory).toHaveBeenCalledTimes(2)
    expect(onStaleChunk).toHaveBeenCalledWith('lazy-import')
    expect(settled).toBe(false)
  })

  it('rethrows non-chunk errors without reloading', async () => {
    const err = new Error('boom')
    const onStaleChunk = vi.fn()
    await expect(
      importWithRetry(() => Promise.reject(err), { onStaleChunk }),
    ).rejects.toThrow('boom')
    expect(onStaleChunk).not.toHaveBeenCalled()
  })
})
