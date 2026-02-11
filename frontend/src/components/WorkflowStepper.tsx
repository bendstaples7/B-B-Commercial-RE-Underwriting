import React from 'react'
import {
  Stepper,
  Step,
  StepLabel,
  StepButton,
  Box,
  Typography,
} from '@mui/material'
import { WorkflowStep } from '@/types'

interface WorkflowStepperProps {
  currentStep: WorkflowStep
  onStepClick?: (step: WorkflowStep) => void
}

const stepLabels = {
  [WorkflowStep.PROPERTY_FACTS]: 'Property Facts',
  [WorkflowStep.COMPARABLE_SEARCH]: 'Comparable Search',
  [WorkflowStep.COMPARABLE_REVIEW]: 'Review Comparables',
  [WorkflowStep.WEIGHTED_SCORING]: 'Weighted Scoring',
  [WorkflowStep.VALUATION]: 'Valuation Models',
  [WorkflowStep.REPORT]: 'Report',
}

export const WorkflowStepper: React.FC<WorkflowStepperProps> = ({
  currentStep,
  onStepClick,
}) => {
  const steps = [
    WorkflowStep.PROPERTY_FACTS,
    WorkflowStep.COMPARABLE_SEARCH,
    WorkflowStep.COMPARABLE_REVIEW,
    WorkflowStep.WEIGHTED_SCORING,
    WorkflowStep.VALUATION,
    WorkflowStep.REPORT,
  ]

  const handleStepClick = (step: WorkflowStep) => {
    // Only allow navigation to completed steps (steps before current)
    if (step < currentStep && onStepClick) {
      onStepClick(step)
    }
  }

  return (
    <Box sx={{ width: '100%', mb: { xs: 2, sm: 3, md: 4 } }} role="navigation" aria-label="Workflow progress">
      <Stepper 
        activeStep={currentStep - 1} 
        alternativeLabel
        orientation="horizontal"
        sx={{
          '& .MuiStepLabel-label': {
            fontSize: { xs: '0.75rem', sm: '0.875rem' },
          },
        }}
      >
        {steps.map((step) => {
          const isCompleted = step < currentStep
          const isCurrent = step === currentStep
          const isClickable = isCompleted && onStepClick

          return (
            <Step key={step} completed={isCompleted}>
              {isClickable ? (
                <StepButton 
                  onClick={() => handleStepClick(step)}
                  aria-label={`Go back to ${stepLabels[step]}`}
                >
                  <StepLabel>
                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: isCurrent ? 'bold' : 'normal',
                        display: { xs: 'none', sm: 'block' },
                      }}
                    >
                      {stepLabels[step]}
                    </Typography>
                  </StepLabel>
                </StepButton>
              ) : (
                <StepLabel>
                  <Typography
                    variant="body2"
                    sx={{
                      fontWeight: isCurrent ? 'bold' : 'normal',
                      display: { xs: 'none', sm: 'block' },
                    }}
                    aria-current={isCurrent ? 'step' : undefined}
                  >
                    {stepLabels[step]}
                  </Typography>
                </StepLabel>
              )}
            </Step>
          )
        })}
      </Stepper>
    </Box>
  )
}
