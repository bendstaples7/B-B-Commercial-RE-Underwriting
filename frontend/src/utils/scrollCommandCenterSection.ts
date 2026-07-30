/**
 * Scroll a Command Center section so its top sits just below sticky chrome
 * (CC header stack), not under it / mid-section.
 */
export function scrollCommandCenterSectionIntoView(elementId: string): void {
  const el = document.getElementById(elementId)
  if (!el) return

  const sticky = document.querySelector(
    '[data-testid="cc-sticky-chrome"]',
  ) as HTMLElement | null
  const offset = (sticky?.offsetHeight ?? 0) + 8
  const top = el.getBoundingClientRect().top + window.scrollY - offset
  window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
}
