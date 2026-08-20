/**
 * First-paint settle for the same-address merge banner + dialog.
 */
import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { SameAddressMergeBanner } from '@/components/lead-detail/SameAddressMergeBanner'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    mergeInto: vi.fn(),
    getMergePreview: vi.fn(),
  },
}))

describe('first-paint settle — same-address merge banner', () => {
  it('command center header stack mounts banner; dialog has Combine landmark', () => {
    const ulcc = readFileSync(
      resolve(__dirname, '../UnifiedLeadCommandCenter.tsx'),
      'utf8',
    )
    const banner = readFileSync(
      resolve(__dirname, './SameAddressMergeBanner.tsx'),
      'utf8',
    )
    expect(ulcc).toContain('data-testid="cc-header-stack"')
    expect(ulcc).toContain('SameAddressMergeBanner')
    expect(ulcc).toContain('property-overview-address-line')
    expect(banner).toContain('data-testid="same-address-merge-banner"')
    expect(banner).toContain('data-testid="same-address-merge-dialog"')
    expect(banner).toContain('Combine these records')
    expect(banner).toMatch(/twins\.length|hasTwins/)
    expect(ulcc).toContain('afterCommandCenterMutation')
    expect(banner).toContain('onMerged')
  })

  it('banner + dialog landmarks settle when twin payload is present', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={1}
          currentOwnerLabel="Current"
          currentPeopleNames={['Current']}
          twins={[
            {
              id: 2,
              property_street: '1 Main',
              owner_display_name: 'Twin',
              people_names: ['Twin'],
            },
          ]}
          onMerged={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('same-address-merge-banner')).toBeInTheDocument()
    await user.click(screen.getByTestId('same-address-merge-open'))
    expect(screen.getByTestId('same-address-merge-dialog')).toHaveTextContent(
      'Combine these records',
    )
  })
})
