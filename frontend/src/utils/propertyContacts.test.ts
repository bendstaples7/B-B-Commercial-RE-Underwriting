import { describe, expect, it } from 'vitest'

import type { PropertyContactSummary } from '@/types'
import {
  isAddressLikeContactName,
  isEntityContactName,
  isGenericOwnerName,
  ownerDisplayEntries,
  primaryOwnerDisplayName,
  rankOwnersForDisplay,
} from './propertyContacts'

function makeContact(
  partial: Partial<PropertyContactSummary> & {
    id: number
    first_name?: string | null
    last_name?: string | null
  },
): PropertyContactSummary {
  return {
    role: 'owner',
    is_primary: false,
    phones: [],
    emails: [],
    ...partial,
  } as PropertyContactSummary
}

describe('isEntityContactName', () => {
  it('does not classify personal surnames starting with Co as entities', () => {
    expect(isEntityContactName({ first_name: 'John', last_name: 'Cooper' })).toBe(false)
    expect(isEntityContactName({ first_name: 'Jane', last_name: 'Cohen' })).toBe(false)
  })

  it('still classifies company suffixes as entities', () => {
    expect(isEntityContactName({ first_name: 'Acme', last_name: 'Co' })).toBe(true)
    expect(isEntityContactName({ first_name: 'Acme', last_name: 'CO.' })).toBe(true)
  })
})

describe('isAddressLikeContactName', () => {
  it('detects mashed house-number street names', () => {
    expect(
      isAddressLikeContactName({ first_name: '3508SACRAMENTO', last_name: 'MAYNARD' }),
    ).toBe(true)
  })

  it('detects conventional street addresses', () => {
    expect(isAddressLikeContactName({ first_name: '123', last_name: 'Main St' })).toBe(true)
  })

  it('does not flag normal people', () => {
    expect(isAddressLikeContactName({ first_name: 'Joseph', last_name: 'Kiferbaum' })).toBe(false)
  })

  it('does not flag LLCs as address-like', () => {
    expect(isAddressLikeContactName({ first_name: 'Kdg Avondale', last_name: 'LLC' })).toBe(false)
  })
})

describe('isGenericOwnerName', () => {
  it('recognizes listing placeholders without classifying real people', () => {
    expect(isGenericOwnerName('FSBO')).toBe(true)
    expect(isGenericOwnerName('For Sale By Owner +')).toBe(true)
    expect(isGenericOwnerName('Current Resident')).toBe(true)
    expect(isGenericOwnerName('N/A')).toBe(true)
    expect(isGenericOwnerName('NA')).toBe(true)
    expect(isGenericOwnerName('Joseph Kiferbaum')).toBe(false)
    expect(isGenericOwnerName('Jane Na')).toBe(false)
    expect(isGenericOwnerName('Na Zhang')).toBe(false)
    expect(isGenericOwnerName('Bank of America, N.A.')).toBe(false)
  })
})

describe('rankOwnersForDisplay / primaryOwnerDisplayName', () => {
  const addressLike = makeContact({
    id: 1,
    first_name: '3508SACRAMENTO',
    last_name: 'MAYNARD',
    is_primary: true,
  })
  const person = makeContact({
    id: 2,
    first_name: 'Joseph',
    last_name: 'Kiferbaum',
  })
  const llc = makeContact({
    id: 3,
    first_name: 'Kdg Avondale',
    last_name: 'LLC',
  })

  it('ranks person before LLC before address-like', () => {
    const ranked = rankOwnersForDisplay([addressLike, person, llc])
    expect(ranked.map((c) => c.id)).toEqual([2, 3, 1])
  })

  it('prefers person for sticky-header display name', () => {
    expect(primaryOwnerDisplayName([addressLike, person, llc])).toBe('Joseph Kiferbaum')
  })

  it('falls back to linked organization when no person exists', () => {
    expect(
      primaryOwnerDisplayName([addressLike], null, null, [
        {
          id: 9,
          name: 'Kdg Avondale LLC',
          org_type: 'llc',
          role: 'owner',
          link_id: 1,
        },
      ]),
    ).toBe('Kdg Avondale LLC')
  })
})

describe('ownerDisplayEntries', () => {
  it('labels person Owner, org Company, address-like Also listed', () => {
    const entries = ownerDisplayEntries(
      [
        makeContact({
          id: 1,
          first_name: '3508SACRAMENTO',
          last_name: 'MAYNARD',
          is_primary: true,
        }),
        makeContact({ id: 2, first_name: 'Joseph', last_name: 'Kiferbaum' }),
      ],
      'Joseph',
      'Kiferbaum',
      'Kdg Avondale',
      'LLC',
      [
        {
          id: 10,
          name: 'Kdg Avondale LLC',
          org_type: 'llc',
          role: 'owner',
          link_id: 2,
        },
      ],
    )

    expect(entries).toEqual([
      expect.objectContaining({ label: 'Owner', name: 'Joseph Kiferbaum' }),
      expect.objectContaining({ label: 'Company', name: 'Kdg Avondale LLC' }),
      expect.objectContaining({ label: 'Also listed', name: '3508SACRAMENTO MAYNARD' }),
    ])
  })

  it('merges flat Owner2 LLC as Company when contacts only have the person', () => {
    const entries = ownerDisplayEntries(
      [makeContact({ id: 1, first_name: 'Joseph', last_name: 'Kiferbaum', is_primary: true })],
      'Joseph',
      'Kiferbaum',
      'Kdg Avondale',
      'LLC',
    )

    expect(entries).toEqual([
      expect.objectContaining({ label: 'Owner', name: 'Joseph Kiferbaum' }),
      expect.objectContaining({ label: 'Company', name: 'Kdg Avondale LLC' }),
    ])
  })
})
