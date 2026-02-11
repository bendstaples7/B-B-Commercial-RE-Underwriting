import { useState } from 'react'
import { Container, Typography, Box, Paper } from '@mui/material'
import { WorkflowStep, PropertyFacts, PropertyType, ConstructionType, InteriorCondition } from './types'
import { PropertyFactsForm } from './components/PropertyFactsForm'

function App() {
  const [currentStep] = useState<WorkflowStep>(WorkflowStep.PROPERTY_FACTS)
  const [propertyFacts, setPropertyFacts] = useState<PropertyFacts | undefined>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>()

  const handleAddressSubmit = async (address: string) => {
    setLoading(true)
    setError(undefined)
    
    try {
      // TODO: Call API to fetch property facts
      // For now, just simulate a delay
      await new Promise(resolve => setTimeout(resolve, 1000))
      
      // Mock data for testing
      setPropertyFacts({
        address,
        propertyType: PropertyType.SINGLE_FAMILY,
        units: 1,
        bedrooms: 3,
        bathrooms: 2,
        squareFootage: 1500,
        lotSize: 5000,
        yearBuilt: 2000,
        constructionType: ConstructionType.BRICK,
        basement: true,
        parkingSpaces: 2,
        assessedValue: 250000,
        annualTaxes: 5000,
        zoning: 'R-1',
        interiorCondition: InteriorCondition.AVERAGE,
        coordinates: { lat: 41.8781, lng: -87.6298 },
        dataSource: 'mock',
        userModifiedFields: [],
      })
    } catch (err) {
      setError('Failed to fetch property data. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handlePropertyFactsSubmit = (facts: PropertyFacts) => {
    setPropertyFacts(facts)
    // TODO: Advance to next step
    console.log('Property facts confirmed:', facts)
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

        <Paper elevation={2} sx={{ p: { xs: 2, sm: 3, md: 4 } }}>
          {currentStep === WorkflowStep.PROPERTY_FACTS && (
            <PropertyFactsForm
              propertyFacts={propertyFacts}
              onAddressSubmit={handleAddressSubmit}
              onSubmit={handlePropertyFactsSubmit}
              loading={loading}
              error={error}
            />
          )}
        </Paper>
      </Box>
    </Container>
  )
}

export default App
