import React, { useState } from 'react'
import {
  Box,
  Paper,
  Typography,
  Checkbox,
  FormControlLabel,
  FormGroup,
  Divider,
  Stack,
} from '@mui/material'
import type {
  ARVRange,
  Scenario,
} from '@/types'
import { WholesaleScenarioForm } from './WholesaleScenarioForm'
import { FixFlipScenarioForm } from './FixFlipScenarioForm'
import { BuyHoldScenarioForm } from './BuyHoldScenarioForm'
import { ScenarioComparisonTable } from './ScenarioComparisonTable'

interface ScenarioAnalysisPanelProps {
  arvRange: ARVRange
  sessionId: string
  onScenariosChange?: (scenarios: Scenario[]) => void
}

export const ScenarioAnalysisPanel: React.FC<ScenarioAnalysisPanelProps> = ({
  arvRange,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  sessionId: _sessionId,
  onScenariosChange,
}) => {
  const [selectedScenarios, setSelectedScenarios] = useState<{
    wholesale: boolean
    fixFlip: boolean
    buyHold: boolean
  }>({
    wholesale: false,
    fixFlip: false,
    buyHold: false,
  })

  const [scenarios, setScenarios] = useState<Scenario[]>([])

  const handleScenarioToggle = (scenarioType: 'wholesale' | 'fixFlip' | 'buyHold') => {
    setSelectedScenarios((prev) => ({
      ...prev,
      [scenarioType]: !prev[scenarioType],
    }))
  }

  const handleScenarioUpdate = (scenario: Scenario) => {
    setScenarios((prev) => {
      const filtered = prev.filter((s) => s.scenarioType !== scenario.scenarioType)
      const updated = [...filtered, scenario]
      onScenariosChange?.(updated)
      return updated
    })
  }

  const multipleSelected =
    [selectedScenarios.wholesale, selectedScenarios.fixFlip, selectedScenarios.buyHold].filter(
      Boolean
    ).length > 1

  return (
    <Box sx={{ px: { xs: 1, sm: 2 } }} component="section" aria-labelledby="scenario-analysis-heading">
      <Paper sx={{ p: { xs: 2, sm: 3 }, mb: { xs: 2, sm: 3 } }}>
        <Typography variant="h5" gutterBottom id="scenario-analysis-heading">
          Scenario Analysis
        </Typography>
        <Divider sx={{ mb: 2 }} />
        
        <Typography variant="body2" color="text.secondary" paragraph>
          Select one or more investment scenarios to analyze:
        </Typography>

        <FormGroup role="group" aria-labelledby="scenario-analysis-heading">
          <FormControlLabel
            control={
              <Checkbox
                checked={selectedScenarios.wholesale}
                onChange={() => handleScenarioToggle('wholesale')}
                inputProps={{
                  'aria-label': 'Select wholesale strategy scenario',
                }}
              />
            }
            label="Wholesale Strategy"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={selectedScenarios.fixFlip}
                onChange={() => handleScenarioToggle('fixFlip')}
                inputProps={{
                  'aria-label': 'Select fix and flip strategy scenario',
                }}
              />
            }
            label="Fix & Flip Strategy"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={selectedScenarios.buyHold}
                onChange={() => handleScenarioToggle('buyHold')}
                inputProps={{
                  'aria-label': 'Select buy and hold strategy scenario',
                }}
              />
            }
            label="Buy & Hold Strategy"
          />
        </FormGroup>
      </Paper>

      <Stack spacing={{ xs: 2, sm: 3 }}>
        {selectedScenarios.wholesale && (
          <WholesaleScenarioForm
            arvRange={arvRange}
            onScenarioUpdate={handleScenarioUpdate}
          />
        )}

        {selectedScenarios.fixFlip && (
          <FixFlipScenarioForm
            arvRange={arvRange}
            onScenarioUpdate={handleScenarioUpdate}
          />
        )}

        {selectedScenarios.buyHold && (
          <BuyHoldScenarioForm
            arvRange={arvRange}
            onScenarioUpdate={handleScenarioUpdate}
          />
        )}

        {multipleSelected && scenarios.length > 1 && (
          <ScenarioComparisonTable scenarios={scenarios} />
        )}
      </Stack>
    </Box>
  )
}
