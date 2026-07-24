import { useEffect, useState, type ReactNode } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useSearchParams } from 'react-router-dom'
import { ccCardSx, ccSectionTitleSx } from '@/components/lead-detail/commandCenterChrome'

/**
 * Deep Dive Details — existing tabs wrapped in collapsible card chrome.
 * Expanded on desktop; collapsed on mobile unless ?tab= is set.
 */
export function DeepDiveDetailsCard({ children }: { children: ReactNode }) {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const deepLinked = Boolean(tabParam && tabParam !== 'timeline')
  const [expanded, setExpanded] = useState(() => deepLinked || !isMobile)

  useEffect(() => {
    if (deepLinked) setExpanded(true)
  }, [deepLinked, tabParam])

  useEffect(() => {
    if (!deepLinked) setExpanded(!isMobile)
  }, [isMobile, deepLinked])

  useEffect(() => {
    const expandFromHash = () => {
      if (window.location.hash === '#deep-dive-details') {
        setExpanded(true)
      }
    }
    expandFromHash()
    window.addEventListener('hashchange', expandFromHash)
    return () => window.removeEventListener('hashchange', expandFromHash)
  }, [])

  return (
    <Accordion
      expanded={expanded}
      onChange={(_, next) => setExpanded(next)}
      disableGutters
      elevation={0}
      id="deep-dive-details"
      data-testid="deep-dive-details"
      sx={{
        ...ccCardSx,
        '&:before': { display: 'none' },
        scrollMarginTop: 16,
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        aria-controls="deep-dive-content"
        id="deep-dive-header"
        sx={{ px: 0, minHeight: 48, '& .MuiAccordionSummary-content': { my: 1 } }}
      >
        <Typography sx={{ ...ccSectionTitleSx, mb: 0 }} component="h2">
          Deep Dive Details
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 0, pt: 0, pb: 0 }}>
        <Box sx={{ pt: 0.5 }}>{children}</Box>
      </AccordionDetails>
    </Accordion>
  )
}
