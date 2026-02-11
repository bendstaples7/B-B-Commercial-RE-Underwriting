import { useState } from 'react'
import { Container, Typography, Box, Paper } from '@mui/material'
import { WorkflowStep } from './types'
import WorkflowStepper from './components/WorkflowStepper'
import PropertyFactsForm from './components/PropertyFactsForm'
import ComparableSalesDisplay from './components/ComparableSalesDisplay'
import ComparableReviewTable from './components/ComparableReviewTable'
import WeightedScoringTable from './components/WeightedScoringTable'
import ValuationModelsDisplay from './components/ValuationModelsDisplay'
import ReportDisplay from './components/ReportDisplay'

function App() {
  const [currentStep, setCurrentStep] = useState<WorkflowStep>(WorkflowStep.PROPERTY_FACTS)
  const [sessionId, setSessionId] = useState<string | null>(null)

  const handleStepChange = (step: WorkflowStep) => {
    setCurrentStep(step)
  }

  const handleSessionStart = (newSessionId: string) => {
    setSessionId(newSessionId)
  }

  const renderStepContent = () => {
    if (!sessionId && currentStep !== WorkflowStep.PROPERTY_FACTS) {
      return null
    }

    switch (currentStep) {
      case WorkflowStep.PROPERTY_FACTS:
        return (
          <PropertyFactsForm
            sessionId={sessionId}
            onSessionStart={handleSessionStart}
            onNext={() => handleStepChange(WorkflowStep.COMPARABLE_SEARCH)}
          />
        )
      case WorkflowStep.COMPARABLE_SEARCH:
        return (
          <ComparableSalesDisplay
            sessionId={sessionId!}
            onNext={() => handleStepChange(WorkflowStep.COMPARABLE_REVIEW)}
            onBack={() => handleStepChange(WorkflowStep.PROPERTY_FACTS)}
          />
        )
      case WorkflowStep.COMPARABLE_REVIEW:
        return (
          <ComparableReviewTable
            sessionId={sessionId!}
            onNext={() => handleStepChange(WorkflowStep.WEIGHTED_SCORING)}
            onBack={() => handleStepChange(WorkflowStep.COMPARABLE_SEARCH)}
          />
        )
      case WorkflowStep.WEIGHTED_SCORING:
        return (
          <WeightedScoringTable
            sessionId={sessionId!}
            onNext={() => handleStepChange(WorkflowStep.VALUATION)}
            onBack={() => handleStepChange(WorkflowStep.COMPARABLE_REVIEW)}
          />
        )
      case WorkflowStep.VALUATION:
        return (
          <ValuationModelsDisplay
            sessionId={sessionId!}
            onNext={() => handleStepChange(WorkflowStep.REPORT)}
            onBack={() => handleStepChange(WorkflowStep.WEIGHTED_SCORING)}
          />
        )
      case WorkflowStep.REPORT:
        return (
          <ReportDisplay
            sessionId={sessionId!}
            onBack={() => handleStepChange(WorkflowStep.VALUATION)}
          />
        )
      default:
        return null
    }
  }

  return (
    <Container maxWidth="lg" component="main" role="main">
      <Box sx={{ my: { xs: 2, sm: 3, md: 4 }, px: { xs: 1, sm: 2 } }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Real Estate Analysis Platform
        </Typography>
        <Typography variant="body1" color="text.secondary" component="p" sx={{ mb: 4 }}>
          Property valuation and investment analysis tool
        </Typography>

        {sessionId && (
          <Box sx={{ mb: 4 }}>
            <WorkflowStepper currentStep={currentStep} onStepClick={handleStepChange} />
          </Box>
        )}

        <Paper elevation={2} sx={{ p: { xs: 2, sm: 3, md: 4 } }}>
          {renderStepContent()}
        </Paper>
      </Box>
    </Container>
  )
}

export default App
