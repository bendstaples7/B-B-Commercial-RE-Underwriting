/** Helpers for displaying Open Letter Connect product options. */

export type OlcProduct = {
  id: string | number
  name?: string
  productType?: string
  deliveryType?: string
  postageType?: string
  envelopeType?: string | null
  paperType?: string
  paperSize?: string
  productSlug?: string
}

export type OlcCostTier = 'budget' | 'standard' | 'premium'

const DELIVERY_SPEED: Record<string, string> = {
  'First Class': '1–5 business days',
  'Standard Class': '7–21 business days',
  'First Class Forever': '1–5 business days',
}

const COST_TIER_LABEL: Record<OlcCostTier, string> = {
  budget: 'Budget',
  standard: 'Standard',
  premium: 'Premium',
}

/** Relative cost tier — OLC does not expose per-SKU prices via API. */
export function getOlcCostTier(product: OlcProduct): OlcCostTier {
  const postage = (product.postageType || '').toLowerCase()
  const delivery = product.deliveryType || ''
  const type = (product.productType || '').toLowerCase()

  if (postage === 'forever' || type.includes('real penned')) {
    return 'premium'
  }
  if (delivery === 'Standard Class' || delivery.toLowerCase() === 'standard class') {
    return 'budget'
  }
  return 'standard'
}

export function formatOlcProductLabel(product: OlcProduct): string {
  const parts = [
    product.productType || product.name,
    product.deliveryType,
    product.postageType,
    product.envelopeType,
  ].filter(Boolean)
  return parts.join(' · ')
}

export function getOlcDeliverySpeed(product: OlcProduct): string | null {
  if (!product.deliveryType) return null
  return DELIVERY_SPEED[product.deliveryType] || null
}

export function describeOlcProduct(product: OlcProduct): {
  tier: OlcCostTier
  tierLabel: string
  deliverySpeed: string | null
  postageNote: string
} {
  const tier = getOlcCostTier(product)
  const postage = (product.postageType || '').toLowerCase()

  let postageNote = 'Metered postage printed on the envelope at current USPS rates.'
  if (postage === 'forever') {
    postageNote =
      'Uses a Forever-stamp look on a “real penned” piece. Premium presentation — typically costs more than Live, not less.'
  } else if (postage === 'indicia') {
    postageNote = 'Permit imprint postage (common on postcards and self-mailers).'
  }

  return {
    tier,
    tierLabel: COST_TIER_LABEL[tier],
    deliverySpeed: getOlcDeliverySpeed(product),
    postageNote,
  }
}

export const OLC_PRICING_URL = 'https://openletterconnect.com/pricing/'

export const POSTAGE_COMPARISON = [
  {
    postage: 'Live',
    summary: 'Printed metered postage',
    cost: 'Standard pricing',
    bestFor: 'Professional outreach letters — the usual choice for CRE mail at scale.',
  },
  {
    postage: 'Forever',
    summary: 'Physical Forever-stamp appearance',
    cost: 'Premium (higher than Live)',
    bestFor: '“Real penned” letters when you want a handwritten, personal look and higher open rates.',
  },
  {
    postage: 'Indicia',
    summary: 'Permit imprint',
    cost: 'Varies by format',
    bestFor: 'Postcards, snap packs, and self-mailers.',
  },
] as const

export function sortOlcProducts(products: OlcProduct[]): OlcProduct[] {
  const tierOrder: Record<OlcCostTier, number> = { budget: 0, standard: 1, premium: 2 }
  return [...products].sort((a, b) => {
    const tierDiff = tierOrder[getOlcCostTier(a)] - tierOrder[getOlcCostTier(b)]
    if (tierDiff !== 0) return tierDiff
    return formatOlcProductLabel(a).localeCompare(formatOlcProductLabel(b))
  })
}

/** Envelope styles exposed by OLC products (unique `envelopeType` values). */
export function listOlcEnvelopeTypes(
  products: OlcProduct[],
  productType?: string | null,
): string[] {
  const filtered = productType
    ? products.filter((p) => p.productType === productType)
    : products
  const values = new Set<string>()
  for (const product of filtered) {
    const envelope = (product.envelopeType || '').trim()
    if (envelope) values.add(envelope)
  }
  return [...values].sort((a, b) => a.localeCompare(b))
}

/** Prefer same product type, postage, and delivery when swapping envelope SKU. */
export function findOlcProductForEnvelope(
  products: OlcProduct[],
  currentProductId: number | '' | null | undefined,
  envelopeType: string,
): OlcProduct | undefined {
  const wanted = envelopeType.trim()
  if (!wanted) return undefined
  const current = products.find((p) => Number(p.id) === Number(currentProductId))
  const matches = products.filter((p) => (p.envelopeType || '').trim() === wanted)
  if (!matches.length) return undefined
  if (current?.productType) {
    const sameType = matches.filter((p) => p.productType === current.productType)
    const samePostage = sameType.filter((p) => p.postageType === current.postageType)
    const sameDelivery = samePostage.find((p) => p.deliveryType === current.deliveryType)
    if (sameDelivery) return sameDelivery
    if (samePostage[0]) return samePostage[0]
    const sameDeliveryFallback = sameType.find((p) => p.deliveryType === current.deliveryType)
    if (sameDeliveryFallback) return sameDeliveryFallback
    if (sameType[0]) return sameType[0]
  }
  return matches[0]
}
