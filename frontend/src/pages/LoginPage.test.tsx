/**
 * LoginPage.test.tsx
 *
 * Tests for the LoginPage component.
 * Covers: form rendering, client-side validation, 401 error handling,
 * success redirect, and credential preservation on error.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.4, 7.7
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { LoginPage } from './LoginPage'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal AuthContext mock — overridable per test. */
const mockLogin = vi.fn()

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ login: mockLogin }),
}))

function renderLoginPage(initialPath = '/login', locationState?: unknown) {
  return render(
    <MemoryRouter
      initialEntries={[{ pathname: initialPath, state: locationState }]}
    >
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div data-testid="home-page">Home</div>} />
        <Route path="/leads" element={<div data-testid="leads-page">Leads</div>} />
      </Routes>
    </MemoryRouter>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LoginPage', () => {
  beforeEach(() => {
    mockLogin.mockReset()
  })

  // -------------------------------------------------------------------------
  // Rendering (Req 7.2)
  // -------------------------------------------------------------------------

  it('renders email field, password field, and submit button', () => {
    renderLoginPage()

    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('does not show any error alert on initial render', () => {
    renderLoginPage()

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Client-side validation (Req 7.7)
  // -------------------------------------------------------------------------

  it('shows email validation error and does not call login when email is empty', async () => {
    renderLoginPage()

    await userEvent.type(screen.getByLabelText(/password/i), 'secret')
    fireEvent.submit(screen.getByRole('button', { name: /sign in/i }).closest('form')!)

    expect(await screen.findByText(/email is required/i)).toBeInTheDocument()
    expect(mockLogin).not.toHaveBeenCalled()
  })

  it('shows password validation error and does not call login when password is empty', async () => {
    renderLoginPage()

    await userEvent.type(screen.getByLabelText(/email address/i), 'user@example.com')
    fireEvent.submit(screen.getByRole('button', { name: /sign in/i }).closest('form')!)

    expect(await screen.findByText(/password is required/i)).toBeInTheDocument()
    expect(mockLogin).not.toHaveBeenCalled()
  })

  it('shows both validation errors when both fields are empty', async () => {
    renderLoginPage()

    fireEvent.submit(screen.getByRole('button', { name: /sign in/i }).closest('form')!)

    expect(await screen.findByText(/email is required/i)).toBeInTheDocument()
    expect(screen.getByText(/password is required/i)).toBeInTheDocument()
    expect(mockLogin).not.toHaveBeenCalled()
  })

  it('clears email validation error when user starts typing in email field', async () => {
    renderLoginPage()

    // Trigger validation error
    fireEvent.submit(screen.getByRole('button', { name: /sign in/i }).closest('form')!)
    expect(await screen.findByText(/email is required/i)).toBeInTheDocument()

    // Start typing — error should clear
    await userEvent.type(screen.getByLabelText(/email address/i), 'a')
    expect(screen.queryByText(/email is required/i)).not.toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // 401 error handling (Req 7.4)
  // -------------------------------------------------------------------------

  it('shows generic error message on 401 and does NOT clear credentials', async () => {
    const error = Object.assign(new Error('Unauthorized'), {
      response: { status: 401 },
    })
    mockLogin.mockRejectedValueOnce(error)

    renderLoginPage()

    await userEvent.type(screen.getByLabelText(/email address/i), 'user@example.com')
    await userEvent.type(screen.getByLabelText(/password/i), 'wrongpassword')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    // Generic error message shown
    expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument()

    // Credentials are preserved (Req 7.4)
    expect(screen.getByLabelText(/email address/i)).toHaveValue('user@example.com')
    expect(screen.getByLabelText(/password/i)).toHaveValue('wrongpassword')
  })

  it('does not reveal which field was wrong in the 401 error message', async () => {
    const error = Object.assign(new Error('Unauthorized'), {
      response: { status: 401 },
    })
    mockLogin.mockRejectedValueOnce(error)

    renderLoginPage()

    await userEvent.type(screen.getByLabelText(/email address/i), 'unknown@example.com')
    await userEvent.type(screen.getByLabelText(/password/i), 'anypassword')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    const alert = await screen.findByRole('alert')
    // Must not mention "email" or "password" specifically as the wrong field
    expect(alert.textContent).not.toMatch(/email.*wrong|password.*wrong|wrong.*email|wrong.*password/i)
    expect(alert.textContent).toMatch(/invalid email or password/i)
  })

  it('shows a generic unexpected error message for non-401 errors', async () => {
    const error = Object.assign(new Error('Server Error'), {
      response: { status: 500 },
    })
    mockLogin.mockRejectedValueOnce(error)

    renderLoginPage()

    await userEvent.type(screen.getByLabelText(/email address/i), 'user@example.com')
    await userEvent.type(screen.getByLabelText(/password/i), 'password')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByText(/an unexpected error occurred/i)).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Success redirect (Req 7.3)
  // -------------------------------------------------------------------------

  it('redirects to "/" on successful login when no location.state.from is set', async () => {
    mockLogin.mockResolvedValueOnce(undefined)

    renderLoginPage()

    await userEvent.type(screen.getByLabelText(/email address/i), 'user@example.com')
    await userEvent.type(screen.getByLabelText(/password/i), 'correctpassword')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByTestId('home-page')).toBeInTheDocument()
    })
  })

  it('redirects to location.state.from (string) on successful login', async () => {
    mockLogin.mockResolvedValueOnce(undefined)

    renderLoginPage('/login', { from: '/leads' })

    await userEvent.type(screen.getByLabelText(/email address/i), 'user@example.com')
    await userEvent.type(screen.getByLabelText(/password/i), 'correctpassword')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByTestId('leads-page')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  it('disables the submit button while the login request is in flight', async () => {
    // login never resolves during this test
    mockLogin.mockReturnValueOnce(new Promise(() => {}))

    renderLoginPage()

    await userEvent.type(screen.getByLabelText(/email address/i), 'user@example.com')
    await userEvent.type(screen.getByLabelText(/password/i), 'password')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    // After click, the button should be disabled (aria-label changes to "Signing in…")
    await waitFor(() => {
      const btn = screen.getByRole('button')
      expect(btn).toBeDisabled()
    })
  })

  // -------------------------------------------------------------------------
  // Accessibility
  // -------------------------------------------------------------------------

  it('email field is marked as required', () => {
    renderLoginPage()
    expect(screen.getByLabelText(/email address/i)).toBeRequired()
  })

  it('password field is marked as required', () => {
    renderLoginPage()
    expect(screen.getByLabelText(/password/i)).toBeRequired()
  })
})
