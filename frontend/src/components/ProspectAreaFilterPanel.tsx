/**
 * Map-drawn geographic filter for Prospect Review (display only).
 * Uses native Polygon/Rectangle shapes — Google removed DrawingManager in Maps API 3.65+.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  ButtonGroup,
  CircularProgress,
  FormControlLabel,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { GoogleMap, Polygon } from '@react-google-maps/api'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { prospectService } from '@/services/api'
import type { ProspectAreaFilterConfig, ProspectAreaFilterStats } from '@/types'

const CHICAGO_CENTER = { lat: 41.8781, lng: -87.6298 }
const MAP_STYLE = { width: '100%', height: 320 }
const SHAPE_STYLE = {
  fillColor: '#1976d2',
  fillOpacity: 0.15,
  strokeColor: '#1976d2',
  strokeWeight: 2,
}

type LatLng = { lat: number; lng: number }
type DrawMode = 'none' | 'rectangle' | 'polygon'

function pathsFromGeometry(geometry: ProspectAreaFilterConfig['geometry']): LatLng[] {
  if (!geometry || geometry.type !== 'Polygon' || !geometry.coordinates?.[0]) {
    return []
  }
  const ring = geometry.coordinates[0]
  const paths = ring.map(([lng, lat]) => ({ lat, lng }))
  if (paths.length > 1) {
    const first = paths[0]
    const last = paths[paths.length - 1]
    if (first.lat === last.lat && first.lng === last.lng) {
      return paths.slice(0, -1)
    }
  }
  return paths
}

function geometryFromLatLngs(points: LatLng[]): ProspectAreaFilterConfig['geometry'] {
  if (points.length < 3) return null
  const coordinates = points.map((pt) => [pt.lng, pt.lat])
  const first = coordinates[0]
  const last = coordinates[coordinates.length - 1]
  if (first[0] !== last[0] || first[1] !== last[1]) {
    coordinates.push([...first])
  }
  return { type: 'Polygon', coordinates: [coordinates] }
}

function geometryFromRectangle(bounds: google.maps.LatLngBounds): ProspectAreaFilterConfig['geometry'] {
  const ne = bounds.getNorthEast()
  const sw = bounds.getSouthWest()
  return geometryFromLatLngs([
    { lat: sw.lat(), lng: sw.lng() },
    { lat: sw.lat(), lng: ne.lng() },
    { lat: ne.lat(), lng: ne.lng() },
    { lat: ne.lat(), lng: sw.lng() },
  ])
}

function removeListeners(listeners: google.maps.MapsEventListener[]) {
  listeners.forEach((listener) => google.maps.event.removeListener(listener))
}

interface ProspectAreaFilterPanelProps {
  mapsLoaded: boolean
  config: ProspectAreaFilterConfig | undefined
  filterStats?: ProspectAreaFilterStats
  onChanged?: () => void
}

export function ProspectAreaFilterPanel({
  mapsLoaded,
  config,
  filterStats,
  onChanged,
}: ProspectAreaFilterPanelProps) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(Boolean(config?.enabled || config?.geometry))
  const [enabled, setEnabled] = useState(Boolean(config?.enabled))
  const [label, setLabel] = useState(config?.label ?? '')
  const [draftGeometry, setDraftGeometry] = useState<ProspectAreaFilterConfig['geometry']>(
    config?.geometry ?? null,
  )
  const [drawMode, setDrawMode] = useState<DrawMode>('none')
  const [polygonPointCount, setPolygonPointCount] = useState(0)

  const mapRef = useRef<google.maps.Map | null>(null)
  const drawListenersRef = useRef<google.maps.MapsEventListener[]>([])
  const previewOverlayRef = useRef<google.maps.Rectangle | google.maps.Polygon | null>(null)
  const rectangleStartRef = useRef<google.maps.LatLng | null>(null)
  const polygonPointsRef = useRef<google.maps.LatLng[]>([])

  useEffect(() => {
    setEnabled(Boolean(config?.enabled))
    setLabel(config?.label ?? '')
    setDraftGeometry(config?.geometry ?? null)
    if (config?.enabled || config?.geometry) {
      setExpanded(true)
    }
  }, [config])

  const savedPaths = useMemo(() => pathsFromGeometry(draftGeometry), [draftGeometry])

  const clearPreview = useCallback(() => {
    previewOverlayRef.current?.setMap?.(null)
    previewOverlayRef.current = null
    rectangleStartRef.current = null
    polygonPointsRef.current = []
    setPolygonPointCount(0)
  }, [])

  const stopDrawing = useCallback(() => {
    removeListeners(drawListenersRef.current)
    drawListenersRef.current = []
    clearPreview()
    setDrawMode('none')
    const map = mapRef.current
    if (map) {
      map.setOptions({ draggable: true, draggableCursor: undefined })
    }
  }, [clearPreview])

  const triggerMapResize = useCallback(() => {
    const map = mapRef.current
    if (!map || typeof google === 'undefined') return
    google.maps.event.trigger(map, 'resize')
    map.setCenter(savedPaths[0] ?? CHICAGO_CENTER)
  }, [savedPaths])

  const onMapLoad = useCallback(
    (map: google.maps.Map) => {
      mapRef.current = map
      window.setTimeout(triggerMapResize, 0)
    },
    [triggerMapResize],
  )

  useEffect(() => {
    if (!expanded || !mapsLoaded) return
    const id = window.setTimeout(triggerMapResize, 150)
    return () => window.clearTimeout(id)
  }, [expanded, mapsLoaded, triggerMapResize])

  useEffect(() => () => stopDrawing(), [stopDrawing])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapsLoaded || drawMode === 'none') {
      return undefined
    }

    removeListeners(drawListenersRef.current)
    drawListenersRef.current = []
    clearPreview()
    map.setOptions({ draggable: drawMode !== 'rectangle', draggableCursor: 'crosshair' })

    if (drawMode === 'rectangle') {
      const onMouseDown = map.addListener('mousedown', (event: google.maps.MapMouseEvent) => {
        if (!event.latLng) return
        rectangleStartRef.current = event.latLng
        previewOverlayRef.current?.setMap?.(null)
        previewOverlayRef.current = new google.maps.Rectangle({
          map,
          bounds: new google.maps.LatLngBounds(event.latLng, event.latLng),
          ...SHAPE_STYLE,
          clickable: false,
        })
      })

      const onMouseMove = map.addListener('mousemove', (event: google.maps.MapMouseEvent) => {
        const start = rectangleStartRef.current
        const preview = previewOverlayRef.current as google.maps.Rectangle | null
        if (!start || !preview || !event.latLng) return
        preview.setBounds(new google.maps.LatLngBounds(start, event.latLng))
      })

      const onMouseUp = map.addListener('mouseup', (event: google.maps.MapMouseEvent) => {
        const start = rectangleStartRef.current
        const preview = previewOverlayRef.current as google.maps.Rectangle | null
        if (!start || !preview || !event.latLng) return
        const bounds = new google.maps.LatLngBounds(start, event.latLng)
        preview.setBounds(bounds)
        const ne = bounds.getNorthEast()
        const sw = bounds.getSouthWest()
        if (Math.abs(ne.lat() - sw.lat()) > 0.0001 && Math.abs(ne.lng() - sw.lng()) > 0.0001) {
          setDraftGeometry(geometryFromRectangle(bounds))
        }
        stopDrawing()
      })

      drawListenersRef.current = [onMouseDown, onMouseMove, onMouseUp]
    }

    if (drawMode === 'polygon') {
      const onClick = map.addListener('click', (event: google.maps.MapMouseEvent) => {
        if (!event.latLng) return
        polygonPointsRef.current = [...polygonPointsRef.current, event.latLng]
        setPolygonPointCount(polygonPointsRef.current.length)
        if (!previewOverlayRef.current) {
          previewOverlayRef.current = new google.maps.Polygon({
            map,
            paths: polygonPointsRef.current,
            ...SHAPE_STYLE,
            clickable: false,
          })
        } else {
          ;(previewOverlayRef.current as google.maps.Polygon).setPath(polygonPointsRef.current)
        }
      })
      drawListenersRef.current = [onClick]
    }

    return () => {
      removeListeners(drawListenersRef.current)
      drawListenersRef.current = []
      map.setOptions({ draggable: true, draggableCursor: undefined })
    }
  }, [clearPreview, drawMode, mapsLoaded, stopDrawing])

  const finishPolygon = useCallback(() => {
    const points = polygonPointsRef.current.map((pt) => ({ lat: pt.lat(), lng: pt.lng() }))
    if (points.length >= 3) {
      setDraftGeometry(geometryFromLatLngs(points))
    }
    stopDrawing()
  }, [stopDrawing])

  const resolveGeometryForSave = useCallback((): ProspectAreaFilterConfig['geometry'] => {
    const points = polygonPointsRef.current.map((pt) => ({ lat: pt.lat(), lng: pt.lng() }))
    if (points.length >= 3) {
      return geometryFromLatLngs(points)
    }
    if (draftGeometry) return draftGeometry
    return null
  }, [draftGeometry])

  const canSave = Boolean(draftGeometry) || polygonPointCount >= 3

  const saveMutation = useMutation({
    mutationFn: (payload: {
      enabled: boolean
      geometry: NonNullable<ProspectAreaFilterConfig['geometry']>
      label: string | null
    }) => prospectService.saveAreaFilter(payload),
    onSuccess: (data) => {
      setEnabled(Boolean(data.enabled))
      setDraftGeometry(data.geometry)
      queryClient.invalidateQueries({ queryKey: ['prospect-area-filter'] })
      queryClient.invalidateQueries({ queryKey: ['prospect-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
      onChanged?.()
    },
  })

  const handleSave = () => {
    const geometry = resolveGeometryForSave()
    if (!geometry) return
    setDraftGeometry(geometry)
    stopDrawing()
    saveMutation.mutate({
      enabled,
      geometry,
      label: label.trim() || null,
    })
  }

  const saveErrorMessage =
    saveMutation.error instanceof Error
      ? saveMutation.error.message
      : 'Failed to save area. Try again.'

  const clearMutation = useMutation({
    mutationFn: () => prospectService.saveAreaFilter({ enabled: false, clear: true }),
    onSuccess: () => {
      setEnabled(false)
      setDraftGeometry(null)
      stopDrawing()
      queryClient.invalidateQueries({ queryKey: ['prospect-area-filter'] })
      queryClient.invalidateQueries({ queryKey: ['prospect-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
      onChanged?.()
    },
  })

  const summary =
    filterStats?.filter_enabled && filterStats.total_unfiltered > 0
      ? `Showing ${filterStats.total_filtered} of ${filterStats.total_unfiltered} prospects in your area`
      : null

  return (
    <Box sx={{ mb: 2 }}>
      <Button size="small" onClick={() => setExpanded((v) => !v)} sx={{ mb: 1 }}>
        {expanded ? 'Hide target area' : 'Target area (optional)'}
      </Button>
      {expanded && (
        <Box
          data-testid="prospect-area-filter-panel"
          sx={{
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 1,
            p: 2,
            bgcolor: 'background.paper',
          }}
        >
          <Typography variant="subtitle2" gutterBottom>
            Draw a rectangle or polygon to filter Prospect Review
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Sync still pulls all qualifying prospects. When enabled, only properties inside your
            shape appear in this queue and the sidebar badge.
          </Typography>

          <FormControlLabel
            control={
              <Switch
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                data-testid="prospect-area-filter-enabled"
              />
            }
            label="Filter to my area"
          />

          <TextField
            size="small"
            label="Area label (optional)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            sx={{ display: 'block', mb: 1.5, maxWidth: 320 }}
          />

          {!mapsLoaded ? (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                py: 4,
                justifyContent: 'center',
                minHeight: 320,
              }}
            >
              <CircularProgress size={24} />
              <Typography variant="body2" color="text.secondary">Loading map…</Typography>
            </Box>
          ) : (
            <>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1, alignItems: 'center' }}>
                <ButtonGroup size="small" variant="outlined">
                  <Button
                    variant={drawMode === 'rectangle' ? 'contained' : 'outlined'}
                    onClick={() => setDrawMode((mode) => (mode === 'rectangle' ? 'none' : 'rectangle'))}
                    data-testid="prospect-area-draw-rectangle"
                  >
                    Draw rectangle
                  </Button>
                  <Button
                    variant={drawMode === 'polygon' ? 'contained' : 'outlined'}
                    onClick={() => setDrawMode((mode) => (mode === 'polygon' ? 'none' : 'polygon'))}
                    data-testid="prospect-area-draw-polygon"
                  >
                    Draw polygon
                  </Button>
                </ButtonGroup>
                {drawMode === 'rectangle' && (
                  <Typography variant="caption" color="text.secondary">
                    Click and drag on the map to draw a rectangle.
                  </Typography>
                )}
                {drawMode === 'polygon' && (
                  <>
                    <Typography variant="caption" color="text.secondary">
                      Click map corners ({polygonPointCount} points). Save area works once you have at least 3.
                    </Typography>
                    <Button
                      size="small"
                      variant="contained"
                      disabled={polygonPointCount < 3}
                      onClick={finishPolygon}
                      data-testid="prospect-area-finish-polygon"
                    >
                      Finish polygon
                    </Button>
                    <Button size="small" onClick={stopDrawing}>
                      Cancel
                    </Button>
                  </>
                )}
              </Box>

              <Box sx={{ width: '100%', height: 320, minHeight: 320 }}>
                <GoogleMap
                  mapContainerStyle={MAP_STYLE}
                  center={savedPaths[0] ?? CHICAGO_CENTER}
                  zoom={11}
                  onLoad={onMapLoad}
                  options={{ mapTypeControl: false, streetViewControl: false }}
                >
                  {savedPaths.length >= 3 && drawMode === 'none' && (
                    <Polygon
                      paths={savedPaths}
                      options={{
                        fillColor: '#1976d2',
                        fillOpacity: 0.12,
                        strokeColor: '#1565c0',
                        strokeWeight: 2,
                      }}
                    />
                  )}
                </GoogleMap>
              </Box>
            </>
          )}

          <Box sx={{ display: 'flex', gap: 1, mt: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
            <Button
              variant="contained"
              size="small"
              disabled={saveMutation.isPending || !canSave}
              onClick={handleSave}
              data-testid="prospect-area-save"
            >
              {saveMutation.isPending ? 'Saving…' : 'Save area'}
            </Button>
            <Button
              variant="outlined"
              size="small"
              color="inherit"
              disabled={clearMutation.isPending}
              onClick={() => clearMutation.mutate()}
            >
              Clear area
            </Button>
            {summary && filterStats && (
              <Typography variant="body2" color="text.secondary" data-testid="prospect-area-filter-summary">
                {summary}
                {filterStats.hidden_outside_area > 0
                  ? ` (${filterStats.hidden_outside_area} outside area)`
                  : ''}
                {filterStats.hidden_no_coords > 0
                  ? ` (${filterStats.hidden_no_coords} missing map coordinates)`
                  : ''}
              </Typography>
            )}
          </Box>

          {saveMutation.isSuccess && (
            <Alert severity="success" sx={{ mt: 1.5 }} data-testid="prospect-area-save-success">
              Area saved and filter enabled. The queue below shows only prospects inside your shape.
            </Alert>
          )}
          {saveMutation.isError && (
            <Alert severity="error" sx={{ mt: 1.5 }} data-testid="prospect-area-save-error">
              {saveErrorMessage}
            </Alert>
          )}
        </Box>
      )}
    </Box>
  )
}
