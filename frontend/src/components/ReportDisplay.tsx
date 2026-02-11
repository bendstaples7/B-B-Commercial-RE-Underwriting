import React, { useState } from 'react'
import {
  Box,
  Paper,
  Typography,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Divider,
  Alert,
  CircularProgress,
  Stack,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import ShareIcon from '@mui/icons-material/Share'
import type { Report } from '@/types'
import { analysisService } from '@/services/api'

interface ReportDisplayProps {
  report: Report
  sessionId: string
}

export const ReportDisplay: React.FC<ReportDisplayProps> = ({
  report,
  sessionId,
}) => {
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [sheetsUrl, setSheetsUrl] = useState<string | null>(null)

  const handleExportToExcel = async () => {
    try {
      setExporting(true)
      setExportError(null)
      
      const blob = await analysisService.exportToExcel(sessionId)
      
      // Create download link
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `real-estate-analysis-${sessionId}.xlsx`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  const handleExportToGoogleSheets = async () => {
    try {
      setExporting(true)
      setExportError(null)
      setSheetsUrl(null)
      
      // For now, use empty credentials (OAuth will be implemented later)
      const result = await analysisService.exportToGoogleSheets(sessionId, {})
      setSheetsUrl(result.url)
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'Export failed')
    } finally {
      setExporting(false)
    }
  }

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

  return (
    <Box>
      {/* Export Buttons */}
      <Stack direction="row" spacing={2} sx={{ mb: 3 }}>
        <Button
          variant="contained"
          startIcon={exporting ? <CircularProgress size={20} /> : <DownloadIcon />}
          onClick={handleExportToExcel}
          disabled={exporting}
        >
          Export to Excel
        </Button>
        <Button
          variant="outlined"
          startIcon={exporting ? <CircularProgress size={20} /> : <ShareIcon />}
          onClick={handleExportToGoogleSheets}
          disabled={exporting}
        >
          Export to Google Sheets
        </Button>
      </Stack>

      {exportError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setExportError(null)}>
          {exportError}
        </Alert>
      )}

      {sheetsUrl && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Report exported successfully!{' '}
          <a href={sheetsUrl} target="_blank" rel="noopener noreferrer">
            Open in Google Sheets
          </a>
        </Alert>
      )}

      {/* Section A: Subject Property Facts */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h5" gutterBottom>
          Section A: Subject Property Facts
        </Typography>
        <Divider sx={{ mb: 2 }} />
        <TableContainer>
          <Table size="small">
            <TableBody>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Address</TableCell>
                <TableCell>{report.subjectProperty.address}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Property Type</TableCell>
                <TableCell>{report.subjectProperty.propertyType}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Units</TableCell>
                <TableCell>{report.subjectProperty.units}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Bedrooms</TableCell>
                <TableCell>{report.subjectProperty.bedrooms}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Bathrooms</TableCell>
                <TableCell>{report.subjectProperty.bathrooms}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Square Footage</TableCell>
                <TableCell>{report.subjectProperty.squareFootage.toLocaleString()}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Lot Size</TableCell>
                <TableCell>{report.subjectProperty.lotSize.toLocaleString()} sq ft</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Year Built</TableCell>
                <TableCell>{report.subjectProperty.yearBuilt}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Construction Type</TableCell>
                <TableCell>{report.subjectProperty.constructionType}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Interior Condition</TableCell>
                <TableCell>{report.subjectProperty.interiorCondition}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Basement</TableCell>
                <TableCell>{report.subjectProperty.basement ? 'Yes' : 'No'}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Parking Spaces</TableCell>
                <TableCell>{report.subjectProperty.parkingSpaces}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Assessed Value</TableCell>
                <TableCell>{formatCurrency(report.subjectProperty.assessedValue)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Annual Taxes</TableCell>
                <TableCell>{formatCurrency(report.subjectProperty.annualTaxes)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>Zoning</TableCell>
                <TableCell>{report.subjectProperty.zoning}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Section B: Comparable Sales */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h5" gutterBottom>
          Section B: Comparable Sales
        </Typography>
        <Divider sx={{ mb: 2 }} />
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Address</TableCell>
                <TableCell>Sale Date</TableCell>
                <TableCell>Sale Price</TableCell>
                <TableCell>Units</TableCell>
                <TableCell>Beds</TableCell>
                <TableCell>Baths</TableCell>
                <TableCell>Sq Ft</TableCell>
                <TableCell>Year Built</TableCell>
                <TableCell>Construction</TableCell>
                <TableCell>Condition</TableCell>
                <TableCell>Distance</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {report.comparables.map((comp) => (
                <TableRow key={comp.id}>
                  <TableCell>{comp.address}</TableCell>
                  <TableCell>{formatDate(comp.saleDate)}</TableCell>
                  <TableCell>{formatCurrency(comp.salePrice)}</TableCell>
                  <TableCell>{comp.units}</TableCell>
                  <TableCell>{comp.bedrooms}</TableCell>
                  <TableCell>{comp.bathrooms}</TableCell>
                  <TableCell>{comp.squareFootage.toLocaleString()}</TableCell>
                  <TableCell>{comp.yearBuilt}</TableCell>
                  <TableCell>{comp.constructionType}</TableCell>
                  <TableCell>{comp.interiorCondition}</TableCell>
                  <TableCell>{comp.distanceMiles.toFixed(2)} mi</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Section C: Weighted Ranking */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h5" gutterBottom>
          Section C: Weighted Ranking
        </Typography>
        <Divider sx={{ mb: 2 }} />
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Rank</TableCell>
                <TableCell>Address</TableCell>
                <TableCell>Recency</TableCell>
                <TableCell>Proximity</TableCell>
                <TableCell>Units</TableCell>
                <TableCell>Beds/Baths</TableCell>
                <TableCell>Sq Ft</TableCell>
                <TableCell>Construction</TableCell>
                <TableCell>Interior</TableCell>
                <TableCell>Total Score</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {report.rankedComparables.map((ranked) => (
                <TableRow key={ranked.comparable.id}>
                  <TableCell sx={{ fontWeight: 'bold' }}>{ranked.rank}</TableCell>
                  <TableCell>{ranked.comparable.address}</TableCell>
                  <TableCell>{ranked.scoreBreakdown.recencyScore.toFixed(1)}</TableCell>
                  <TableCell>{ranked.scoreBreakdown.proximityScore.toFixed(1)}</TableCell>
                  <TableCell>{ranked.scoreBreakdown.unitsScore.toFixed(1)}</TableCell>
                  <TableCell>{ranked.scoreBreakdown.bedsBathsScore.toFixed(1)}</TableCell>
                  <TableCell>{ranked.scoreBreakdown.sqftScore.toFixed(1)}</TableCell>
                  <TableCell>{ranked.scoreBreakdown.constructionScore.toFixed(1)}</TableCell>
                  <TableCell>{ranked.scoreBreakdown.interiorScore.toFixed(1)}</TableCell>
                  <TableCell sx={{ fontWeight: 'bold' }}>
                    {ranked.totalScore.toFixed(1)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Section D: Valuation Models */}
      {report.valuationResult && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h5" gutterBottom>
            Section D: Valuation Models
          </Typography>
          <Divider sx={{ mb: 2 }} />
          {report.valuationResult.comparableValuations.map((valuation, index) => (
            <Box key={valuation.comparable.id} sx={{ mb: 3 }}>
              <Typography variant="h6" gutterBottom>
                Comparable {index + 1}: {valuation.comparable.address}
              </Typography>
              <Typography variant="body2" paragraph>
                {valuation.narrative}
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableBody>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 'bold' }}>Price per Sq Ft</TableCell>
                      <TableCell>{formatCurrency(valuation.pricePerSqft)}</TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 'bold' }}>Price per Unit</TableCell>
                      <TableCell>{formatCurrency(valuation.pricePerUnit)}</TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 'bold' }}>Price per Bedroom</TableCell>
                      <TableCell>{formatCurrency(valuation.pricePerBedroom)}</TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 'bold' }}>Adjusted Value</TableCell>
                      <TableCell sx={{ fontWeight: 'bold' }}>
                        {formatCurrency(valuation.adjustedValue)}
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </TableContainer>
              {valuation.adjustments.length > 0 && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="subtitle2" gutterBottom>
                    Adjustments:
                  </Typography>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Category</TableCell>
                        <TableCell>Difference</TableCell>
                        <TableCell>Adjustment</TableCell>
                        <TableCell>Explanation</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {valuation.adjustments.map((adj, adjIndex) => (
                        <TableRow key={adjIndex}>
                          <TableCell>{adj.category}</TableCell>
                          <TableCell>{adj.difference}</TableCell>
                          <TableCell>{formatCurrency(adj.adjustmentAmount)}</TableCell>
                          <TableCell>{adj.explanation}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              )}
            </Box>
          ))}
        </Paper>
      )}

      {/* Section E: Final ARV Range */}
      {report.valuationResult && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h5" gutterBottom>
            Section E: Final ARV Range
          </Typography>
          <Divider sx={{ mb: 2 }} />
          <TableContainer>
            <Table size="small">
              <TableBody>
                <TableRow>
                  <TableCell sx={{ fontWeight: 'bold' }}>Conservative ARV (25th percentile)</TableCell>
                  <TableCell sx={{ fontSize: '1.1rem', fontWeight: 'bold' }}>
                    {formatCurrency(report.valuationResult.arvRange.conservative)}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 'bold' }}>Likely ARV (Median)</TableCell>
                  <TableCell sx={{ fontSize: '1.1rem', fontWeight: 'bold', color: 'primary.main' }}>
                    {formatCurrency(report.valuationResult.arvRange.likely)}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 'bold' }}>Aggressive ARV (75th percentile)</TableCell>
                  <TableCell sx={{ fontSize: '1.1rem', fontWeight: 'bold' }}>
                    {formatCurrency(report.valuationResult.arvRange.aggressive)}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {/* Section F: Key Drivers */}
      {report.valuationResult && report.valuationResult.keyDrivers.length > 0 && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h5" gutterBottom>
            Section F: Key Drivers
          </Typography>
          <Divider sx={{ mb: 2 }} />
          <Box component="ul" sx={{ pl: 2 }}>
            {report.valuationResult.keyDrivers.map((driver, index) => (
              <Typography component="li" key={index} variant="body1" sx={{ mb: 1 }}>
                {driver}
              </Typography>
            ))}
          </Box>
        </Paper>
      )}
    </Box>
  )
}
