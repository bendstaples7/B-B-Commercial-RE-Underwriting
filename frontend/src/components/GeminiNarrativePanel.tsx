import React from 'react'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'

interface GeminiNarrativePanelProps {
  narrative: string | null | undefined
}

export const GeminiNarrativePanel: React.FC<GeminiNarrativePanelProps> = ({ narrative }) => {
  if (!narrative) {
    return null
  }

  return (
    <Accordion defaultExpanded={true}>
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        aria-controls="gemini-narrative-content"
        id="gemini-narrative-header"
      >
        <Typography variant="subtitle1" fontWeight="medium">
          AI Analysis
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Box sx={{ maxHeight: 400, overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
          <Typography variant="body2">{narrative}</Typography>
        </Box>
      </AccordionDetails>
    </Accordion>
  )
}
