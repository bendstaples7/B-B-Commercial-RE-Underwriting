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
} from '@mui/material'
import type { ARVRange, WholesaleScenario, ScenarioType } from '@/types'

interface WholesaleScenarioFormProps {
  arvRange: ARVRange
  onScenarioUpdate: (scenario: WholesaleScenario) => void
}

export const WholesaleScenarioForm: React.FC<WholesaleScenarioFormProps> = ({
  arvRange,
  onScenarioUpdate,
}) => {
  const [estimatedRepairs, setEstimatedRepairs] = useState<number>(20000)

  const calculateWholesale = (repairs: number): WholesaleScenario => {
    const mao = arvRange.conservative * 0.7 - repairs
    const contractPrice = mao * 0.95
    const assignmentFeeLow = contractPrice * 0.05
    const assignmentFeeHigh = contractPrice * 0.1

    return {
      scenarioType: 'WHOLESALE' as ScenarioType.WHOLESALE,
      purchasePrice: mao,
      mao,
      contractPrice,
      assignmentFeeLow,
      assignmentFeeHigh,
      estimatedRepairs: repairs,
    }
  }

  useEffect(() => {
    const scenario = calculateWholesale(estimatedRepairs)
    onScenarioUpdate(scenario)
  }, [estimatedRepairs, arvRange])

  const scenario = calculateWholesale(estimatedRepairs)

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
        Wholesale Strategy Analysis
      </Typography>
      <Divider sx={{ mb: 2 }} />

      <Box sx={{ mb: 3 }}>
        <TextField
          label="Estimated Repairs"
          type="number"
          value={estimatedRepairs}
          onChange={(e) => setEstimatedRepairs(Number(e.target.value))}
          fullWidth
          InputProps={{
            startAdornment: '$',
          }}
          helperText="Enter estimated repair costs"
        />
      </Box>

      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
        Results
      </Typography>

      <TableContainer>
        <Table size="small">
          <TableBody>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Conservative ARV</TableCell>
              <TableCell>{formatCurrency(arvRange.conservative)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Estimated Repairs</TableCell>
              <TableCell>{formatCurrency(estimatedRepairs)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', fontSize: '1.1rem' }}>
                Maximum Allowable Offer (MAO)
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold', fontSize: '1.1rem', color: 'primary.main' }}>
                {formatCurrency(scenario.mao)}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Contract Price (95% of MAO)</TableCell>
              <TableCell sx={{ fontWeight: 'bold' }}>
                {formatCurrency(scenario.contractPrice)}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Assignment Fee Range</TableCell>
              <TableCell>
                {formatCurrency(scenario.assignmentFeeLow)} - {formatCurrency(scenario.assignmentFeeHigh)}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>

      <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Formula: MAO = Conservative ARV × 70% - Estimated Repairs
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Contract Price = MAO × 95%
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Assignment Fee = Contract Price × 5-10%
        </Typography>
      </Box>
    </Paper>
  )
}
