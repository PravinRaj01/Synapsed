import { useSyncExternalStore } from 'react'

/** Whether a media query matches. Where the browser cannot tell (tests), assume a big screen. */
function useMedia(query: string): boolean {
  const subscribe = (onChange: () => void) => {
    if (typeof window === 'undefined' || !window.matchMedia) return () => {}
    const list = window.matchMedia(query)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }
  return useSyncExternalStore(
    subscribe,
    () => (typeof window === 'undefined' || !window.matchMedia ? true : window.matchMedia(query).matches),
    () => true,
  )
}

/** At least 640px wide: room for a table. */
export const useWide = () => useMedia('(min-width: 640px)')

/** At least 1280px wide: room for three side-by-side panes. */
export const useExtraWide = () => useMedia('(min-width: 1280px)')
