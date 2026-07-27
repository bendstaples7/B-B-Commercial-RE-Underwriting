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
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ mb: 2, overflowWrap: 'anywhere', wordBreak: 'break-word' }}
        >
          History of Open Letter sends for the database this app is connected to —
          staged vs submitted counts, address feedback, and analytics. Local
          development does not include production sends. Stage new leads from Ready
          to Mail.
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
