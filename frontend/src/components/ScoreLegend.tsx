/**
 * ScoreLegend — collapsible reference panel explaining each of the lead
 * scoring columns and their possible values.
 *
 * Rendered on the Lead List page and the Lead Detail page to give users
 * in-context documentation of what Tier, Score, Data Quality, Recommended
 * Action, Top Signal, and Missing count actually mean.
 *
 * Pure presentational component — no data fetching or state.
 */
import React from 'react'
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Typography,
  Chip,
  Divider,
  Stack,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { LeadScoreBadge } from './LeadScoreBadge'

export interface ScoreLegendProps {
  /** If true, render expanded on first mount. Defaults to false. */
  defaultExpanded?: boolean
}

/**
 * Compact legend row with a fixed-width label column and a description.
 */
function LegendRow({
  label,
  children,
}: {
  label: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', sm: '160px 1fr' },
        alignItems: 'start',
        gap: { xs: 0.5, sm: 2 },
        py: 1,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', minHeight: 24 }}>
        {label}
      </Box>
      <Box sx={{ color: 'text.secondary' }}>{children}</Box>
    </Box>
  )
}

export const ScoreLegend: React.FC<ScoreLegendProps> = ({
  defaultExpanded = false,
}) => {
  return (
    <Accordion
      defaultExpanded={defaultExpanded}
      disableGutters
      elevation={0}
      sx={{
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        '&:before': { display: 'none' },
      }}
      aria-label="Score column legend"
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{ px: 2 }}
        aria-controls="score-legend-content"
        id="score-legend-header"
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <InfoOutlinedIcon fontSize="small" color="action" />
          <Typography variant="subtitle2">
            What do these score columns mean?
          </Typography>
        </Box>
      </AccordionSummary>

      <AccordionDetails id="score-legend-content" sx={{ px: 2, pb: 2 }}>
        {/* -------- Tier -------- */}
        <LegendRow
          label={
            <Typography variant="body2" fontWeight={600}>
              Tier
            </Typography>
          }
        >
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip
              label="A = 75–100 (strong fit)"
              size="small"
              icon={<LeadScoreBadge tier="A" size="small" />}
              variant="outlined"
            />
            <Chip
              label="B = 60–74 (good fit)"
              size="small"
              icon={<LeadScoreBadge tier="B" size="small" />}
              variant="outlined"
            />
            <Chip
              label="C = 40–59 (marginal)"
              size="small"
              icon={<LeadScoreBadge tier="C" size="small" />}
              variant="outlined"
            />
            <Chip
              label="D = 0–39 (low priority)"
              size="small"
              icon={<LeadScoreBadge tier="D" size="small" />}
              variant="outlined"
            />
          </Stack>
          <Typography variant="caption" display="block" sx={{ mt: 1 }}>
            Letter grade derived from the total Score. Residential and
            commercial leads use separate scoring rubrics but share the same
            tier thresholds.
          </Typography>
        </LegendRow>

        <Divider />

        {/* -------- Score -------- */}
        <LegendRow
          label={
            <Typography variant="body2" fontWeight={600}>
              Score
            </Typography>
          }
        >
          Total lead score (0–100). Residential leads are rated on property type
          fit, neighborhood, unit count, absentee ownership, mailing quality,
          structured motivation signals, and data enrichment dimensions
          (contactability, property equity, ownership duration, engagement).
          Commercial leads use a separate rubric with the same enrichment
          dimensions. Higher is better.
        </LegendRow>

        <Divider />

        {/* -------- Structured Motivation -------- */}
        <LegendRow
          label={
            <Typography variant="body2" fontWeight={600}>
              Motivation
            </Typography>
          }
        >
          Structured distress signals extracted from Cook County enrichment (tax
          sales, scofflaw, violations), ingestion source type, notes keywords,
          and manual priority. Capped at 25 pts residential / 20 commercial
          within the owner-situation bucket. Strong signals (e.g. scavenger tax
          sale) can move a lead several tiers when other factors are equal.
        </LegendRow>

        <Divider />

        {/* -------- Data Quality -------- */}
        <LegendRow
          label={
            <Typography variant="body2" fontWeight={600}>
              Quality
            </Typography>
          }
        >
          Data completeness score, 0–100. Half measures property identity
          (PIN, address, owner name, mailing address, type, size, source).
          Half measures contact reachability: phones weighted by confidence
          (e.g. confirmed ≈ 90) plus email presence. Activity history does not
          count. A low Quality score means the Score itself is less reliable.
          The filter panel exposes a <em>Quality &lt; 70</em> toggle for this.
        </LegendRow>

        <Divider />

        {/* -------- Action -------- */}
        <LegendRow
          label={
            <Typography variant="body2" fontWeight={600}>
              Action
            </Typography>
          }
        >
          <Stack spacing={0.5}>
            <Typography variant="body2" color="text.secondary">
              Suggested next step from the action engine (tier, contactability,
              match status, warmth). Common outcomes:
            </Typography>
            <Box component="ul" sx={{ pl: 2, m: 0 }}>
              <li>
                <strong>Mail Ready</strong> — Tier A with Quality ≥ 70 (when
                cold mail is allowed).
              </li>
              <li>
                <strong>Review Now</strong> — Tier B with Quality ≥ 70.
              </li>
              <li>
                <strong>Enrich Data</strong> — Tier D, no property match /
                street, or unresolved entity owner research — not merely
                “missing phones.”
              </li>
              <li>
                <strong>Follow Up Now</strong> — Warm lead or overdue follow-up.
              </li>
              <li>
                <strong>Nurture</strong> — Tier C or other hold states.
              </li>
              <li>
                <strong>Suppress</strong> — Terminal status, DNC flag, or
                likely condo.
              </li>
              <li>
                <strong>Needs Manual Review</strong> — Commercial lead whose
                condo status is ambiguous.
              </li>
              <li>
                <strong>Call Ready</strong>,{' '}
                <strong>Valuation Needed</strong> — reserved for future
                enrichment workflows.
              </li>
            </Box>
          </Stack>
        </LegendRow>

        <Divider />

        {/* -------- Top Signal -------- */}
        <LegendRow
          label={
            <Typography variant="body2" fontWeight={600}>
              Top Signal
            </Typography>
          }
        >
          The single scoring dimension that contributed the most points.
          When Cook County enrichment has run, this may show a structured
          motivation label (e.g. &quot;Scavenger tax sale&quot;) instead of a
          generic dimension name. Open a lead&apos;s detail page for the full
          breakdown across all dimensions.
        </LegendRow>

        <Divider />

        {/* -------- Missing -------- */}
        <LegendRow
          label={
            <Typography variant="body2" fontWeight={600}>
              Missing
            </Typography>
          }
        >
          Count of key data fields that are absent or empty for this lead.
          The filter panel has shortcuts for leads missing PIN or owner
          mailing address. Reducing this number raises the Quality score and
          often the Tier.
        </LegendRow>

        <Divider />

        {/* -------- Enrichment Dimensions -------- */}
        <Box sx={{ mt: 1 }}>
          <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
            Data Enrichment Dimensions
          </Typography>
          <Stack spacing={1}>
            <LegendRow
              label={
                <Typography variant="caption" fontWeight={600}>
                  Contactability
                </Typography>
              }
            >
              Can we reach this owner? Scored on: mailing address, phone,
              email, and skip trace status.
            </LegendRow>
            <LegendRow
              label={
                <Typography variant="caption" fontWeight={600}>
                  Property Equity
                </Typography>
              }
            >
              Estimated property value from county assessor data. Scored on:
              assessed value, lot size, square footage, and value density.
            </LegendRow>
            <LegendRow
              label={
                <Typography variant="caption" fontWeight={600}>
                  Ownership Duration
                </Typography>
              }
            >
              How long has the current owner held the property? Determined by
              the most recent arm&apos;s-length sale from county records (back
              to 1999).
            </LegendRow>
            <LegendRow
              label={
                <Typography variant="caption" fontWeight={600}>
                  Engagement
                </Typography>
              }
            >
              Is the lead responsive to outreach? Scored on: mailer history,
              follow-up scheduling, recent contact, and response signals.
            </LegendRow>
          </Stack>
        </Box>
      </AccordionDetails>
    </Accordion>
  )
}

export default ScoreLegend
