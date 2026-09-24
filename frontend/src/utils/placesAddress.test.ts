import { describe, expect, it } from 'vitest'
import {
  extractUnitToken,
  extractUnitTokenFromParts,
  formatUnitSuffix,
  isUnitStyleAddressLine,
  streetLineFromPlacesComponents,
} from './placesAddress'

describe('extractUnitToken', () => {
  it('reads bare letter+digit condo doors', () => {
    expect(extractUnitToken('717 West Bittersweet Place L2')).toBe('l2')
  })

  it('reads apt/unit markers', () => {
    expect(extractUnitToken('2553 N Drake Ave Apt 1F')).toBe('1f')
    expect(extractUnitToken('100 Main # 30')).toBe('30')
  })

  it('ignores building-only streets', () => {
    expect(extractUnitToken('717 West Bittersweet Place')).toBe('')
  })
})

describe('extractUnitTokenFromParts', () => {
  it('falls back to address line 2', () => {
    expect(extractUnitTokenFromParts('717 W Bittersweet Pl', 'Unit L2')).toBe('l2')
  })

  it('prefers street when both present', () => {
    expect(extractUnitTokenFromParts('717 W Bittersweet Pl Apt 3', 'Unit L2')).toBe('3')
  })
})

describe('isUnitStyleAddressLine', () => {
  it('treats apt/unit lines as situs line 2', () => {
    expect(isUnitStyleAddressLine('Unit L2')).toBe(true)
    expect(isUnitStyleAddressLine('Apt 3')).toBe(true)
  })

  it('treats full secondary streets as additional address', () => {
    expect(isUnitStyleAddressLine('456 Secondary Ave Chicago IL 60618')).toBe(false)
    expect(isUnitStyleAddressLine('2041 W Cuyler Ave')).toBe(false)
  })
})

describe('streetLineFromPlacesComponents', () => {
  it('includes subpremise from Places', () => {
    const line = streetLineFromPlacesComponents([
      { long_name: '717', types: ['street_number'] },
      { long_name: 'West Bittersweet Place', types: ['route'] },
      { long_name: 'L2', types: ['subpremise'] },
    ])
    expect(line).toBe('717 West Bittersweet Place L2')
  })

  it('preserves a typed unit when Places omits subpremise', () => {
    const line = streetLineFromPlacesComponents(
      [
        { long_name: '717', types: ['street_number'] },
        { long_name: 'West Bittersweet Place', types: ['route'] },
      ],
      { priorStreet: '717 West Bittersweet Place L2 Chicago, Illinois, 60613' },
    )
    expect(line).toBe('717 West Bittersweet Place Unit L2')
  })

  it('does not double-append when street already has the unit', () => {
    const line = streetLineFromPlacesComponents(
      [
        { long_name: '717', types: ['street_number'] },
        { long_name: 'West Bittersweet Place', types: ['route'] },
        { long_name: 'L2', types: ['subpremise'] },
      ],
      { priorStreet: '717 West Bittersweet Place L2' },
    )
    expect(line).toBe('717 West Bittersweet Place L2')
  })
})

describe('formatUnitSuffix', () => {
  it('uppercases the token', () => {
    expect(formatUnitSuffix('l2')).toBe('Unit L2')
  })
})
