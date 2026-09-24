import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  PropertyAddressEditDialog,
  splitStreetAndAddress2,
} from './PropertyAddressEditDialog'

describe('splitStreetAndAddress2', () => {
  it('keeps an existing address_2 and leaves street alone', () => {
    expect(splitStreetAndAddress2('717 W Bittersweet Pl', 'Unit L2')).toEqual({
      street: '717 W Bittersweet Pl',
      address2: 'Unit L2',
    })
  })

  it('peels a trailing unit off the street when line 2 is empty', () => {
    expect(splitStreetAndAddress2('717 W Bittersweet Pl Unit L2', null)).toEqual({
      street: '717 W Bittersweet Pl',
      address2: 'Unit L2',
    })
  })
})

describe('PropertyAddressEditDialog', () => {
  it('exposes Address line 2 and saves address_2', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(
      <PropertyAddressEditDialog
        open
        row={{
          id: 1,
          property_street: '717 W Bittersweet Pl',
          address_2: null,
          property_city: 'Chicago',
          property_state: 'IL',
          property_zip: '60613',
        }}
        onClose={vi.fn()}
        onSave={onSave}
        saveLabel="Save address"
      />,
    )

    expect(screen.getByTestId('property-address-line2-input')).toBeInTheDocument()
    await user.clear(screen.getByTestId('property-address-line2-input'))
    await user.type(screen.getByTestId('property-address-line2-input'), 'Unit L2')
    await user.click(screen.getByTestId('property-address-save'))

    expect(onSave).toHaveBeenCalledWith({
      property_street: '717 W Bittersweet Pl',
      address_2: 'Unit L2',
      property_city: 'Chicago',
      property_state: 'IL',
      property_zip: '60613',
    })
  })
})
