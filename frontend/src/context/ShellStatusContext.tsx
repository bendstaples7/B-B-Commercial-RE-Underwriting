import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

type ShellStatusContextValue = {
  statusLabel: string | null
  /** Set or clear a label owned by ``owner``. Clear only succeeds for the current owner. */
  setStatusLabel: (owner: string, label: string | null) => void
}

const ShellStatusContext = createContext<ShellStatusContextValue | undefined>(undefined)

export function ShellStatusProvider({ children }: { children: React.ReactNode }) {
  const [statusLabel, setStatusLabelState] = useState<string | null>(null)
  const ownerRef = useRef<string | null>(null)

  const setStatusLabel = useCallback((owner: string, label: string | null) => {
    if (label === null) {
      if (ownerRef.current !== owner) return
      ownerRef.current = null
      setStatusLabelState(null)
      return
    }
    ownerRef.current = owner
    setStatusLabelState(label)
  }, [])

  const value = useMemo(
    () => ({ statusLabel, setStatusLabel }),
    [statusLabel, setStatusLabel],
  )
  return (
    <ShellStatusContext.Provider value={value}>{children}</ShellStatusContext.Provider>
  )
}

export function useShellStatus(): ShellStatusContextValue {
  const ctx = useContext(ShellStatusContext)
  if (!ctx) {
    throw new Error('useShellStatus must be used within ShellStatusProvider')
  }
  return ctx
}
