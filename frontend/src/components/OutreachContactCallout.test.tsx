import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { OutreachContactCallout, OutreachContactInline } from './OutreachContactCallout'
import type { OutreachContact } from '@/types'

const user = userEvent.setup({ pointerEventsCheck: 0 })

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('navigator', {
    ...navigator,
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})

describe('OutreachContactCallout', () => {
  it('renders nothing when contact is null', () => {
    const { container } = render(<OutreachContactCallout contact={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders phone link in full mode', () => {
    const contact: OutreachContact = {
      channel: 'phone',
      label: 'Call',
      value: '5551234567',
      display: '(555) 123-4567',
      href: 'tel:+15551234567',
    }
    render(<OutreachContactCallout contact={contact} />)

    expect(screen.getByTestId('outreach-contact-callout')).toBeInTheDocument()
    expect(screen.getByText('Call')).toBeInTheDocument()
    const link = screen.getByTestId('outreach-contact-link')
    expect(link).toHaveTextContent('(555) 123-4567')
    expect(link).toHaveAttribute('href', 'tel:+15551234567')
  })

  it('renders email mailto link', () => {
    const contact: OutreachContact = {
      channel: 'email',
      label: 'Email',
      value: 'owner@example.com',
      display: 'owner@example.com',
      href: 'mailto:owner@example.com',
    }
    render(<OutreachContactCallout contact={contact} />)

    const link = screen.getByTestId('outreach-contact-link')
    expect(link).toHaveAttribute('href', 'mailto:owner@example.com')
  })

  it('renders mailing address lines', () => {
    const contact: OutreachContact = {
      channel: 'direct_mail',
      label: 'Direct Mail',
      value: '123 Main St — Springfield, IL 62701',
      display: '123 Main St — Springfield, IL 62701',
      lines: ['123 Main St', 'Springfield, IL 62701'],
    }
    render(<OutreachContactCallout contact={contact} />)

    expect(screen.getByText('123 Main St')).toBeInTheDocument()
    expect(screen.getByText('Springfield, IL 62701')).toBeInTheDocument()
  })

  it('copies phone on copy button click', async () => {
    const contact: OutreachContact = {
      channel: 'phone',
      label: 'Call',
      value: '5551234567',
      display: '(555) 123-4567',
      href: 'tel:+15551234567',
    }
    render(<OutreachContactCallout contact={contact} />)

    const copyBtn = screen.getByTestId('outreach-contact-copy')
    expect(copyBtn).toHaveAttribute('aria-label', 'Copy phone contact')
    await user.click(copyBtn)
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('+15551234567')
  })

  it('swallows clipboard write failures without throwing', async () => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    const contact: OutreachContact = {
      channel: 'email',
      label: 'Email',
      value: 'owner@example.com',
      display: 'owner@example.com',
      href: 'mailto:owner@example.com',
    }
    render(<OutreachContactCallout contact={contact} />)
    await user.click(screen.getByTestId('outreach-contact-copy'))
    expect(screen.getByTestId('outreach-contact-copy')).toHaveAttribute(
      'aria-label',
      'Copy email contact',
    )
  })

  it('renders compact mode without copy button', () => {
    const contact: OutreachContact = {
      channel: 'phone',
      label: 'Call',
      value: '5551234567',
      display: '(555) 123-4567',
      href: 'tel:+15551234567',
    }
    render(<OutreachContactCallout contact={contact} compact />)

    expect(screen.getByTestId('outreach-contact-callout')).toBeInTheDocument()
    expect(screen.queryByTestId('outreach-contact-copy')).not.toBeInTheDocument()
  })
})

describe('OutreachContactInline', () => {
  it('renders inline phone link with outreach-contact-inline test id', () => {
    const contact: OutreachContact = {
      channel: 'phone',
      label: 'Call',
      value: '5551234567',
      display: '(555) 123-4567',
      href: 'tel:+15551234567',
    }
    render(<OutreachContactInline contact={contact} />)

    expect(screen.getByTestId('outreach-contact-inline')).toBeInTheDocument()
    expect(screen.getByTestId('outreach-contact-link')).toHaveTextContent('(555) 123-4567')
    expect(screen.queryByTestId('outreach-contact-callout')).not.toBeInTheDocument()
  })

  it('copies phone digits via the inline copy control', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })

    const contact: OutreachContact = {
      channel: 'phone',
      label: 'Call',
      value: '(555) 123-4567',
      display: '(555) 123-4567',
      href: 'tel:+15551234567',
    }
    render(<OutreachContactInline contact={contact} />)

    await user.click(screen.getByTestId('outreach-contact-copy'))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalled()
    })
    const copied = writeText.mock.calls[0][0] as string
    expect(copied.replace(/\D/g, '')).toContain('5551234567')
  })
})
