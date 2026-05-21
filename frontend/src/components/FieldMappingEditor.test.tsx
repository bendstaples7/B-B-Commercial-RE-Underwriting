import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import {
  FieldMappingEditor,
  validateMapping,
} from './FieldMappingEditor'

const SAMPLE_HEADERS = ['Address', 'Owner', 'Last Name', 'Type', 'Beds', 'Baths']

const SAMPLE_AUTO_MAPPING: Record<string, string> = {
  Address: 'property_street',
  Owner: 'owner_first_name',
  'Last Name': 'owner_last_name',
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

/**
 * Helper: open an MUI Select dropdown in jsdom by finding the combobox
 * trigger inside the data-testid wrapper and firing mouseDown on it.
 */
function openSelect(header: string) {
  const wrapper = screen.getByTestId(`select-${header}`)
  const trigger = within(wrapper).getByRole('combobox')
  fireEvent.mouseDown(trigger)
}

describe('FieldMappingEditor', () => {
  let onMappingChange: ReturnType<typeof vi.fn>

  beforeEach(() => {
    onMappingChange = vi.fn()
  })

  // ---- Rendering ----

  it('renders all headers with dropdown selectors', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={{}}
        onMappingChange={onMappingChange}
      />,
    )

    for (const header of SAMPLE_HEADERS) {
      expect(screen.getByText(header)).toBeInTheDocument()
      expect(screen.getByTestId(`select-${header}`)).toBeInTheDocument()
    }
  })

  it('renders the section heading', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={{}}
        onMappingChange={onMappingChange}
      />,
    )

    expect(screen.getByText('Map Sheet Columns to Database Fields')).toBeInTheDocument()
  })

  // ---- Auto-mapped fields pre-selected ----

  it('shows auto-mapped fields pre-selected in dropdowns', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    const addressWrapper = screen.getByTestId('select-Address')
    expect(addressWrapper).toHaveTextContent('Property Street')

    const ownerWrapper = screen.getByTestId('select-Owner')
    expect(ownerWrapper).toHaveTextContent('Owner First Name')
  })

  it('does not show Required chips when no fields are required', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    expect(screen.queryByText('Required')).not.toBeInTheDocument()
  })

  // ---- Changing a mapping ----

  it('calls onMappingChange when a mapping is changed', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    openSelect('Type')

    const listbox = screen.getByRole('listbox')
    const propertyTypeOption = within(listbox).getByText('Property Type')
    fireEvent.click(propertyTypeOption)

    expect(onMappingChange).toHaveBeenCalledWith({
      Address: 'property_street',
      Owner: 'owner_first_name',
      'Last Name': 'owner_last_name',
      Type: 'property_type',
    })
  })

  it('calls onMappingChange with field removed when Skip is selected', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    openSelect('Address')

    const listbox = screen.getByRole('listbox')
    const skipOption = within(listbox).getByText('— Skip —')
    fireEvent.click(skipOption)

    expect(onMappingChange).toHaveBeenCalledWith({
      Owner: 'owner_first_name',
      'Last Name': 'owner_last_name',
    })
  })

  // ---- Required field validation warning ----

  it('does not show validation warning since no fields are required', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={{}}
        onMappingChange={onMappingChange}
      />,
    )

    expect(screen.queryByRole('alert', { name: 'Required fields warning' })).not.toBeInTheDocument()
  })

  it('does not show validation warning when all required fields are mapped', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    expect(screen.queryByLabelText('Required fields warning')).not.toBeInTheDocument()
  })

  it('does not show validation warning when showValidation is false', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={{}}
        onMappingChange={onMappingChange}
        showValidation={false}
      />,
    )

    expect(screen.queryByLabelText('Required fields warning')).not.toBeInTheDocument()
  })

  // ---- Already-used db fields disabled in other dropdowns ----

  it('disables already-used database fields in other dropdowns', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    openSelect('Type')

    const listbox = screen.getByRole('listbox')
    const propertyStreetOption = within(listbox).getByText('Property Street')
    const ownerNameOption = within(listbox).getByText('Owner First Name')

    expect(propertyStreetOption.closest('li')).toHaveAttribute('aria-disabled', 'true')
    expect(ownerNameOption.closest('li')).toHaveAttribute('aria-disabled', 'true')

    const propertyTypeOption = within(listbox).getByText('Property Type')
    expect(propertyTypeOption.closest('li')).not.toHaveAttribute('aria-disabled', 'true')
  })

  // ---- Reset to auto-map ----

  it('resets mapping to auto-map when reset button is clicked', async () => {
    const customMapping = {
      Address: 'property_street',
      Owner: 'owner_first_name',
      'Last Name': 'owner_last_name',
      Type: 'property_type',
      Beds: 'bedrooms',
    }

    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={customMapping}
        onMappingChange={onMappingChange}
        autoMapping={SAMPLE_AUTO_MAPPING}
      />,
    )

    await user.click(screen.getByLabelText('Reset mapping to auto-map'))

    expect(onMappingChange).toHaveBeenCalledWith({
      Address: 'property_street',
      Owner: 'owner_first_name',
      'Last Name': 'owner_last_name',
    })
  })

  it('resets mapping to empty when no autoMapping is provided', async () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    await user.click(screen.getByLabelText('Reset mapping to auto-map'))

    expect(onMappingChange).toHaveBeenCalledWith({})
  })

  it('has an icon button for reset as well', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={{}}
        onMappingChange={onMappingChange}
      />,
    )

    expect(screen.getByLabelText('Reset to auto-map')).toBeInTheDocument()
  })

  // ---- Disabled state ----

  it('disables all dropdowns when disabled prop is true', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
        disabled
      />,
    )

    for (const header of SAMPLE_HEADERS) {
      const selectRoot = screen.getByTestId(`select-${header}`)
      expect(selectRoot).toHaveClass('Mui-disabled')
    }
  })

  it('disables reset buttons when disabled prop is true', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={{}}
        onMappingChange={onMappingChange}
        disabled
      />,
    )

    expect(screen.getByLabelText('Reset to auto-map')).toBeDisabled()
    expect(screen.getByLabelText('Reset mapping to auto-map')).toBeDisabled()
  })

  // ---- Duplicate prevention: already-used fields disabled ----

  it('shows already-used fields as disabled in other header dropdowns', () => {
    render(
      <FieldMappingEditor
        headers={SAMPLE_HEADERS}
        mapping={SAMPLE_AUTO_MAPPING}
        onMappingChange={onMappingChange}
      />,
    )

    openSelect('Owner')

    const listbox = screen.getByRole('listbox')
    const propStreetOption = within(listbox).getByText('Property Street')
    expect(propStreetOption.closest('li')).toHaveAttribute('aria-disabled', 'true')
  })
})

// ---- validateMapping helper ----

describe('validateMapping', () => {
  it('returns valid=true when fields are mapped', () => {
    const result = validateMapping({
      col1: 'property_street',
      col2: 'owner_first_name',
      col3: 'owner_last_name',
    })
    expect(result.valid).toBe(true)
    expect(result.missingRequired).toEqual([])
  })

  it('returns valid=true even without property_street', () => {
    const result = validateMapping({
      col1: 'owner_first_name',
      col2: 'owner_last_name',
    })
    expect(result.valid).toBe(true)
    expect(result.missingRequired).toEqual([])
  })

  it('returns valid=true even without owner_first_name', () => {
    const result = validateMapping({
      col1: 'property_street',
      col2: 'owner_last_name',
    })
    expect(result.valid).toBe(true)
    expect(result.missingRequired).toEqual([])
  })

  it('returns valid=true for empty mapping (no required fields)', () => {
    const result = validateMapping({})
    expect(result.valid).toBe(true)
    expect(result.missingRequired).toEqual([])
  })

  it('returns valid=true even with empty string values', () => {
    const result = validateMapping({
      col1: '',
      col2: 'owner_first_name',
      col3: 'owner_last_name',
    })
    expect(result.valid).toBe(true)
    expect(result.missingRequired).toEqual([])
  })

  it('returns valid=true with extra optional fields mapped', () => {
    const result = validateMapping({
      col1: 'property_street',
      col2: 'owner_first_name',
      col3: 'owner_last_name',
      col4: 'bedrooms',
      col5: 'property_type',
    })
    expect(result.valid).toBe(true)
    expect(result.missingRequired).toEqual([])
  })
})
