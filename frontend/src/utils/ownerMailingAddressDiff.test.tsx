import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  formatOwnerMailingLine,
  renderOriginalMailingWithStrikes,
} from '@/utils/ownerMailingAddressDiff'

describe('formatOwnerMailingLine', () => {
  it('joins street, city, state zip', () => {
    expect(formatOwnerMailingLine({
      street: '3056 N Oakley Ave Ste 1n',
      city: 'Chicago',
      state: 'IL',
      zip: '60603',
    })).toBe('3056 N Oakley Ave Ste 1n, Chicago, IL 60603')
  })
})

describe('renderOriginalMailingWithStrikes', () => {
  it('strikes only parts that differ from corrected', () => {
    render(
      <div data-testid="line">
        {renderOriginalMailingWithStrikes(
          {
            street: '3056 N Oakley Ave Ste 1n',
            city: 'Chicago',
            state: 'Il',
            zip: '60603',
          },
          {
            street: '3056 N Oakley Ave Ste 1n',
            city: 'Chicago',
            state: 'IL',
            zip: '60603',
          },
        )}
      </div>,
    )
    expect(screen.getByTestId('mailing-original-state-struck')).toHaveTextContent('Il')
    expect(screen.queryByTestId('mailing-original-street-struck')).not.toBeInTheDocument()
    expect(screen.getByTestId('mailing-original-street')).toHaveTextContent(
      '3056 N Oakley Ave Ste 1n',
    )
  })
})
