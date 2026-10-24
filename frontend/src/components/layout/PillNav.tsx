import { motion } from 'motion/react'
import { NavLink } from 'react-router'
import { cn } from '@/lib/cn'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/vault', label: 'Vault' },
  { to: '/chat', label: 'Chat' },
  { to: '/roadmap', label: 'Roadmap' },
  { to: '/laboratory', label: 'Laboratory' },
] as const

/** The page navigation: a white pill container whose active item is a solid ink pill that slides between pages. */
export function PillNav() {
  return (
    <nav aria-label="Main" className="max-w-full overflow-x-auto rounded-full border border-line bg-card p-1 shadow-card">
      <ul className="flex items-center gap-1">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} className={({ isActive }) => cn('relative block rounded-full px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors', isActive ? 'text-ink-contrast' : 'text-muted hover:text-ink')}>
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full bg-ink" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />
                  )}
                  <span className="relative">{item.label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
