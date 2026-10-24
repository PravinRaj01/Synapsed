import { cn } from '@/lib/cn'

/** The Synapsed mark: a white S on an emerald rounded square, with the wordmark beside it. */
export function Logo({ className, showName = true }: { className?: string; showName?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span className="grid size-9 place-items-center rounded-xl bg-accent-gradient text-white shadow-card">
        <svg viewBox="0 0 64 64" className="size-5" fill="none" stroke="currentColor" strokeWidth="7" strokeLinecap="round" aria-hidden>
          <path d="M42 20c-2-3-6-5-11-5-7 0-11 3-11 8 0 12 22 6 22 18 0 5-4 8-11 8-6 0-10-2-12-6" />
        </svg>
      </span>
      {showName && <span className="text-base font-semibold tracking-tight text-ink">Synapsed</span>}
    </span>
  )
}
