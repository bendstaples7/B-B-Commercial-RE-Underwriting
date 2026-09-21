import { createContext, useContext } from 'react'

export type GoogleMapsAvailability = 'loading' | 'ready' | 'unavailable'

export const GoogleMapsLoadedContext = createContext(false)
export const useGoogleMapsLoaded = () => useContext(GoogleMapsLoadedContext)

/** Distinguishes "still fetching the key / script" from "no key at all". */
export const GoogleMapsAvailabilityContext = createContext<GoogleMapsAvailability>('loading')
export const useGoogleMapsAvailability = () => useContext(GoogleMapsAvailabilityContext)
