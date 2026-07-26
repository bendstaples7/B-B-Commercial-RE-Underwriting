import React from 'react'
import { Box, Typography } from '@mui/material'
import { OpenLetterSetupPanel } from '@/components/OpenLetterSetupPanel'

export const MarketingHub: React.FC = () => {
  return (
    <Box sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Typography variant="h5" component="h1" gutterBottom>
        Direct Mail Setup
      </Typography>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ mb: 2, overflowWrap: 'anywhere', wordBreak: 'break-word' }}
      >
        Connect Open Letter Connect and choose your default product and template.
        Finish the checklist below before staging leads and sending a batch.
      </Typography>

      <OpenLetterSetupPanel />
    </Box>
  )
}
