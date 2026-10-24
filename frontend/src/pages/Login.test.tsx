import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({
  getSession: vi.fn(),
  signOut: vi.fn(),
  signIn: { email: vi.fn(), social: vi.fn() },
  signUp: { email: vi.fn() },
  emailOtp: { sendVerificationOtp: vi.fn(), verifyEmail: vi.fn() },
}))
vi.mock('@/lib/auth', () => ({ authClient: auth, getAccessToken: vi.fn(), clearAccessToken: vi.fn() }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }))

import Login from './Login'

const signedOut = { data: null }
const signedIn = { data: { user: { id: 'u1', name: 'Maya Tan', email: 'maya@acme.io' } } }

function renderLogin() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard" element={<p>Dashboard page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  Object.values(auth).forEach((v) => (typeof v === 'function' ? v.mockReset() : Object.values(v).forEach((f) => f.mockReset())))
  auth.getSession.mockResolvedValue(signedOut)
})

async function fill(email: string, password: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Email'), email)
  await user.type(screen.getByLabelText('Password'), password)
  return user
}

describe('sign in', () => {
  it('checks the fields before calling the service', async () => {
    renderLogin()
    const user = await fill('not-an-email', 'short')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Use at least 8 characters')).toBeInTheDocument()
    expect(auth.signIn.email).not.toHaveBeenCalled()
  })

  it('signs in and goes to the dashboard', async () => {
    auth.signIn.email.mockResolvedValue({ error: null })
    auth.getSession.mockResolvedValueOnce(signedOut).mockResolvedValue(signedIn)
    renderLogin()
    const user = await fill('maya@acme.io', 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Dashboard page')).toBeInTheDocument()
    expect(auth.signIn.email).toHaveBeenCalledWith({ email: 'maya@acme.io', password: 'correct-horse' })
  })

  it('shows the service message for a wrong password and stays on the page', async () => {
    auth.signIn.email.mockResolvedValue({ error: { code: 'INVALID_EMAIL_OR_PASSWORD', message: 'Invalid email or password' } })
    renderLogin()
    const user = await fill('maya@acme.io', 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
    expect(screen.queryByText('Dashboard page')).not.toBeInTheDocument()
  })

  it('asks for the emailed code when the address is not verified yet, then continues', async () => {
    auth.signIn.email.mockResolvedValue({ error: { code: 'EMAIL_NOT_VERIFIED', message: 'Email not verified' } })
    auth.emailOtp.sendVerificationOtp.mockResolvedValue({ error: null })
    auth.emailOtp.verifyEmail.mockResolvedValue({ error: null })
    renderLogin()
    const user = await fill('maya@acme.io', 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Check your email')).toBeInTheDocument()
    expect(auth.emailOtp.sendVerificationOtp).toHaveBeenCalledWith({ email: 'maya@acme.io', type: 'email-verification' })
    const verify = screen.getByRole('button', { name: 'Verify and continue' })
    expect(verify).toBeDisabled() // needs a code first

    auth.getSession.mockResolvedValue(signedIn)
    await user.type(screen.getByLabelText('Verification code'), '482913')
    await user.click(verify)
    expect(await screen.findByText('Dashboard page')).toBeInTheDocument()
    expect(auth.emailOtp.verifyEmail).toHaveBeenCalledWith({ email: 'maya@acme.io', otp: '482913' })
  })

  it('shows a wrong code as an error and lets the user go back', async () => {
    auth.signIn.email.mockResolvedValue({ error: { code: 'EMAIL_NOT_VERIFIED', message: 'x' } })
    auth.emailOtp.sendVerificationOtp.mockResolvedValue({ error: null })
    auth.emailOtp.verifyEmail.mockResolvedValue({ error: { message: 'Invalid OTP' } })
    renderLogin()
    const user = await fill('maya@acme.io', 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.type(await screen.findByLabelText('Verification code'), '000000')
    await user.click(screen.getByRole('button', { name: 'Verify and continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid OTP')
    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
  })
})

describe('create account', () => {
  it('signs up with the name and goes straight to the code step', async () => {
    auth.signUp.email.mockResolvedValue({ error: null })
    renderLogin()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: 'Create account' }))
    await user.type(screen.getByLabelText('Your name'), 'Maya Tan')
    await user.type(screen.getByLabelText('Email'), 'maya@acme.io')
    await user.type(screen.getByLabelText('Password'), 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Check your email')).toBeInTheDocument()
    expect(auth.signUp.email).toHaveBeenCalledWith({ name: 'Maya Tan', email: 'maya@acme.io', password: 'correct-horse' })
  })

  it('uses the part of the email before the @ when no name is given', async () => {
    auth.signUp.email.mockResolvedValue({ error: null })
    renderLogin()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: 'Create account' }))
    await user.type(screen.getByLabelText('Email'), 'maya@acme.io')
    await user.type(screen.getByLabelText('Password'), 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(auth.signUp.email).toHaveBeenCalledWith({ name: 'maya', email: 'maya@acme.io', password: 'correct-horse' }))
  })

  it('shows a sign-up refusal (for example an address already in use)', async () => {
    auth.signUp.email.mockResolvedValue({ error: { message: 'User already exists' } })
    renderLogin()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: 'Create account' }))
    await user.type(screen.getByLabelText('Email'), 'maya@acme.io')
    await user.type(screen.getByLabelText('Password'), 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('User already exists')
  })
})

describe('google', () => {
  it('starts Google sign-in and returns to the app afterwards', async () => {
    auth.signIn.social.mockResolvedValue({ error: null })
    renderLogin()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Continue with Google' }))
    expect(auth.signIn.social).toHaveBeenCalledWith({ provider: 'google', callbackURL: `${window.location.origin}/dashboard` })
  })
})

describe('already signed in', () => {
  it('skips the page', async () => {
    auth.getSession.mockResolvedValue(signedIn)
    renderLogin()
    expect(await screen.findByText('Dashboard page')).toBeInTheDocument()
  })
})
