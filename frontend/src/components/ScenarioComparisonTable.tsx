import React from 'react'
import {
  Box,
  Paper,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Divider,
  Chip,
} from '@mui/material'
import TrendingUpIcon from '@mui/icons-material/TrendingUp'
import type { Scenario, WholesaleScenario, FixFlipScenario, BuyHoldScenario } from '@/types'

interface ScenarioComparisonTableProps {
  scenarios: Scenario[]
}

interface ComparisonRow {
  pricePoint: string
  wholesale?: { roi: number; profit: number }
  fixFlip?: { roi: number; profit: number }
  buyHold?: { roi: number; profit: number }
}

export const ScenarioComparisonTable: React.FC<ScenarioComparisonTableProps> = ({
  scenarios,
}) => {
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const formatPercent = (value: number) => {
    return `${value.toFixed(1)}%`
  }

  // Build comparison data
  const wholesaleScenario = scenarios.find(
    (s) => s.scenarioType === 'WHOLESALE'
  ) as WholesaleScenario | undefined

  const fixFlipScenario = scenarios.find(
    (s) => s.scenarioType === 'FIX_FLIP'
  ) as FixFlipScenario | undefined

  const buyHoldScenario = scenarios.find(
    (s) => s.scenarioType === 'BUY_HOLD'
  ) as BuyHoldScenario | undefined

  // Create comparison rows for different price points
  const comparisonRows: ComparisonRow[] = []

  // For wholesale (single price point)
  if (wholesaleScenario) {
    const assignmentFeeAvg =
      (wholesaleScenario.assignmentFeeLow + wholesaleScenario.assignmentFeeHigh) / 2
    const roi = (assignmentFeeAvg / wholesaleScenario.mao) * 100

    comparisonRows.push({
      pricePoint: 'Low',
      wholesale: { roi, profit: assignmentFeeAvg },
    })
  }

  // For fix & flip (single price point)
  if (fixFlipScenario) {
    if (comparisonRows.length === 0) {
      comparisonRows.push({ pricePoint: 'Low' })
    }
    comparisonRows[0].fixFlip = {
      roi: fixFlipScenario.roi,
      profit: fixFlipScenario.netProfit,
    }
  }

  // For buy & hold (multiple price points)
  if (buyHoldScenario && buyHoldScenario.pricePoints.length >= 3) {
    // Use first capital structure (5% down owner-occupied)
    const lowPoint = buyHoldScenario.pricePoints[0]
    const mediumPoint = buyHoldScenario.pricePoints[1]
    const highPoint = buyHoldScenario.pricePoints[2]

    if (comparisonRows.length === 0) {
      comparisonRows.push({ pricePoint: 'Low' })
    }
    comparisonRows[0].buyHold = {
      roi: lowPoint.cashOnCashReturn * 100,
      profit: lowPoint.monthlyCashFlow * 12,
    }

    comparisonRows.push({
      pricePoint: 'Medium',
      buyHold: {
        roi: mediumPoint.cashOnCashReturn * 100,
        profit: mediumPoint.monthlyCashFlow * 12,
      },
    })

    comparisonRows.push({
      pricePoint: 'High',
      buyHold: {
        roi: highPoint.cashOnCashReturn * 100,
        profit: highPoint.monthlyCashFlow * 12,
      },
    })
  }

  // Ensure we have at least 3 rows
  while (comparisonRows.length < 3) {
    const priceLabel =
      comparisonRows.length === 0 ? 'Low' : comparisonRows.length === 1 ? 'Medium' : 'High'
    comparisonRows.push({ pricePoint: priceLabel })
  }

  // Find highest ROI for each price point
  const getHighestROI = (row: ComparisonRow): 'wholesale' | 'fixFlip' | 'buyHold' | null => {
    const rois: Array<{ type: 'wholesale' | 'fixFlip' | 'buyHold'; value: number }> = []
    
    if (row.wholesale) rois.push({ type: 'wholesale', value: row.wholesale.roi })
    if (row.fixFlip) rois.push({ type: 'fixFlip', value: row.fixFlip.roi })
    if (row.buyHold) rois.push({ type: 'buyHold', value: row.buyHold.roi })

    if (rois.length === 0) return null

    return rois.reduce((max, current) => (current.value > max.value ? current : max)).type
  }

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Scenario Comparison
      </Typography>
      <Divider sx={{ mb: 2 }} />

      <Typography variant="body2" color="text.secondary" paragraph>
        Compare ROI and profit across different investment strategies. The highest ROI for each
        price point is highlighted.
      </Typography>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Price Point</TableCell>
              {wholesaleScenario && (
                <TableCell sx={{ fontWeight: 'bold' }} align="center">
                  Wholesale
                </TableCell>
              )}
              {fixFlipScenario && (
                <TableCell sx={{ fontWeight: 'bold' }} align="center">
                  Fix & Flip
                </TableCell>
              )}
              {buyHoldScenario && (
                <TableCell sx={{ fontWeight: 'bold' }} align="center">
                  Buy & Hold
                </TableCell>
              )}
            </TableRow>
          </TableHead>
          <TableBody>
            {comparisonRows.map((row, index) => {
              const highestROI = getHighestROI(row)

              return (
                <TableRow key={index}>
                  <TableCell sx={{ fontWeight: 'bold' }}>{row.pricePoint}</TableCell>

                  {wholesaleScenario && (
                    <TableCell align="center">
                      {row.wholesale ? (
                        <Box>
                          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
                            <Typography
                              variant="body2"
                              sx={{
                                fontWeight: highestROI === 'wholesale' ? 'bold' : 'normal',
                                color: highestROI === 'wholesale' ? 'success.main' : 'inherit',
                              }}
                            >
                              ROI: {formatPercent(row.wholesale.roi)}
                            </Typography>
                            {highestROI === 'wholesale' && (
                              <Chip
                                icon={<TrendingUpIcon />}
                                label="Best"
                                size="small"
                                color="success"
                              />
                            )}
                          </Box>
                          <Typography variant="caption" color="text.secondary">
                            Profit: {formatCurrency(row.wholesale.profit)}
                          </Typography>
                        </Box>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          -
                        </Typography>
                      )}
                    </TableCell>
                  )}

                  {fixFlipScenario && (
                    <TableCell align="center">
                      {row.fixFlip ? (
                        <Box>
                          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
                            <Typography
                              variant="body2"
                              sx={{
                                fontWeight: highestROI === 'fixFlip' ? 'bold' : 'normal',
                                color: highestROI === 'fixFlip' ? 'success.main' : 'inherit',
                              }}
                            >
                              ROI: {formatPercent(row.fixFlip.roi)}
                            </Typography>
                            {highestROI === 'fixFlip' && (
                              <Chip
                                icon={<TrendingUpIcon />}
                                label="Best"
                                size="small"
                                color="success"
                              />
                            )}
                          </Box>
                          <Typography variant="caption" color="text.secondary">
                            Profit: {formatCurrency(row.fixFlip.profit)}
                          </Typography>
                        </Box>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          -
                        </Typography>
                      )}
                    </TableCell>
                  )}

                  {buyHoldScenario && (
                    <TableCell align="center">
                      {row.buyHold ? (
                        <Box>
                          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
                            <Typography
                              variant="body2"
                              sx={{
                                fontWeight: highestROI === 'buyHold' ? 'bold' : 'normal',
                                color: highestROI === 'buyHold' ? 'success.main' : 'inherit',
                              }}
                            >
                              ROI: {formatPercent(row.buyHold.roi)}
                            </Typography>
                            {highestROI === 'buyHold' && (
                              <Chip
                                icon={<TrendingUpIcon />}
                                label="Best"
                                size="small"
                                color="success"
                              />
                            )}
                          </Box>
                          <Typography variant="caption" color="text.secondary">
                            Annual CF: {formatCurrency(row.buyHold.profit)}
                          </Typography>
                        </Box>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          -
                        </Typography>
                      )}
                    </TableCell>
                  )}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Note: Wholesale and Fix & Flip show single price point analysis. Buy & Hold shows
          multiple price points with 5% down owner-occupied financing.
        </Typography>
      </Box>
    </Paper>
  )
}
