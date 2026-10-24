import { AnimatePresence, motion } from 'motion/react'
import { LogOut } from 'lucide-react'
import { Outlet, useLocation } from 'react-router'
import { useSignOut } from '@/lib/session'
import { CampaignScope } from './CampaignScope'
import { Logo } from './Logo'
import { PillNav } from './PillNav'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'

/** The frame around every signed-in page: top bar, left icon rail, and the page itself with a fade between pages. */
export function AppShell() {
  const location = useLocation()
  const signOut = useSignOut()
  return (
    <div className="min-h-dvh bg-canvas">
      <header className="sticky top-0 z-40 border-b border-line/60 bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
          <Logo />
          <div className="order-last w-full sm:order-none sm:w-auto sm:flex-1 sm:flex sm:justify-center">
            <PillNav />
          </div>
          <div className="ml-auto flex items-center gap-3">
            <CampaignScope />
            <UserMenu />
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1600px]">
        <aside className="sticky top-[73px] hidden h-[calc(100dvh-73px)] w-[72px] shrink-0 flex-col items-center justify-between py-6 lg:flex" aria-label="Quick actions">
          <ThemeToggle />
          <button
            type="button"
            onClick={() => signOut.mutate()}
            aria-label="Sign out"
            className="grid size-10 place-items-center rounded-xl text-muted transition-colors hover:bg-inner hover:text-ink"
          >
            <LogOut className="size-5" aria-hidden />
          </button>
        </aside>

        <main className="min-w-0 flex-1 px-4 pt-6 pb-16 sm:px-6 lg:pl-2">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={location.pathname} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  )
}
