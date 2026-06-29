/**
 * Zod runtime validation schemas for critical API responses.
 *
 * These schemas guard the endpoints that have historically caused silent bugs
 * when the backend response shape drifted from what the frontend expected.
 * Wrapping responses with `.parse()` causes an immediate, descriptive error
 * instead of silently passing `undefined` into components.
 *
 * Covered endpoints:
 *   - GET  /api/hubspot/config          → HubSpotConfigSchema
 *   - GET  /api/hubspot/import/runs     → HubSpotImportRunListSchema
 *   - GET  /api/hubspot/import/runs/:id → HubSpotImportRunSchema
 *   - GET  /api/hubspot/review-queue    → HubSpotMatchListSchema
 *   - GET  /api/leads/                  → LeadListSchema
 *   - GET  /api/leads/views/*           → LeadListSchema
 *   - GET  /api/hubspot/pipeline/status → PipelineStatusSchema
 */
import { z } from 'zod'

// ---------------------------------------------------------------------------
// HubSpot Config
// ---------------------------------------------------------------------------

export const HubSpotConfigSchema = z.object({
  id: z.number().optional(),
  portal_id: z.string().nullable().optional(),
  account_name: z.string().nullable().optional(),
  configured_at: z.string().nullable().optional(),
  /** Present when no config has been saved yet */
  configured: z.boolean().optional(),
})

export type HubSpotConfigParsed = z.infer<typeof HubSpotConfigSchema>

// ---------------------------------------------------------------------------
// HubSpot Import Run
// ---------------------------------------------------------------------------

export const HubSpotImportRunSchema = z.object({
  id: z.number(),
  object_type: z.string(),
  status: z.string(),
  start_time: z.string().nullable().optional(),
  end_time: z.string().nullable().optional(),
  total_fetched: z.number(),
  created_count: z.number(),
  updated_count: z.number(),
  skipped_count: z.number(),
  error_count: z.number(),
  error_message: z.string().nullable().optional(),
})

export type HubSpotImportRunParsed = z.infer<typeof HubSpotImportRunSchema>

export const HubSpotImportRunListSchema = z.object({
  runs: z.array(HubSpotImportRunSchema),
  total: z.number(),
  page: z.number(),
  per_page: z.number(),
  pages: z.number(),
})

export type HubSpotImportRunListParsed = z.infer<typeof HubSpotImportRunListSchema>

// ---------------------------------------------------------------------------
// HubSpot Match (review queue item)
// ---------------------------------------------------------------------------

export const HubSpotMatchSchema = z.object({
  id: z.number(),
  hubspot_record_type: z.string(),
  hubspot_id: z.string(),
  internal_record_type: z.string().nullable().optional(),
  internal_record_id: z.number().nullable().optional(),
  confidence: z.enum(['HIGH', 'MEDIUM', 'LOW', 'UNMATCHED']),
  status: z.enum(['pending', 'confirmed', 'rejected']),
  matching_criteria: z.string().nullable().optional(),
  display_name: z.string().nullable().optional(),
  internal_display_name: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
})

export type HubSpotMatchParsed = z.infer<typeof HubSpotMatchSchema>

export const HubSpotMatchListSchema = z.object({
  matches: z.array(HubSpotMatchSchema),
  total: z.number(),
  page: z.number(),
  per_page: z.number(),
  pages: z.number(),
  pending_count: z.number(),
})

export type HubSpotMatchListParsed = z.infer<typeof HubSpotMatchListSchema>

// ---------------------------------------------------------------------------
// Lead Summary (used in list views)
// ---------------------------------------------------------------------------

export const LeadSummarySchema = z.object({
  id: z.number(),
  property_street: z.string().nullable(),
  property_city: z.string().nullable(),
  property_state: z.string().nullable(),
  property_zip: z.string().nullable(),
  property_type: z.string().nullable(),
  bedrooms: z.number().nullable(),
  bathrooms: z.number().nullable(),
  square_footage: z.number().nullable(),
  lot_size: z.number().nullable(),
  year_built: z.number().nullable(),
  units: z.number().nullable(),
  units_allowed: z.number().nullable(),
  zoning: z.string().nullable(),
  county_assessor_pin: z.string().nullable(),
  tax_bill_2021: z.number().nullable(),
  most_recent_sale: z.string().nullable(),
  owner_first_name: z.string().nullable(),
  owner_last_name: z.string().nullable(),
  owner_2_first_name: z.string().nullable(),
  owner_2_last_name: z.string().nullable(),
  ownership_type: z.string().nullable(),
  acquisition_date: z.string().nullable(),
  phone_1: z.string().nullable(),
  phone_2: z.string().nullable(),
  phone_3: z.string().nullable(),
  phone_4: z.string().nullable(),
  phone_5: z.string().nullable(),
  phone_6: z.string().nullable(),
  phone_7: z.string().nullable(),
  email_1: z.string().nullable(),
  email_2: z.string().nullable(),
  email_3: z.string().nullable(),
  email_4: z.string().nullable(),
  email_5: z.string().nullable(),
  socials: z.string().nullable(),
  mailing_address: z.string().nullable(),
  mailing_city: z.string().nullable(),
  mailing_state: z.string().nullable(),
  mailing_zip: z.string().nullable(),
  address_2: z.string().nullable(),
  returned_addresses: z.string().nullable(),
  lead_score: z.number(),
  lead_category: z.string(),
  data_source: z.string().nullable(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
  source: z.string().nullable(),
  date_identified: z.string().nullable(),
  // notes and mailer_history are only present in the detail endpoint, not the
  // list endpoint — use .nullish() to accept both null and undefined.
  notes: z.string().nullish(),
  needs_skip_trace: z.boolean().nullable(),
  skip_tracer: z.string().nullable(),
  date_skip_traced: z.string().nullable(),
  date_added_to_hubspot: z.string().nullable(),
  up_next_to_mail: z.boolean().nullable(),
  source_type: z.string().nullable(),
  owner_user_id: z.string().nullable(),
  // mailer_history is stored as free-text strings in legacy imported data,
  // so we accept string | array | object to avoid parse failures.
  // Also nullish because it is absent from list-endpoint responses.
  mailer_history: z.union([z.record(z.unknown()), z.array(z.unknown()), z.string()]).nullish(),
  score_tier: z.enum(['A', 'B', 'C', 'D']).nullish(),
  data_quality_score: z.number().nullish(),
  recommended_action: z.string().nullish(),
  top_signal: z.string().nullish(),
  missing_data: z.array(z.string()).nullish(),
  missing_data_count: z.number().nullish(),
})

export type LeadSummaryParsed = z.infer<typeof LeadSummarySchema>

export const LeadListSchema = z.object({
  leads: z.array(LeadSummarySchema),
  total: z.number(),
  page: z.number(),
  per_page: z.number(),
  pages: z.number(),
})

export type LeadListParsed = z.infer<typeof LeadListSchema>

// ---------------------------------------------------------------------------
// Pipeline Status
// ---------------------------------------------------------------------------

export const PipelineStatusSchema = z.object({
  pipeline_running: z.boolean(),
  matches: z.object({
    total: z.number(),
    high: z.number(),
    medium: z.number(),
    unmatched: z.number(),
  }),
  interactions: z.number(),
  tasks: z.number(),
  signals: z.number(),
})

export type PipelineStatusParsed = z.infer<typeof PipelineStatusSchema>
