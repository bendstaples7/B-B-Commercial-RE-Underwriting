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
  TableHead,
  TableRow,
  Divider,
  Grid,
  Tabs,
  Tab,
} from '@mui/material'
import type { ARVRange, BuyHoldScenario, ScenarioType, PricePoint, CapitalStructure } from '@/types'

interface BuyHoldScenarioFormProps {
  arvRange: ARVRange
  onScenarioUpdate: (scenario: BuyHoldScenario) => void
}

export const BuyHoldScenarioForm: React.FC<BuyHoldScenarioFormProps> = ({
  arvRange,
  onScenarioUpdate,
}) => {
  const [marketRent, setMarketRent] = useState<number>(2000)
  const [monthlyExpenses, setMonthlyExpenses] = useState<number>(500)
  const [selectedTab, setSelectedTab] = useState(0)

  const capitalStructures: CapitalStructure[] = [
    {
      name: '5% Down Owner-Occupied',
      downPaymentPercent: 0.05,
      interestRate: 0.065,
      loanTermMonths: 360,
    },
    {
      name: '25% Down Investor',
      downPaymentPercent: 0.25,
      interestRate: 0.075,
      loanTermMonths: 360,
    },
  ]

  const calculateMonthlyPayment = (
    principal: number,
    annualRate: number,
    months: number
  ): number => {
    const monthlyRate = annualRate / 12
    return (principal * monthlyRate * Math.pow(1 + monthlyRate, months)) /
      (Math.pow(1 + monthlyRate, months) - 1)
  }

  const calculatePricePoint = (
    purchasePrice: number,
    structure: CapitalStructure,
    rent: number,
    expenses: number
  ): PricePoint => {
    const downPayment = purchasePrice * structure.downPaymentPercent
    const loanAmount = purchasePrice - downPayment
    const monthlyPayment = calculateMonthlyPayment(
      loanAmount,
      structure.interestRate,
      structure.loanTermMonths
    )
    const monthlyCashFlow = rent - monthlyPayment - expenses
    const cashOnCashReturn = (monthlyCashFlow * 12) / downPayment
    const capRate = ((rent - expenses) * 12) / purchasePrice

    return {
      purchasePrice,
      downPayment,
      loanAmount,
      monthlyPayment,
      monthlyRent: rent,
      monthlyExpenses: expenses,
      monthlyCashFlow,
      cashOnCashReturn,
      capRate,
    }
  }

  const calculateBuyHold = (rent: number, expenses: number): BuyHoldScenario => {
    const lowPrice = arvRange.conservative * 0.85
    const mediumPrice = arvRange.likely * 0.9
    const highPrice = arvRange.aggressive * 0.95

    const pricePoints: PricePoint[] = []
    
    // Generate price points for each capital structure
    capitalStructures.forEach((structure) => {
      pricePoints.push(calculatePricePoint(lowPrice, structure, rent, expenses))
      pricePoints.push(calculatePricePoint(mediumPrice, structure, rent, expenses))
      pricePoints.push(calculatePricePoint(highPrice, structure, rent, expenses))
    })

    return {
      scenarioType: 'BUY_HOLD' as ScenarioType.BUY_HOLD,
      purchasePrice: mediumPrice,
      capitalStructures,
      marketRent: rent,
      pricePoints,
    }
  }

  useEffect(() => {
    const scenario = calculateBuyHold(marketRent, monthlyExpenses)
    onScenarioUpdate(scenario)
  }, [marketRent, monthlyExpenses, arvRange])

  const scenario = calculateBuyHold(marketRent, monthlyExpenses)

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const formatPercent = (value: number) => {
    return `${(value * 100).toFixed(2)}%`
  }

  // Get price points for selected capital structure
  const structureIndex = selectedTab
  const structurePricePoints = scenario.pricePoints.filter((_, index) => {
    return Math.floor(index / 3) === structureIndex
  })

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Buy & Hold Strategy Analysis
      </Typography>
      <Divider sx={{ mb: 2 }} />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={6}>
          <TextField
            label="Market Rent (Monthly)"
            type="number"
            value={marketRent}
            onChange={(e) => setMarketRent(Number(e.target.value))}
            fullWidth
            InputProps={{
              startAdornment: '$',
            }}
            helperText="Expected monthly rental income"
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <TextField
            label="Monthly Expenses"
            type="number"
            value={monthlyExpenses}
            onChange={(e) => setMonthlyExpenses(Number(e.target.value))}
            fullWidth
            InputProps={{
              startAdornment: '$',
            }}
            helperText="Property taxes, insurance, maintenance, vacancy"
          />
        </Grid>
      </Grid>

      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
        Capital Structure Analysis
      </Typography>

      <Tabs value={selectedTab} onChange={(_, newValue) => setSelectedTab(newValue)} sx={{ mb: 2 }}>
        <Tab label="5% Down Owner-Occupied" />
        <Tab label="25% Down Investor" />
      </Tabs>

      <Box sx={{ mb: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          <strong>Structure:</strong> {capitalStructures[structureIndex].name}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          <strong>Down Payment:</strong> {capitalStructures[structureIndex].downPaymentPercent * 100}%
        </Typography>
        <Typography variant="body2" color="text.secondary">
          <strong>Interest Rate:</strong> {capitalStructures[structureIndex].interestRate * 100}%
        </Typography>
        <Typography variant="body2" color="text.secondary">
          <strong>Loan Term:</strong> {capitalStructures[structureIndex].loanTermMonths / 12} years
        </Typography>
      </Box>

      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
        Price Point Analysis
      </Typography>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Price Point</TableCell>
              <TableCell sx={{ fontWeight: 'bold' }}>Purchase Price</TableCell>
              <TableCell sx={{ fontWeight: 'bold' }}>Down Payment</TableCell>
              <TableCell sx={{ fontWeight: 'bold' }}>Monthly Payment</TableCell>
              <TableCell sx={{ fontWeight: 'bold' }}>Cash Flow</TableCell>
              <TableCell sx={{ fontWeight: 'bold' }}>Cash-on-Cash</TableCell>
              <TableCell sx={{ fontWeight: 'bold' }}>Cap Rate</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {structurePricePoints.map((point, index) => {
              const priceLabel = index === 0 ? 'Low' : index === 1 ? 'Medium' : 'High'
              return (
                <TableRow key={index}>
                  <TableCell sx={{ fontWeight: 'bold' }}>{priceLabel}</TableCell>
                  <TableCell>{formatCurrency(point.purchasePrice)}</TableCell>
                  <TableCell>{formatCurrency(point.downPayment)}</TableCell>
                  <TableCell>{formatCurrency(point.monthlyPayment)}</TableCell>
                  <TableCell
                    sx={{
                      color: point.monthlyCashFlow >= 0 ? 'success.main' : 'error.main',
                      fontWeight: 'bold',
                    }}
                  >
                    {formatCurrency(point.monthlyCashFlow)}
                  </TableCell>
                  <TableCell
                    sx={{
                      color: point.cashOnCashReturn >= 0 ? 'success.main' : 'error.main',
                    }}
                  >
                    {formatPercent(point.cashOnCashReturn)}
                  </TableCell>
                  <TableCell>{formatPercent(point.capRate)}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Cash Flow = Monthly Rent - Monthly Payment - Monthly Expenses
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Cash-on-Cash Return = (Annual Cash Flow) / Down Payment
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Cap Rate = (Annual Rent - Annual Expenses) / Purchase Price
        </Typography>
      </Box>
    </Paper>
  )
}
