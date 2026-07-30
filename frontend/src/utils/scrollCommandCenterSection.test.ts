import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { scrollCommandCenterSectionIntoView } from './scrollCommandCenterSection'

describe('scrollCommandCenterSectionIntoView', () => {
  const originalScrollTo = window.scrollTo

  beforeEach(() => {
    window.scrollTo = vi.fn() as unknown as typeof window.scrollTo
    Object.defineProperty(window, 'scrollY', { value: 200, configurable: true })
  })

  afterEach(() => {
    window.scrollTo = originalScrollTo
    document.body.innerHTML = ''
  })

  it('noops when the section is missing', () => {
    scrollCommandCenterSectionIntoView('building-ownership-section')
    expect(window.scrollTo).not.toHaveBeenCalled()
  })

  it('offsets by sticky chrome height so the section top is visible', () => {
    const sticky = document.createElement('div')
    sticky.setAttribute('data-testid', 'cc-sticky-chrome')
    Object.defineProperty(sticky, 'offsetHeight', { value: 120 })
    document.body.appendChild(sticky)

    const section = document.createElement('div')
    section.id = 'building-ownership-section'
    section.getBoundingClientRect = () =>
      ({
        top: 800,
        bottom: 1200,
        left: 0,
        right: 0,
        width: 0,
        height: 400,
        x: 0,
        y: 800,
        toJSON: () => ({}),
      }) as DOMRect
    document.body.appendChild(section)

    scrollCommandCenterSectionIntoView('building-ownership-section')

    // 800 (rect.top) + 200 (scrollY) - 120 (sticky) - 8 (pad) = 872
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 872, behavior: 'smooth' })
  })
})
