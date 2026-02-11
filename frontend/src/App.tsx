import { Container, Typography, Box } from '@mui/material'

function App() {
  return (
    <Container maxWidth="lg" component="main" role="main">
      <Box sx={{ my: { xs: 2, sm: 3, md: 4 }, px: { xs: 1, sm: 2 } }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Real Estate Analysis Platform
        </Typography>
        <Typography variant="body1" color="text.secondary" component="p">
          Property valuation and investment analysis tool
        </Typography>
      </Box>
    </Container>
  )
}

export default App
