import { describe, expect, it } from 'vitest'
import {
  findOlcProductForEnvelope,
  listOlcEnvelopeTypes,
  type OlcProduct,
} from '@/utils/olcProductHelpers'

const products: OlcProduct[] = [
  {
    id: 26,
    productType: 'Personal Letters',
    deliveryType: 'First Class',
    envelopeType: 'A6 Blue Mosaic',
  },
  {
    id: 28,
    productType: 'Personal Letters',
    deliveryType: 'First Class',
    envelopeType: 'A6 Lavender',
  },
  {
    id: 27,
    productType: 'Personal Letters',
    deliveryType: 'Standard Class',
    envelopeType: 'A6 Blue Mosaic',
  },
  {
    id: 36,
    productType: 'Professional Letters',
    deliveryType: 'First Class',
    envelopeType: '#10 White',
  },
]

describe('OLC envelope options', () => {
  it('lists unique envelopes for a product type', () => {
    expect(listOlcEnvelopeTypes(products, 'Personal Letters')).toEqual([
      'A6 Blue Mosaic',
      'A6 Lavender',
    ])
  })

  it('swaps product SKU when envelope changes, keeping delivery', () => {
    const next = findOlcProductForEnvelope(products, 26, 'A6 Lavender')
    expect(next?.id).toBe(28)
    expect(next?.deliveryType).toBe('First Class')
  })
})
