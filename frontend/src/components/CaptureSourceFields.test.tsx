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
  let catalog: Array<{ name: string; is_builtin: boolean; created?: boolean }>

  beforeEach(() => {
    catalog = [
      { name: 'Driving For Dollars', is_builtin: true },
      { name: 'Referral', is_builtin: true },
      { name: 'Direct Mail', is_builtin: true },
    ]
    vi.mocked(dealSourcesApi.list).mockImplementation(async () => catalog)
    vi.mocked(dealSourcesApi.create).mockImplementation(async (name: string) => {
      const created = {
        name,
        is_builtin: false,
        created: true,
      }
      catalog = [...catalog, created]
      return created
    })
  })

  it('loads catalog options and persists a new source on subsequent opens', async () => {
    const user = userEvent.setup()
    const onSourceChange = vi.fn()
    const onContextChange = vi.fn()

    const { unmount } = render(
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

    // After create, the optimistic cache / refetch should expose the new option.
    vi.mocked(dealSourcesApi.list).mockResolvedValue([
      { name: 'Driving For Dollars', is_builtin: true },
      { name: 'Referral', is_builtin: true },
      { name: 'Direct Mail', is_builtin: true },
      { name: 'Facebook Ad', is_builtin: false },
    ])

    unmount()
    render(
      <CaptureSourceFields
        source="Facebook Ad"
        onSourceChange={onSourceChange}
        context=""
        onContextChange={onContextChange}
      />,
    )

    await waitFor(() => {
      expect(dealSourcesApi.list).toHaveBeenCalled()
    })

    fireEvent.mouseDown(screen.getByLabelText('Source'))
    expect(await screen.findByTestId('capture-source-option-Facebook Ad')).toBeInTheDocument()
  })

  it('surfaces create Error.message when add fails', async () => {
    const user = userEvent.setup()
    vi.mocked(dealSourcesApi.create).mockRejectedValue(new Error('Source name is required'))

    render(
      <CaptureSourceFields
        source="Driving For Dollars"
        onSourceChange={vi.fn()}
        context=""
        onContextChange={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(dealSourcesApi.list).toHaveBeenCalled()
    })

    fireEvent.mouseDown(screen.getByLabelText('Source'))
    fireEvent.click(await screen.findByTestId('capture-source-add-new'))
    await user.type(await screen.findByTestId('capture-source-new-input'), 'x')
    await user.click(screen.getByTestId('capture-source-save-new'))

    await waitFor(() => {
      expect(screen.getByText('Source name is required')).toBeInTheDocument()
    })
  })
})
