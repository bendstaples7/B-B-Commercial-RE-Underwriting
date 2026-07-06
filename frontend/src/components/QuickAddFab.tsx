/**
 * Quick Add FAB — portaled to document.body so Kanban/DndContext cannot stack above it.
 *
 * Uses visualViewport for positioning because on mobile, layout viewport (innerHeight)
 * can expand to document height while the visual viewport stays screen-sized, which
 * breaks CSS `bottom` anchoring on position:fixed elements.
 */
import { useCallback, useLayoutEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Fab, Portal } from '@mui/material'
import AddLocationAltIcon from '@mui/icons-material/AddLocationAlt'
import { useAuth } from '@/context/AuthContext'

export const FAB_SIZE = 56
export const FAB_MARGIN = 24

function setImportantStyle(el: HTMLElement, prop: string, value: string): void {
  el.style.setProperty(prop, value, 'important')
}

/** Position FAB relative to the visual viewport (falls back to bottom/right). */
export function applyVisualViewportPosition(el: HTMLElement): void {
  const vv = window.visualViewport
  setImportantStyle(el, 'position', 'fixed')
  setImportantStyle(el, 'z-index', '9999')

  if (vv) {
    setImportantStyle(
      el,
      'top',
      `${vv.offsetTop + vv.height - FAB_SIZE - FAB_MARGIN}px`,
    )
    setImportantStyle(
      el,
      'left',
      `${vv.offsetLeft + vv.width - FAB_SIZE - FAB_MARGIN}px`,
    )
    setImportantStyle(el, 'bottom', 'auto')
    setImportantStyle(el, 'right', 'auto')
  } else {
    setImportantStyle(el, 'bottom', `${FAB_MARGIN}px`)
    setImportantStyle(el, 'right', `${FAB_MARGIN}px`)
    setImportantStyle(el, 'top', 'auto')
    setImportantStyle(el, 'left', 'auto')
  }
}

export function QuickAddFabHost() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { user, isLoading } = useAuth()
  const fabNodeRef = useRef<HTMLButtonElement | null>(null)

  const hideReason =
    pathname.startsWith('/quick-add')
      ? 'onQuickAddPage'
      : isLoading || !user
        ? 'noUser'
        : null

  const syncFabPosition = useCallback(() => {
    const el = fabNodeRef.current
    if (el) {
      applyVisualViewportPosition(el)
    }
  }, [])

  const setFabRef = useCallback((node: HTMLButtonElement | null) => {
    fabNodeRef.current = node
    if (node) {
      applyVisualViewportPosition(node)
    }
  }, [])

  useLayoutEffect(() => {
    if (hideReason) return

    syncFabPosition()

    const vv = window.visualViewport
    vv?.addEventListener('resize', syncFabPosition)
    vv?.addEventListener('scroll', syncFabPosition)
    window.addEventListener('resize', syncFabPosition)
    window.addEventListener('scroll', syncFabPosition, { passive: true })

    const ro =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => syncFabPosition())
        : null
    ro?.observe(document.documentElement)

    return () => {
      vv?.removeEventListener('resize', syncFabPosition)
      vv?.removeEventListener('scroll', syncFabPosition)
      window.removeEventListener('resize', syncFabPosition)
      window.removeEventListener('scroll', syncFabPosition)
      ro?.disconnect()
    }
  }, [hideReason, syncFabPosition])

  useLayoutEffect(() => {
    if (hideReason) return
    syncFabPosition()
  }, [hideReason, pathname, syncFabPosition])

  if (hideReason) {
    return null
  }

  return (
    <Portal>
      <Fab
        ref={setFabRef}
        color="primary"
        aria-label="Quick add property"
        data-testid="quick-add-fab"
        onClick={() => navigate('/quick-add')}
        sx={{
          boxShadow: 6,
          pointerEvents: 'auto',
          width: FAB_SIZE,
          height: FAB_SIZE,
        }}
      >
        <AddLocationAltIcon />
      </Fab>
    </Portal>
  )
}

export default QuickAddFabHost
