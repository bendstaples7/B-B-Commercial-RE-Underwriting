import { createContext, useContext } from 'react'

export const GoogleMapsLoadedContext = createContext(false)
export const useGoogleMapsLoaded = () => useContext(GoogleMapsLoadedContext)
