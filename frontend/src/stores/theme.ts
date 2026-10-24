import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark'

type ThemeState = { theme: Theme; toggle: () => void; set: (theme: Theme) => void }

/** The theme the page already has: index.html sets data-theme before first paint. */
function initial(): Theme {
  if (typeof document === 'undefined') return 'light'
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

export const useTheme = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: initial(),
      toggle: () => get().set(get().theme === 'dark' ? 'light' : 'dark'),
      set: (theme) => {
        document.documentElement.dataset.theme = theme
        set({ theme })
      },
    }),
    { name: 'synapsed-theme', partialize: (s) => ({ theme: s.theme }) },
  ),
)
