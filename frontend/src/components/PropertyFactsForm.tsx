import React, { useState, useEffect, useRef } from 'react'
import {
  Box,
  TextField,
  Button,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableRow,
  Select,
  MenuItem,
  FormControl,
  Alert,
  CircularProgress,
  Chip,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
} from '@mui/material'
import usePlacesAutocomplete, { getGeocode, getLatLng } from 'use-places-autocomplete'
import {
  PropertyFacts,
  PropertyType,
  ConstructionType,
  InteriorCondition,
} from '@/types'
import { useGoogleMapsLoaded } from '@/App'

interface PropertyFactsFormProps {
  propertyFacts?: PropertyFacts
  onSubmit: (facts: PropertyFacts) => void
  onAddressSubmit: (address: string, coords?: { lat: number; lng: number }) => void
  loading?: boolean
  error?: string
  initialAddress?: string
  initialCoords?: { lat: number; lng: number }
}

export const PropertyFactsForm: React.FC<PropertyFactsFormProps> = ({
  propertyFacts,
  onSubmit,
  onAddressSubmit,
  loading = false,
  error,
  initialAddress,
  initialCoords,
}) => {
  const [editedFacts, setEditedFacts] = useState<Partial<PropertyFacts>>({})
  const [showFactsTable, setShowFactsTable] = useState(false)
  const [autocompleteError, setAutocompleteError] = useState<string | null>(null)
  const suggestionsRef = useRef<HTMLUListElement>(null)

  // NOTE: Google Maps script is loaded at the app level (App.tsx) so it's
  // ready before this component mounts. No script injection needed here.

  const mapsLoaded = useGoogleMapsLoaded()

  const {
    ready,
    value,
    suggestions: { status, data },
    setValue,
    clearSuggestions,
    init,
  } = usePlacesAutocomplete({
    requestOptions: {
      componentRestrictions: { country: 'us' },
    },
    debounce: 300,
    initOnMount: false,
  })

  // Initialize the autocomplete service as soon as the Maps API is ready
  useEffect(() => {
    if (mapsLoaded) init()
  }, [mapsLoaded, init])

  // Auto-submit when an address is pre-filled from the New Analysis dialog.
  // Coordinates are passed through when the user selected a Places suggestion.
  useEffect(() => {
    if (initialAddress?.trim()) {
      setValue(initialAddress.trim(), false) // show the address in the input field
      onAddressSubmit(initialAddress.trim(), initialCoords)
    }
    // Only run on mount — intentionally omitting deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (propertyFacts) {
      setEditedFacts(propertyFacts)
      setShowFactsTable(true)
    }
  }, [propertyFacts])

  const handleSelect = async (description: string) => {
    setValue(description, false)
    clearSuggestions()
    setAutocompleteError(null)

    try {
      const results = await getGeocode({ address: description })
      const { lat, lng } = await getLatLng(results[0])
      onAddressSubmit(description, { lat, lng })
    } catch (err) {
      console.error('Places geocode error:', err)
      setAutocompleteError('Could not get coordinates for this address. Proceeding without location data.')
      // Fall back to submitting without coordinates
      onAddressSubmit(description)
    }
  }

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (value.trim()) {
      clearSuggestions()
      onAddressSubmit(value.trim())
    }
  }

  // Keyboard navigation: close suggestions on Escape
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      clearSuggestions()
    }
  }

  const handleFieldChange = (field: keyof PropertyFacts, value: any) => {
    setEditedFacts((prev) => ({
      ...prev,
      [field]: value,
      userModifiedFields: [
        ...(prev.userModifiedFields || []),
        field,
      ].filter((v, i, a) => a.indexOf(v) === i), // Remove duplicates
    }))
  }

  const handleConfirm = () => {
    if (editedFacts && Object.keys(editedFacts).length > 0) {
      onSubmit(editedFacts as PropertyFacts)
    }
  }

  const isFieldModified = (field: string) => {
    return editedFacts.userModifiedFields?.includes(field)
  }

  const renderFieldValue = (
    field: keyof PropertyFacts,
    label: string,
    type: 'text' | 'number' | 'select' = 'text',
    options?: { value: string; label: string }[]
  ) => {
    const value = editedFacts[field]
    const isModified = isFieldModified(field)

    if (type === 'select' && options) {
      return (
        <TableRow key={field}>
          <TableCell>
            <Typography variant="body2" fontWeight="medium" component="label" htmlFor={`field-${field}`}>
              {label}
              {isModified && (
                <Chip
                  label="Modified"
                  size="small"
                  color="primary"
                  sx={{ ml: 1 }}
                  aria-label="This field has been manually modified"
                />
              )}
            </Typography>
          </TableCell>
          <TableCell>
            <FormControl fullWidth size="small">
              <Select
                id={`field-${field}`}
                value={value || ''}
                onChange={(e) => handleFieldChange(field, e.target.value)}
                inputProps={{
                  'aria-label': label,
                }}
              >
                {options.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </TableCell>
        </TableRow>
      )
    }

    return (
      <TableRow key={field}>
        <TableCell>
          <Typography variant="body2" fontWeight="medium" component="label" htmlFor={`field-${field}`}>
            {label}
            {isModified && (
              <Chip 
                label="Modified" 
                size="small" 
                color="primary" 
                sx={{ ml: 1 }}
                aria-label="This field has been manually modified"
              />
            )}
          </Typography>
        </TableCell>
        <TableCell>
          <TextField
            id={`field-${field}`}
            fullWidth
            size="small"
            type={type}
            value={value ?? ''}
            onChange={(e) =>
              handleFieldChange(
                field,
                type === 'number' ? Number(e.target.value) : e.target.value
              )
            }
            placeholder={value === undefined ? 'Enter manually' : ''}
            inputProps={{
              'aria-label': label,
            }}
          />
        </TableCell>
      </TableRow>
    )
  }

  return (
    <Box sx={{ px: { xs: 1, sm: 2 } }} component="section" aria-labelledby="property-facts-heading">
      <Typography variant="h5" gutterBottom id="property-facts-heading">
        Step 1: Property Facts
      </Typography>

      {!showFactsTable && (
        <Paper sx={{ p: { xs: 2, sm: 3 }, mb: { xs: 2, sm: 3 } }}>
          <form onSubmit={handleManualSubmit} aria-label="Property address search form">
            <Typography variant="body1" gutterBottom>
              Enter the property address to begin analysis
            </Typography>
            <Box sx={{ 
              display: 'flex', 
              flexDirection: { xs: 'column', sm: 'row' },
              gap: 2, 
              mt: 2,
              position: 'relative',
            }}>
              <Box sx={{ flex: 1, position: 'relative' }}>
                <TextField
                  fullWidth
                  label="Property Address"
                  value={value}
                  onChange={(e) => {
                    setValue(e.target.value)
                    setAutocompleteError(null)
                  }}
                  onKeyDown={handleKeyDown}
                  placeholder="123 Main St, Chicago, IL 60601"
                  disabled={loading}
                  autoComplete="off"
                  inputProps={{
                    'aria-label': 'Property address input',
                    'aria-required': 'true',
                    'aria-autocomplete': 'list',
                    'aria-controls': status === 'OK' ? 'address-suggestions' : undefined,
                    'aria-expanded': status === 'OK',
                  }}
                />
                {status === 'OK' && data.length > 0 && (
                  <List
                    id="address-suggestions"
                    ref={suggestionsRef}
                    role="listbox"
                    aria-label="Address suggestions"
                    sx={{
                      position: 'absolute',
                      top: '100%',
                      left: 0,
                      right: 0,
                      zIndex: 1300,
                      bgcolor: 'background.paper',
                      border: '1px solid',
                      borderColor: 'divider',
                      borderRadius: 1,
                      boxShadow: 3,
                      mt: 0.5,
                      maxHeight: 240,
                      overflowY: 'auto',
                      p: 0,
                    }}
                  >
                    {data.map(({ place_id, description }) => (
                      <ListItem key={place_id} disablePadding>
                        <ListItemButton
                          role="option"
                          onClick={() => handleSelect(description)}
                          aria-label={description}
                          sx={{ py: 1 }}
                        >
                          <ListItemText
                            primary={description}
                            primaryTypographyProps={{ variant: 'body2' }}
                          />
                        </ListItemButton>
                      </ListItem>
                    ))}
                  </List>
                )}
              </Box>
              <Button
                type="submit"
                variant="contained"
                disabled={loading || !value.trim()}
                sx={{ minWidth: { xs: '100%', sm: 120 }, alignSelf: 'flex-start' }}
                aria-label="Search for property"
              >
                {loading ? <CircularProgress size={24} aria-label="Loading" /> : 'Search'}
              </Button>
            </Box>
            {autocompleteError && (
              <Alert severity="warning" sx={{ mt: 1 }}>
                {autocompleteError}
              </Alert>
            )}
          </form>
        </Paper>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: { xs: 2, sm: 3 } }} role="alert">
          {error}
        </Alert>
      )}

      {showFactsTable && editedFacts && (
        <Paper sx={{ p: { xs: 2, sm: 3 } }}>
          <Typography variant="h6" gutterBottom id="property-info-heading">
            Property Information
          </Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Review and edit the property facts below. Fields marked as "Modified"
            have been manually entered or updated.
          </Typography>

          <TableContainer sx={{ mt: 2, overflowX: 'auto' }} role="region" aria-labelledby="property-info-heading">
            <Table size="small" aria-label="Property facts table">
              <TableBody>
                {renderFieldValue('address', 'Address', 'text')}
                {renderFieldValue('propertyType', 'Property Type', 'select', [
                  { value: PropertyType.SINGLE_FAMILY, label: 'Single Family' },
                  { value: PropertyType.MULTI_FAMILY, label: 'Multi Family' },
                  { value: PropertyType.COMMERCIAL, label: 'Commercial' },
                ])}
                {renderFieldValue('units', 'Units', 'number')}
                {renderFieldValue('bedrooms', 'Bedrooms', 'number')}
                {renderFieldValue('bathrooms', 'Bathrooms', 'number')}
                {renderFieldValue('squareFootage', 'Square Footage', 'number')}
                {renderFieldValue('lotSize', 'Lot Size (sq ft)', 'number')}
                {renderFieldValue('yearBuilt', 'Year Built', 'number')}
                {renderFieldValue(
                  'constructionType',
                  'Construction Type',
                  'select',
                  [
                    { value: ConstructionType.FRAME, label: 'Frame' },
                    { value: ConstructionType.BRICK, label: 'Brick' },
                    { value: ConstructionType.MASONRY, label: 'Masonry' },
                  ]
                )}
                {renderFieldValue(
                  'interiorCondition',
                  'Interior Condition',
                  'select',
                  [
                    { value: InteriorCondition.NEEDS_GUT, label: 'Needs Gut' },
                    { value: InteriorCondition.POOR, label: 'Poor' },
                    { value: InteriorCondition.AVERAGE, label: 'Average' },
                    { value: InteriorCondition.NEW_RENO, label: 'New Renovation' },
                    { value: InteriorCondition.HIGH_END, label: 'High End' },
                  ]
                )}
                {renderFieldValue('basement', 'Basement', 'select', [
                  { value: 'true', label: 'Yes' },
                  { value: 'false', label: 'No' },
                ])}
                {renderFieldValue('parkingSpaces', 'Parking Spaces', 'number')}
                {renderFieldValue('lastSalePrice', 'Last Sale Price', 'number')}
                {renderFieldValue('lastSaleDate', 'Last Sale Date', 'text')}
                {renderFieldValue('assessedValue', 'Assessed Value', 'number')}
                {renderFieldValue('annualTaxes', 'Annual Taxes', 'number')}
                {renderFieldValue('zoning', 'Zoning', 'text')}
              </TableBody>
            </Table>
          </TableContainer>

          <Box sx={{ 
            mt: 3, 
            display: 'flex', 
            flexDirection: { xs: 'column', sm: 'row' },
            justifyContent: 'flex-end', 
            gap: 2 
          }}>
            <Button
              variant="outlined"
              onClick={() => {
                setShowFactsTable(false)
                setEditedFacts({})
                setValue('')
              }}
              fullWidth={false}
              sx={{ width: { xs: '100%', sm: 'auto' } }}
              aria-label="Start over with new address"
            >
              Start Over
            </Button>
            <Button
              variant="contained"
              onClick={handleConfirm}
              disabled={loading}
              fullWidth={false}
              sx={{ width: { xs: '100%', sm: 'auto' } }}
              aria-label="Confirm property facts and continue to next step"
            >
              Confirm & Continue
            </Button>
          </Box>
        </Paper>
      )}
    </Box>
  )
}
