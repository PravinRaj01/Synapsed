import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Lightbulb } from 'lucide-react'
import { useState } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ getSession: vi.fn() }))
vi.mock('@/lib/auth', () => ({ authClient: auth, getAccessToken: vi.fn(), clearAccessToken: vi.fn() }))

import { RequireAuth } from './layout/RequireAuth'
import { PillNav } from './layout/PillNav'
import { Button } from './ui/Button'
import { Chip } from './ui/Chip'
import { SegmentedControl } from './ui/SegmentedControl'
import { StatsCard } from './ui/StatsCard'

describe('StatsCard', () => {
  it('shows the title, the value and an upward change in the positive colour', () => {
    render(<StatsCard title="Insights found" value="1,284" change={12} icon={Lightbulb} />)
    expect(screen.getByText('Insights found')).toBeInTheDocument()
    expect(screen.getByText('1,284')).toBeInTheDocument()
    expect(screen.getByText('12%').closest('span')).toHaveClass('text-positive')
  })

  it('shows a fall in the negative colour, without a minus sign in the chip', () => {
    render(<StatsCard title="Anomalies" value="3" change={-5} icon={Lightbulb} />)
    expect(screen.getByText('5%').closest('span')).toHaveClass('text-negative')
  })

  it('shows no change as a plain 0%, neither up nor down', () => {
    render(<StatsCard title="Sources" value="10" change={0} icon={Lightbulb} />)
    const chip = screen.getByText('0%').closest('span')!
    expect(chip).toHaveClass('text-muted')
    expect(chip.querySelector('svg')).toBeNull()
  })

  it('hides the chip when there is no previous period, and styles the hero card', () => {
    const { container } = render(<StatsCard hero title="Critical" value="9" icon={Lightbulb} hint="vs last month" />)
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
    expect(screen.getByText('vs last month')).toBeInTheDocument()
    expect(container.firstChild).toHaveClass('bg-accent-gradient')
  })

  it('counts a number up to its value', async () => {
    render(<StatsCard title="Sources" value={42} icon={Lightbulb} />)
    expect(await screen.findByText('42', {}, { timeout: 3000 })).toBeInTheDocument()
  })
})

describe('SegmentedControl', () => {
  function Harness() {
    const [value, setValue] = useState<'a' | 'b'>('a')
    return <SegmentedControl label="View" value={value} onChange={setValue} options={[{ value: 'a', label: 'Alpha' }, { value: 'b', label: 'Beta' }]} />
  }

  it('marks the active option and switches when another is clicked', async () => {
    render(<Harness />)
    expect(screen.getByRole('tab', { name: 'Alpha' })).toHaveAttribute('aria-selected', 'true')
    await userEvent.setup().click(screen.getByRole('tab', { name: 'Beta' }))
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Alpha' })).toHaveAttribute('aria-selected', 'false')
  })
})

describe('Button and Chip', () => {
  it('disables itself and shows progress while loading', () => {
    render(<Button loading>Save</Button>)
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('merges a caller class over the default', () => {
    render(<Button className="h-12">Go</Button>)
    expect(screen.getByRole('button')).toHaveClass('h-12')
    expect(screen.getByRole('button')).not.toHaveClass('h-10')
  })

  it('uses the tone colours', () => {
    render(<Chip tone="warning">Staged</Chip>)
    expect(screen.getByText('Staged')).toHaveClass('text-warning')
  })
})

describe('PillNav', () => {
  it('lists every page and marks the current one', () => {
    render(
      <MemoryRouter initialEntries={['/roadmap']}>
        <PillNav />
      </MemoryRouter>,
    )
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual(['Dashboard', 'Vault', 'Chat', 'Roadmap', 'Laboratory'])
    expect(within(nav).getByRole('link', { name: 'Roadmap' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Vault' })).not.toHaveAttribute('aria-current')
  })
})

describe('RequireAuth', () => {
  beforeEach(() => auth.getSession.mockReset())

  function renderAt(path: string) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/login" element={<p>Sign in page</p>} />
            <Route element={<RequireAuth />}>
              <Route path="/vault" element={<p>Vault page</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('sends a signed-out visitor to sign in', async () => {
    auth.getSession.mockResolvedValue({ data: null })
    renderAt('/vault')
    expect(await screen.findByText('Sign in page')).toBeInTheDocument()
  })

  it('lets a signed-in user through', async () => {
    auth.getSession.mockResolvedValue({ data: { user: { id: 'u', name: 'Maya', email: 'm@x.io' } } })
    renderAt('/vault')
    expect(await screen.findByText('Vault page')).toBeInTheDocument()
  })

  it('shows a loading state while it finds out', () => {
    let release: (v: unknown) => void = () => {}
    auth.getSession.mockReturnValue(new Promise((resolve) => (release = resolve)))
    renderAt('/vault')
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
    release({ data: null })
  })
})
