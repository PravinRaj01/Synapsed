import { useSyncExternalStore } from 'react'

const QUERY = '(min-width: 640px)'

function subscribe(onChange: () => void) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const list = window.matchMedia(QUERY)
  list.addEventListener('change', onChange)
  return () => list.removeEventListener('change', onChange)
}

/** True on screens at least 640px wide. Where the browser cannot tell (tests), assume a desktop. */
export function useWide(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => (typeof window === 'undefined' || !window.matchMedia ? true : window.matchMedia(QUERY).matches),
    () => true,
  )
}
