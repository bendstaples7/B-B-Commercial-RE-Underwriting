import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '@/test/testUtils'
import { CaptureSourceFields } from '@/components/CaptureSourceFields'
import dealSourcesApi from '@/services/dealSourcesApi'

vi.mock('@/services/dealSourcesApi', () => ({
  default: {
    list: vi.fn(),
    create: vi.fn(),
  },
}))

describe('CaptureSourceFields', () => {
  beforeEach(() => {
    vi.mocked(dealSourcesApi.list).mockResolvedValue([
      { name: 'Driving For Dollars', is_builtin: true },
      { name: 'Referral', is_builtin: true },
      { name: 'Direct Mail', is_builtin: true },
    ])
    vi.mocked(dealSourcesApi.create).mockResolvedValue({
      name: 'Facebook Ad',
      is_builtin: false,
      created: true,
    })
  })

  it('loads catalog options and supports adding a new source', async () => {
    const user = userEvent.setup()
    const onSourceChange = vi.fn()
    const onContextChange = vi.fn()

    render(
      <CaptureSourceFields
        source="Driving For Dollars"
        onSourceChange={onSourceChange}
        context=""
        onContextChange={onContextChange}
      />,
    )

    await waitFor(() => {
      expect(dealSourcesApi.list).toHaveBeenCalled()
    })

    fireEvent.mouseDown(screen.getByLabelText('Source'))
    fireEvent.click(await screen.findByTestId('capture-source-add-new'))

    const input = await screen.findByTestId('capture-source-new-input')
    await user.type(input, 'Facebook Ad')
    await user.click(screen.getByTestId('capture-source-save-new'))

    await waitFor(() => {
      expect(dealSourcesApi.create).toHaveBeenCalledWith('Facebook Ad')
      expect(onSourceChange).toHaveBeenCalledWith('Facebook Ad')
    })
  })
})
