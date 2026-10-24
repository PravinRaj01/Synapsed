import { Moon, Sun } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useTheme } from '@/stores/theme'

/** The sun/moon switch. Both themes use the same tokens, so this only flips data-theme. */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      className={cn('grid size-10 place-items-center rounded-xl text-muted transition-colors hover:bg-inner hover:text-ink', className)}
    >
      {dark ? <Sun className="size-5" aria-hidden /> : <Moon className="size-5" aria-hidden />}
    </button>
  )
}
