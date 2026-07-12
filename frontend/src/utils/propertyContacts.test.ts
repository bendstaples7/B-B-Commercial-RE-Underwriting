import { describe, expect, it } from 'vitest'

import { isEntityContactName } from './propertyContacts'

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
