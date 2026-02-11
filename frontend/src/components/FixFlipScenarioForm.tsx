import React, { useState, useEffect } from 'react'
import {
  Box,
  Paper,
  Typography,
  TextField,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableRow,
  Divider,
  Grid,
} from '@mui/material'
import type { ARVRange, FixFlipScenario, ScenarioType } from '@/types'

interface FixFlipScenarioFormProps {
  arvRange: ARVRange
  onScenarioUpdate: (scenario: FixFlipScenario) => void
}

export const FixFlipScenarioForm: React.FC<FixFlipScenarioFormProps> = ({
  arvRange,
  onScenarioUpdate,
}) => {
  const [acquisitionCost, setAcquisitionCost] = useState<number>(150000)
  const [renovationCost, setRenovationCost] = useState<number>(50000)
  const [monthsToFlip, setMonthsToFlip] = useState<number>(6)

  const calculateFixFlip = (
    acquisition: number,
    renovation: number,
    months: number
  ): FixFlipScenario => {
    const holdingCosts = (acquisition + renovation) * 0.02 * months
    const loanAmount = (acquisition + renovation) * 0.75
    const financingCosts = loanAmount * 0.11 * (months / 12)
    const closingCosts = arvRange.likely * 0.08
    const totalCost = acquisition + renovation + holdingCosts + financingCosts + closingCosts
    const exitValue = arvRange.likely
    const netProfit = exitValue - totalCost
    const downPayment = (acquisition + renovation) * 0.25
    const roi = (netProfit / downPayment) * 100

    return {
      scenarioType: 'FIX_FLIP' as ScenarioType.FIX_FLIP,
      purchasePrice: acquisition,
      acquisitionCost: acquisition,
      renovationCost: renovation,
      holdingCosts,
      financingCosts,
      closingCosts,
      totalCost,
      exitValue,
      netProfit,
      roi,
      monthsToFlip: months,
    }
  }

  useEffect(() => {
    const scenario = calculateFixFlip(acquisitionCost, renovationCost, monthsToFlip)
    onScenarioUpdate(scenario)
  }, [acquisitionCost, renovationCost, monthsToFlip, arvRange])

  const scenario = calculateFixFlip(acquisitionCost, renovationCost, monthsToFlip)

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Fix & Flip Strategy Analysis
      </Typography>
      <Divider sx={{ mb: 2 }} />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={4}>
          <TextField
            label="Acquisition Cost"
            type="number"
            value={acquisitionCost}
            onChange={(e) => setAcquisitionCost(Number(e.target.value))}
            fullWidth
            InputProps={{
              startAdornment: '$',
            }}
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <TextField
            label="Renovation Budget"
            type="number"
            value={renovationCost}
            onChange={(e) => setRenovationCost(Number(e.target.value))}
            fullWidth
            InputProps={{
              startAdornment: '$',
            }}
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <TextField
            label="Months to Flip"
            type="number"
            value={monthsToFlip}
            onChange={(e) => setMonthsToFlip(Number(e.target.value))}
            fullWidth
            inputProps={{ min: 1, max: 24 }}
          />
        </Grid>
      </Grid>

      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
        Cost Breakdown
      </Typography>

      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableBody>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Acquisition Cost</TableCell>
              <TableCell>{formatCurrency(scenario.acquisitionCost)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Renovation Cost</TableCell>
              <TableCell>{formatCurrency(scenario.renovationCost)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>
                Holding Costs (2% per month × {monthsToFlip} months)
              </TableCell>
              <TableCell>{formatCurrency(scenario.holdingCosts)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>
                Financing Costs (11% interest, 75% LTC)
              </TableCell>
              <TableCell>{formatCurrency(scenario.financingCosts)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Closing Costs (8% of ARV)</TableCell>
              <TableCell>{formatCurrency(scenario.closingCosts)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', fontSize: '1.1rem' }}>Total Cost</TableCell>
              <TableCell sx={{ fontWeight: 'bold', fontSize: '1.1rem' }}>
                {formatCurrency(scenario.totalCost)}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>

      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
        Profit Analysis
      </Typography>

      <TableContainer>
        <Table size="small">
          <TableBody>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Exit Value (Likely ARV)</TableCell>
              <TableCell>{formatCurrency(scenario.exitValue)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Total Cost</TableCell>
              <TableCell>{formatCurrency(scenario.totalCost)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', fontSize: '1.1rem', color: 'primary.main' }}>
                Net Profit
              </TableCell>
              <TableCell
                sx={{
                  fontWeight: 'bold',
                  fontSize: '1.1rem',
                  color: scenario.netProfit >= 0 ? 'success.main' : 'error.main',
                }}
              >
                {formatCurrency(scenario.netProfit)}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', fontSize: '1.1rem' }}>ROI</TableCell>
              <TableCell
                sx={{
                  fontWeight: 'bold',
                  fontSize: '1.1rem',
                  color: scenario.roi >= 0 ? 'success.main' : 'error.main',
                }}
              >
                {scenario.roi.toFixed(1)}%
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>

      <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Holding Costs = (Acquisition + Renovation) × 2% × Months
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Financing = (Acquisition + Renovation) × 75% × 11% × (Months / 12)
        </Typography>
        <Typography variant="body2" color="text.secondary">
          ROI = Net Profit / Down Payment (25%) × 100
        </Typography>
      </Box>
    </Paper>
  )
}
