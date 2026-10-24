import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** The class for text inputs and selects: the pale pill used on the sign-in page. */
export const inputClass =
  'h-11 w-full rounded-full border border-line bg-inner px-4 text-sm text-ink outline-none placeholder:text-muted focus:border-accent'

/** A labelled form control with an optional hint and an error message underneath. */
export function Field({ label, hint, error, children, className }: { label: string; hint?: string; error?: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('block', className)}>
      <label className="block">
        <span className="mb-1.5 block px-1 text-sm font-medium text-ink">{label}</span>
        {children}
      </label>
      {hint && !error && <p className="mt-1 px-2 text-xs text-muted">{hint}</p>}
      {error && (
        <p role="alert" className="mt-1 px-2 text-xs text-negative">
          {error}
        </p>
      )}
    </div>
  )
}
