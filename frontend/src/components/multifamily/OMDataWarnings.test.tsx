/**
 * Tests for OMDataWarnings component.
 *
 * Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OMDataWarnings } from './OMDataWarnings'

describe('OMDataWarnings', () => {
  // ---------------------------------------------------------------------------
  // Null / empty cases
  // ---------------------------------------------------------------------------

  it('renders nothing when warnings is null', () => {
    const { container } = render(<OMDataWarnings warnings={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when warnings is undefined', () => {
    const { container } = render(<OMDataWarnings warnings={undefined} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when warnings is an empty array', () => {
    const { container } = render(<OMDataWarnings warnings={[]} />)
    expect(container.firstChild).toBeNull()
  })

  // ---------------------------------------------------------------------------
  // Section title
  // ---------------------------------------------------------------------------

  it('renders the "Data Warnings" heading when warnings are present', () => {
    render(
      <OMDataWarnings
        warnings={[{ type: 'unit_count_mismatch_warning', computed: 10, stated: 12, delta: 2 }]}
      />
    )
    expect(screen.getByText('Data Warnings')).toBeInTheDocument()
  })

  // ---------------------------------------------------------------------------
  // unit_count_mismatch_warning (Req 10.1)
  // ---------------------------------------------------------------------------

  it('renders unit_count_mismatch_warning with correct message', () => {
    render(
      <OMDataWarnings
        warnings={[{ type: 'unit_count_mismatch_warning', computed: 10, stated: 12, delta: 2 }]}
      />
    )
    expect(
      screen.getByText(/Unit count mismatch: sum of unit mix rows \(10\) ≠ stated unit count \(12\), delta: 2/)
    ).toBeInTheDocument()
  })

  // ---------------------------------------------------------------------------
  // noi_consistency_warning (Req 10.2)
  // ---------------------------------------------------------------------------

  it('renders noi_consistency_warning with currency-formatted values', () => {
    render(
      <OMDataWarnings
        warnings={[
          {
            type: 'noi_consistency_warning',
            computed: 100000,
            stated: 105000,
            delta: 5000,
          },
        ]}
      />
    )
    const alert = screen.getByText(/NOI inconsistency/)
    expect(alert).toBeInTheDocument()
    // Should contain currency-formatted numbers
    expect(alert.textContent).toContain('$100,000')
    expect(alert.textContent).toContain('$105,000')
    expect(alert.textContent).toContain('$5,000')
  })

  // ---------------------------------------------------------------------------
  // cap_rate_consistency_warning (Req 10.3)
  // ---------------------------------------------------------------------------

  it('renders cap_rate_consistency_warning with percentage-formatted values', () => {
    render(
      <OMDataWarnings
        warnings={[
          {
            type: 'cap_rate_consistency_warning',
            computed: 0.065,
            stated: 0.07,
            delta: 0.005,
          },
        ]}
      />
    )
    const alert = screen.getByText(/Cap rate inconsistency/)
    expect(alert).toBeInTheDocument()
    expect(alert.textContent).toContain('6.50%')
    expect(alert.textContent).toContain('7.00%')
    expect(alert.textContent).toContain('0.50%')
  })

  // ---------------------------------------------------------------------------
  // grm_consistency_warning (Req 10.4)
  // ---------------------------------------------------------------------------

  it('renders grm_consistency_warning with decimal-formatted values', () => {
    render(
      <OMDataWarnings
        warnings={[
          {
            type: 'grm_consistency_warning',
            computed: 12.34,
            stated: 13.0,
            delta: 0.66,
          },
        ]}
      />
    )
    const alert = screen.getByText(/GRM inconsistency/)
    expect(alert).toBeInTheDocument()
    expect(alert.textContent).toContain('12.34')
    expect(alert.textContent).toContain('13.00')
    expect(alert.textContent).toContain('0.66')
  })

  // ---------------------------------------------------------------------------
  // insufficient_data_warning (Req 10.8)
  // ---------------------------------------------------------------------------

  it('renders insufficient_data_warning with field and reason', () => {
    render(
      <OMDataWarnings
        warnings={[
          {
            type: 'insufficient_data_warning',
            field: 'cap_rate',
            reason: 'asking_price is null',
          },
        ]}
      />
    )
    expect(
      screen.getByText(/Insufficient data for cap_rate check: asking_price is null/)
    ).toBeInTheDocument()
  })

  // ---------------------------------------------------------------------------
  // unmatched_expense_items (Req 7.6)
  // ---------------------------------------------------------------------------

  it('renders unmatched_expense_items with comma-separated labels', () => {
    render(
      <OMDataWarnings
        warnings={[
          {
            type: 'unmatched_expense_items',
            items: [{ label: 'Landscaping' }, { label: 'Pest Control' }],
          },
        ]}
      />
    )
    expect(
      screen.getByText(/Unrecognized expense labels: Landscaping, Pest Control/)
    ).toBeInTheDocument()
  })

  // ---------------------------------------------------------------------------
  // Multiple warnings
  // ---------------------------------------------------------------------------

  it('renders multiple warnings as separate Alert components', () => {
    render(
      <OMDataWarnings
        warnings={[
          { type: 'unit_count_mismatch_warning', computed: 10, stated: 12, delta: 2 },
          { type: 'noi_consistency_warning', computed: 100000, stated: 105000, delta: 5000 },
        ]}
      />
    )
    expect(screen.getByText(/Unit count mismatch/)).toBeInTheDocument()
    expect(screen.getByText(/NOI inconsistency/)).toBeInTheDocument()
    // Both should be warning severity alerts
    const alerts = screen.getAllByRole('alert')
    expect(alerts).toHaveLength(2)
  })

  // ---------------------------------------------------------------------------
  // Fallback for unknown warning type
  // ---------------------------------------------------------------------------

  it('renders a fallback message for unknown warning types', () => {
    render(
      <OMDataWarnings
        warnings={[{ type: 'some_future_warning_type' }]}
      />
    )
    expect(screen.getByText(/Warning: some_future_warning_type/)).toBeInTheDocument()
  })

  it('renders the message field for unknown warnings that have one', () => {
    render(
      <OMDataWarnings
        warnings={[{ message: 'Something went sideways' }]}
      />
    )
    expect(screen.getByText('Something went sideways')).toBeInTheDocument()
  })
})
