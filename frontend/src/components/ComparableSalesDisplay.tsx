import React from 'react'
import {
  Box,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Alert,
  Chip,
} from '@mui/material'
import {
  PropertyFacts,
  ComparableSale,
  PropertyType,
  ConstructionType,
  InteriorCondition,
} from '@/types'

interface ComparableSalesDisplayProps {
  subjectProperty: PropertyFacts
  comparables: ComparableSale[]
  searchRadius: number
  loading?: boolean
}

export const ComparableSalesDisplay: React.FC<ComparableSalesDisplayProps> = ({
  subjectProperty,
  comparables,
  searchRadius,
}) => {
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const formatPropertyType = (type: PropertyType) => {
    const labels = {
      [PropertyType.SINGLE_FAMILY]: 'Single Family',
      [PropertyType.MULTI_FAMILY]: 'Multi Family',
      [PropertyType.COMMERCIAL]: 'Commercial',
    }
    return labels[type] || type
  }

  const formatConstructionType = (type: ConstructionType) => {
    const labels = {
      [ConstructionType.FRAME]: 'Frame',
      [ConstructionType.BRICK]: 'Brick',
      [ConstructionType.MASONRY]: 'Masonry',
    }
    return labels[type] || type
  }

  const formatInteriorCondition = (condition: InteriorCondition) => {
    const labels = {
      [InteriorCondition.NEEDS_GUT]: 'Needs Gut',
      [InteriorCondition.POOR]: 'Poor',
      [InteriorCondition.AVERAGE]: 'Average',
      [InteriorCondition.NEW_RENO]: 'New Renovation',
      [InteriorCondition.HIGH_END]: 'High End',
    }
    return labels[condition] || condition
  }

  const formatNumber = (value: number) => {
    return new Intl.NumberFormat('en-US').format(value)
  }

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Step 2: Comparable Sales
      </Typography>

      <Paper sx={{ p: 3, mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">
            Found {comparables.length} Comparable{comparables.length !== 1 ? 's' : ''}
          </Typography>
          <Chip
            label={`Search Radius: ${searchRadius} mile${searchRadius !== 1 ? 's' : ''}`}
            color="primary"
            variant="outlined"
          />
        </Box>

        {comparables.length < 10 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Limited dataset: Only {comparables.length} comparable{comparables.length !== 1 ? 's' : ''} found
            within {searchRadius} mile{searchRadius !== 1 ? 's' : ''}. 
            A minimum of 10 comparables is recommended for accurate valuation.
          </Alert>
        )}

        <Typography variant="body2" color="text.secondary" gutterBottom>
          The subject property is shown in the first row, followed by comparable sales.
        </Typography>

        <TableContainer sx={{ mt: 2, maxHeight: 600 }}>
          <Table stickyHeader size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 200 }}>Address</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }}>Sale Date</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }} align="right">Sale Price</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }}>Property Type</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 80 }} align="right">Units</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 80 }} align="right">Beds</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 80 }} align="right">Baths</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">Sq Ft</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">Lot Size</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">Year Built</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }}>Construction</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 140 }}>Interior Condition</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">Distance</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {/* Subject Property Row */}
              <TableRow
                sx={{
                  backgroundColor: 'primary.light',
                  '& td': { fontWeight: 'bold' },
                }}
              >
                <TableCell>
                  {subjectProperty.address}
                  <Chip label="Subject" size="small" color="primary" sx={{ ml: 1 }} />
                </TableCell>
                <TableCell>
                  {subjectProperty.lastSaleDate
                    ? formatDate(subjectProperty.lastSaleDate)
                    : 'N/A'}
                </TableCell>
                <TableCell align="right">
                  {subjectProperty.lastSalePrice
                    ? formatCurrency(subjectProperty.lastSalePrice)
                    : 'N/A'}
                </TableCell>
                <TableCell>{formatPropertyType(subjectProperty.propertyType)}</TableCell>
                <TableCell align="right">{subjectProperty.units}</TableCell>
                <TableCell align="right">{subjectProperty.bedrooms}</TableCell>
                <TableCell align="right">{subjectProperty.bathrooms}</TableCell>
                <TableCell align="right">{formatNumber(subjectProperty.squareFootage)}</TableCell>
                <TableCell align="right">{formatNumber(subjectProperty.lotSize)}</TableCell>
                <TableCell align="right">{subjectProperty.yearBuilt}</TableCell>
                <TableCell>{formatConstructionType(subjectProperty.constructionType)}</TableCell>
                <TableCell>{formatInteriorCondition(subjectProperty.interiorCondition)}</TableCell>
                <TableCell align="right">-</TableCell>
              </TableRow>

              {/* Comparable Sales Rows */}
              {comparables.map((comp) => (
                <TableRow key={comp.id} hover>
                  <TableCell>{comp.address}</TableCell>
                  <TableCell>{formatDate(comp.saleDate)}</TableCell>
                  <TableCell align="right">{formatCurrency(comp.salePrice)}</TableCell>
                  <TableCell>{formatPropertyType(comp.propertyType)}</TableCell>
                  <TableCell align="right">{comp.units}</TableCell>
                  <TableCell align="right">{comp.bedrooms}</TableCell>
                  <TableCell align="right">{comp.bathrooms}</TableCell>
                  <TableCell align="right">{formatNumber(comp.squareFootage)}</TableCell>
                  <TableCell align="right">{formatNumber(comp.lotSize)}</TableCell>
                  <TableCell align="right">{comp.yearBuilt}</TableCell>
                  <TableCell>{formatConstructionType(comp.constructionType)}</TableCell>
                  <TableCell>{formatInteriorCondition(comp.interiorCondition)}</TableCell>
                  <TableCell align="right">{comp.distanceMiles.toFixed(2)} mi</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Box>
  )
}
