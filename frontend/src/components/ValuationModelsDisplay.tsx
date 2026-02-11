import React from 'react'
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Card,
  CardContent,
  Grid,
  Divider,
  Chip,
} from '@mui/material'
import { ValuationResult } from '@/types'

interface ValuationModelsDisplayProps {
  valuationResult: ValuationResult
}

export const ValuationModelsDisplay: React.FC<ValuationModelsDisplayProps> = ({
  valuationResult,
}) => {
  const formatCurrency = (value: number): string => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }



  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Step 5: Valuation Models
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Detailed valuation analysis using top 5 ranked comparables
      </Typography>

      {/* Valuation Table */}
      <TableContainer component={Paper} sx={{ mb: 4 }}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 200 }}>
                Comparable Address
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 'bold', minWidth: 120 }}>
                Price/Sq Ft
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 'bold', minWidth: 120 }}>
                Price/Unit
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 'bold', minWidth: 120 }}>
                Price/Bedroom
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 'bold', minWidth: 140 }}>
                Adjusted Value
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {valuationResult.comparableValuations.map((valuation, index) => (
              <TableRow
                key={valuation.comparable.id}
                sx={{
                  '&:hover': {
                    backgroundColor: 'action.hover',
                  },
                }}
              >
                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 'medium' }}>
                    {valuation.comparable.address}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Rank #{index + 1}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {formatCurrency(valuation.pricePerSqft)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {formatCurrency(valuation.pricePerUnit)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {formatCurrency(valuation.pricePerBedroom)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                    {formatCurrency(valuation.adjustedValue)}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Narrative Summaries */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h6" gutterBottom>
          Comparable Analysis Narratives
        </Typography>
        <Grid container spacing={2}>
          {valuationResult.comparableValuations.map((valuation, index) => (
            <Grid item xs={12} key={valuation.comparable.id}>
              <Card variant="outlined">
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                    <Chip
                      label={`#${index + 1}`}
                      color="primary"
                      size="small"
                      sx={{ mr: 1 }}
                    />
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                      {valuation.comparable.address}
                    </Typography>
                  </Box>
                  <Typography variant="body2" color="text.secondary" paragraph>
                    {valuation.narrative}
                  </Typography>
                  {valuation.adjustments.length > 0 && (
                    <Box sx={{ mt: 2 }}>
                      <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                        Adjustments Applied:
                      </Typography>
                      <Box sx={{ mt: 1 }}>
                        {valuation.adjustments.map((adjustment, adjIndex) => (
                          <Typography
                            key={adjIndex}
                            variant="caption"
                            display="block"
                            color="text.secondary"
                            sx={{ ml: 1 }}
                          >
                            • {adjustment.category}: {adjustment.explanation} (
                            {adjustment.adjustmentAmount >= 0 ? '+' : ''}
                            {formatCurrency(adjustment.adjustmentAmount)})
                          </Typography>
                        ))}
                      </Box>
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>

      <Divider sx={{ my: 4 }} />

      {/* ARV Range */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h6" gutterBottom>
          After Repair Value (ARV) Range
        </Typography>
        <Grid container spacing={3}>
          <Grid item xs={12} md={4}>
            <Card
              sx={{
                backgroundColor: 'warning.light',
                color: 'warning.contrastText',
              }}
            >
              <CardContent>
                <Typography variant="overline" display="block" gutterBottom>
                  Conservative ARV
                </Typography>
                <Typography variant="h4" sx={{ fontWeight: 'bold' }}>
                  {formatCurrency(valuationResult.arvRange.conservative)}
                </Typography>
                <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                  25th Percentile
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card
              sx={{
                backgroundColor: 'success.light',
                color: 'success.contrastText',
              }}
            >
              <CardContent>
                <Typography variant="overline" display="block" gutterBottom>
                  Likely ARV
                </Typography>
                <Typography variant="h4" sx={{ fontWeight: 'bold' }}>
                  {formatCurrency(valuationResult.arvRange.likely)}
                </Typography>
                <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                  Median (50th Percentile)
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card
              sx={{
                backgroundColor: 'info.light',
                color: 'info.contrastText',
              }}
            >
              <CardContent>
                <Typography variant="overline" display="block" gutterBottom>
                  Aggressive ARV
                </Typography>
                <Typography variant="h4" sx={{ fontWeight: 'bold' }}>
                  {formatCurrency(valuationResult.arvRange.aggressive)}
                </Typography>
                <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                  75th Percentile
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Box>

      <Divider sx={{ my: 4 }} />

      {/* Key Drivers */}
      <Box>
        <Typography variant="h6" gutterBottom>
          Key Valuation Drivers
        </Typography>
        <Paper sx={{ p: 3 }}>
          {valuationResult.keyDrivers.length > 0 ? (
            <Box component="ul" sx={{ m: 0, pl: 3 }}>
              {valuationResult.keyDrivers.map((driver, index) => (
                <Typography
                  key={index}
                  component="li"
                  variant="body2"
                  sx={{ mb: 1 }}
                >
                  {driver}
                </Typography>
              ))}
            </Box>
          ) : (
            <Typography variant="body2" color="text.secondary">
              No key drivers identified
            </Typography>
          )}
        </Paper>
      </Box>
    </Box>
  )
}
