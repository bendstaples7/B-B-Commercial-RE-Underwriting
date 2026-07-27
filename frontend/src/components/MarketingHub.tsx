import React from 'react'
import { Box, Typography } from '@mui/material'
import { OpenLetterSetupPanel } from '@/components/OpenLetterSetupPanel'
import { MailCampaignsPanel } from '@/components/MailCampaignsPanel'

export type MarketingHubMode = 'setup' | 'batches'

export const MarketingHub: React.FC<{ mode?: MarketingHubMode }> = ({
  mode = 'setup',
}) => {
  if (mode === 'batches') {
    return (
      <Box
        sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
        data-testid="mail-batches-page"
      >
        <Typography variant="h5" component="h1" gutterBottom>
          Mail Batches
        </Typography>
        <MailCampaignsPanel />
      </Box>
    )
  }

  return (
    <Box
      sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
      data-testid="direct-mail-setup-page"
    >
      <Typography variant="h5" component="h1" gutterBottom>
        Direct Mail Setup
      </Typography>
      <OpenLetterSetupPanel />
    </Box>
  )
}
