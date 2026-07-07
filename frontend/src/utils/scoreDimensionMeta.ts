/**
 * Human-readable metadata for lead scoring dimensions.
 * Mirrors backend rules in deterministic_scoring_engine.py.
 */

export interface ScoreDimensionMeta {
  label: string
  description: string
  dataSource: string
  maxPoints: number
}

export interface ScoreVersionMeta {
  label: string
  shortLabel: string
  description: string
}

const RESIDENTIAL_MAX: Record<string, number> = {
  property_type_fit: 20,
  neighborhood_fit: 15,
  unit_count_fit: 15,
  absentee_owner: 10,
  owner_mailing_quality: 10,
  years_owned: 10,
  structured_motivation: 25,
  existing_notes_motivation: 10,
  manual_priority: 10,
  source_type_distress: 15,
}

const COMMERCIAL_MAX: Record<string, number> = {
  property_type_fit: 20,
  condo_clarity: 20,
  building_sale_possible: 15,
  neighborhood_fit: 10,
  owner_concentration: 10,
  absentee_owner: 10,
  building_size_fit: 5,
  structured_motivation: 20,
  existing_notes_motivation: 5,
  manual_priority: 5,
}

const DIMENSION_COPY: Record<string, Omit<ScoreDimensionMeta, 'maxPoints'>> = {
  property_type_fit: {
    label: 'Property Type Fit',
    description:
      'How well the property type matches your buy box. Multi-family / 2–4 units score highest; single-family scores moderately. Inferred from unit count when type is missing.',
    dataSource: 'Lead property type, or units count when type is blank',
  },
  neighborhood_fit: {
    label: 'Neighborhood Fit',
    description:
      'Whether the property has a known city or ZIP. A target-neighborhood list is planned; for now any located property earns partial credit.',
    dataSource: 'Property city and ZIP on the lead record',
  },
  unit_count_fit: {
    label: 'Unit Count Fit',
    description:
      'Rewards 2–4 unit buildings (ideal small multifamily). 5+ units and single-family earn lower but non-zero points.',
    dataSource: 'Units field on the lead / property record',
  },
  absentee_owner: {
    label: 'Absentee Owner',
    description:
      'Owner mailing address differs from the property address — often indicates an out-of-area owner more likely to sell.',
    dataSource:
      'Owner mailing address vs. property street (or lead source type = absentee owner)',
  },
  owner_mailing_quality: {
    label: 'Owner Mailing Quality',
    description:
      'Completeness of the owner mailing address. Full street + city + state + ZIP scores highest; partial addresses score less.',
    dataSource: 'Owner mailing address fields on the lead record',
  },
  years_owned: {
    label: 'Years Owned',
    description:
      'Longer hold periods score higher (10+ years = max). Uses acquisition date when set, otherwise parses the last sale date on the lead.',
    dataSource: 'Acquisition date, or last sale date (most_recent_sale) on the lead',
  },
  structured_motivation: {
    label: 'Structured Motivation',
    description:
      'Distress signals from Cook County enrichment (tax sales, scofflaw, violations), source type, notes keywords, and manual priority — unified and capped to avoid double-counting.',
    dataSource: 'motivation_signals table (synced from enrichment JSON and ingestion fields)',
  },
  existing_notes_motivation: {
    label: 'Motivation in Notes',
    description:
      'Lead notes containing motivation keywords (e.g. probate, vacant, tired landlord) score highest. Any notes without keywords earn a small partial score.',
    dataSource: 'Lead notes field (manual, HubSpot, or import)',
  },
  manual_priority: {
    label: 'Manual Priority',
    description:
      'User-assigned priority boost when you have flagged this lead as especially important.',
    dataSource: 'Manual priority field (when set on the lead)',
  },
  source_type_distress: {
    label: 'Source / Distress Signal',
    description:
      'Extra points when the lead came from a distress-oriented source (foreclosure, tax distress, long-owned) or has tax distress data attached.',
    dataSource: 'Lead source type and tax distress enrichment data',
  },
  condo_clarity: {
    label: 'Condo Clarity',
    description:
      'How confident we are the building is not a condo unit. Likely-not-condo scores highest; likely-condo scores zero.',
    dataSource: 'Condo risk status from property / condo analysis',
  },
  building_sale_possible: {
    label: 'Whole-Building Sale Possible',
    description:
      'Whether the entire building (not just a unit) could be purchased. "Yes" scores highest; unknown scores partially.',
    dataSource: 'Building sale possible field from enrichment or manual review',
  },
  owner_concentration: {
    label: 'Owner Concentration',
    description:
      'Fewer distinct owners at the same normalized address suggests a simpler acquisition (one owner = max points).',
    dataSource: 'Condo / ownership analysis (owner count at address)',
  },
  building_size_fit: {
    label: 'Building Size Fit',
    description:
      'Larger commercial buildings (2,000+ sq ft) score higher when square footage is known.',
    dataSource: 'Building square footage on the property record',
  },
}

export const SCORE_VERSION_META: Record<string, ScoreVersionMeta> = {
  residential_v1_internal_data: {
    label: 'Residential scoring model',
    shortLabel: 'Residential (v1)',
    description:
      'This lead uses the residential rubric. There are two scoring models in the app (residential and commercial) — each lead gets exactly one based on property type. "v1" is the first published version of that rubric; "internal data" means it uses fields already in your database (not live public API feeds yet). New scores create history rows — they do not mean a new model version is running.',
  },
  commercial_v1_internal_data: {
    label: 'Commercial scoring model',
    shortLabel: 'Commercial (v1)',
    description:
      'This lead uses the commercial rubric. There are two scoring models in the app (residential and commercial) — each lead gets exactly one based on property type. "v1" is the first published version of that rubric; "internal data" means it uses fields already in your database (not live public API feeds yet). New scores create history rows — they do not mean a new model version is running.',
  },
}

function maxPointsFor(dimension: string, scoreVersion: string): number {
  const table = scoreVersion.startsWith('commercial')
    ? COMMERCIAL_MAX
    : RESIDENTIAL_MAX
  return table[dimension] ?? 0
}

export function getScoreVersionMeta(scoreVersion: string): ScoreVersionMeta {
  return (
    SCORE_VERSION_META[scoreVersion] ?? {
      label: 'Scoring model',
      shortLabel: scoreVersion,
      description:
        'Algorithm identifier for this score. Each lead uses one residential or commercial model; recalculating adds a new score history entry.',
    }
  )
}

export function getDimensionMeta(
  dimension: string,
  scoreVersion: string,
): ScoreDimensionMeta {
  const copy = DIMENSION_COPY[dimension]
  const maxPoints = maxPointsFor(dimension, scoreVersion)

  if (copy) {
    return { ...copy, maxPoints }
  }

  const label = dimension
    .split('_')
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(' ')

  return {
    label,
    description: 'Scoring dimension for this lead.',
    dataSource: 'Lead and property fields in the database',
    maxPoints,
  }
}
