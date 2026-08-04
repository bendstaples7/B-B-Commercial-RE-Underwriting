/**
 * Smoke: live-UI metrics helper marks children clipped outside root.
 */
import { describe, expect, it } from 'vitest'
import { collectLiveUiMetrics } from './liveUiCapture'

describe('collectLiveUiMetrics', () => {
  it('reports missing selector', () => {
    const m = collectLiveUiMetrics('[data-testid="does-not-exist-xyz"]')
    expect(m.ok).toBe(false)
  })

  it('detects clipped child testids', () => {
    const root = document.createElement('div')
    root.setAttribute('data-testid', 'live-ui-root')
    Object.defineProperty(root, 'getBoundingClientRect', {
      value: () => ({ left: 0, right: 100, top: 0, bottom: 40, width: 100, height: 40 }),
    })

    const child = document.createElement('div')
    child.setAttribute('data-testid', 'clipped-child')
    Object.defineProperty(child, 'getBoundingClientRect', {
      value: () => ({ left: 90, right: 140, top: 0, bottom: 20, width: 50, height: 20 }),
    })
    root.appendChild(child)
    document.body.appendChild(root)

    const m = collectLiveUiMetrics('[data-testid="live-ui-root"]') as {
      ok: boolean
      clippedCount: number
      clippedTestIds: string[]
    }
    expect(m.ok).toBe(true)
    expect(m.clippedCount).toBe(1)
    expect(m.clippedTestIds).toContain('clipped-child')

    root.remove()
  })
})
