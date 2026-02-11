import React, { useState, useEffect } from 'react'
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
} from '@mui/material'
import {
  PropertyFacts,
  PropertyType,
  ConstructionType,
  InteriorCondition,
} from '@/types'

interface PropertyFactsFormProps {
  propertyFacts?: PropertyFacts
  onSubmit: (facts: PropertyFacts) => void
  onAddressSubmit: (address: string) => void
  loading?: boolean
  error?: string
}

export const PropertyFactsForm: React.FC<PropertyFactsFormProps> = ({
  propertyFacts,
  onSubmit,
  onAddressSubmit,
  loading = false,
  error,
}) => {
  const [address, setAddress] = useState('')
  const [editedFacts, setEditedFacts] = useState<Partial<PropertyFacts>>({})
  const [showFactsTable, setShowFactsTable] = useState(false)

  useEffect(() => {
    if (propertyFacts) {
      setEditedFacts(propertyFacts)
      setShowFactsTable(true)
    }
  }, [propertyFacts])

  const handleAddressSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (address.trim()) {
      onAddressSubmit(address.trim())
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
          <form onSubmit={handleAddressSubmit} aria-label="Property address search form">
            <Typography variant="body1" gutterBottom>
              Enter the property address to begin analysis
            </Typography>
            <Box sx={{ 
              display: 'flex', 
              flexDirection: { xs: 'column', sm: 'row' },
              gap: 2, 
              mt: 2 
            }}>
              <TextField
                fullWidth
                label="Property Address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="123 Main St, Chicago, IL 60601"
                disabled={loading}
                inputProps={{
                  'aria-label': 'Property address input',
                  'aria-required': 'true',
                }}
              />
              <Button
                type="submit"
                variant="contained"
                disabled={loading || !address.trim()}
                sx={{ minWidth: { xs: '100%', sm: 120 } }}
                aria-label="Search for property"
              >
                {loading ? <CircularProgress size={24} aria-label="Loading" /> : 'Search'}
              </Button>
            </Box>
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
