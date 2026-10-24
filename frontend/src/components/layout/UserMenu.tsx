import * as Menu from '@radix-ui/react-dropdown-menu'
import { ChevronDown, LogOut, Moon, Sun } from 'lucide-react'
import { initials, useSession, useSignOut } from '@/lib/session'
import { useTheme } from '@/stores/theme'

/** The signed-in user chip in the top bar, with theme and sign-out. */
export function UserMenu() {
  const { data: user } = useSession()
  const signOut = useSignOut()
  const { theme, toggle } = useTheme()
  if (!user) return null
  return (
    <Menu.Root>
      <Menu.Trigger className="flex h-10 items-center gap-3 rounded-full border border-line bg-card py-1 pr-3 pl-1 shadow-card" aria-label="Account menu">
        <span className="grid size-8 place-items-center rounded-full bg-accent-gradient text-xs font-semibold text-white">{initials(user)}</span>
        <span className="hidden text-left leading-tight lg:block">
          <span className="block max-w-36 truncate text-sm font-medium text-ink">{user.name}</span>
          <span className="block max-w-36 truncate text-xs text-muted">{user.email}</span>
        </span>
        <ChevronDown className="size-4 text-muted" aria-hidden />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={8} className="z-50 min-w-56 rounded-card border border-line bg-card p-2 shadow-lift">
          <div className="px-3 py-2">
            <p className="truncate text-sm font-medium text-ink">{user.name}</p>
            <p className="truncate text-xs text-muted">{user.email}</p>
          </div>
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Item onSelect={toggle} className="flex cursor-pointer items-center gap-2 rounded-inner px-3 py-2 text-sm text-ink outline-none data-[highlighted]:bg-inner lg:hidden">
            {theme === 'dark' ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
            {theme === 'dark' ? 'Light theme' : 'Dark theme'}
          </Menu.Item>
          <Menu.Item onSelect={() => signOut.mutate()} className="flex cursor-pointer items-center gap-2 rounded-inner px-3 py-2 text-sm text-negative outline-none data-[highlighted]:bg-inner">
            <LogOut className="size-4" aria-hidden />
            Sign out
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
