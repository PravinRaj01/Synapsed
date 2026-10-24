import { motion, useReducedMotion } from 'motion/react'
import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** One grey block that shimmers. Shaped by its className; hidden from screen readers (the wrapper says "Loading"). */
export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn('skeleton rounded-inner', className)} {...rest} />
}

/** Lines of text, the last one shorter, as a paragraph that has not arrived yet. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div aria-hidden className={cn('space-y-2.5', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn('h-3', i === lines - 1 && lines > 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}

/** A card-shaped frame for placeholders; the surface is real, the contents are blocks. */
export function SkeletonCard({ className, children }: { className?: string; children?: ReactNode }) {
  return <div aria-hidden className={cn('rounded-card border border-line bg-card p-6 shadow-card', className)}>{children}</div>
}

/**
 * Wraps a placeholder so it is announced once as "Loading ..." (role=status) and marked busy, whatever shapes are inside.
 * The shapes should look like the content that is coming, so the page does not jump when it arrives.
 */
export function Loading({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div role="status" aria-label={label} aria-busy="true" className={className}>
      {children}
    </div>
  )
}

/** Content arriving: it fades in and rises a few pixels. With reduced motion it simply appears. */
export function FadeIn({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduced = useReducedMotion()
  return (
    <motion.div className={className} initial={reduced ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28, ease: 'easeOut', delay }}>
      {children}
    </motion.div>
  )
}

// ---------------------------------------------------------------- shapes for each kind of page

/** A row of KPI cards. */
export function StatCardsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <SkeletonCard key={i} className="h-[132px]">
          <div className="flex items-start justify-between">
            <div className="space-y-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-4 w-20 rounded-full" />
            </div>
            <Skeleton className="size-10 rounded-full" />
          </div>
        </SkeletonCard>
      ))}
    </div>
  )
}

/** Rows with a round marker, a title and a line under it: lists of sources, themes, results. */
export function RowsSkeleton({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div aria-hidden className={cn('divide-y divide-line', className)}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 py-4">
          <Skeleton className="size-9 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <Skeleton className="h-6 w-20 shrink-0 rounded-full" />
        </div>
      ))}
    </div>
  )
}

/** A card holding rows: a table or list that is loading. */
export function ListCardSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <SkeletonCard className="py-2">
      <RowsSkeleton rows={rows} />
    </SkeletonCard>
  )
}

/** A chart card: a title, a line under it, and bars of different lengths. */
export function ChartCardSkeleton({ className }: { className?: string }) {
  const widths = ['w-11/12', 'w-4/5', 'w-3/5', 'w-2/3', 'w-2/5']
  return (
    <SkeletonCard className={cn('h-80', className)}>
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="mt-2 h-3 w-1/2" />
      <div className="mt-8 space-y-4">
        {widths.map((w, i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-3 w-16 shrink-0" />
            <Skeleton className={cn('h-4', w)} />
          </div>
        ))}
      </div>
    </SkeletonCard>
  )
}

/** The Roadmap board: three columns with a few cards each. */
export function BoardSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      {[3, 2, 2].map((cards, c) => (
        <SkeletonCard key={c} className="space-y-3 bg-inner p-4">
          <Skeleton className="h-4 w-20" />
          {Array.from({ length: cards }, (_, i) => (
            <div key={i} className="space-y-3 rounded-inner bg-card p-4">
              <Skeleton className="h-3.5 w-4/5" />
              <Skeleton className="h-3 w-1/2" />
              <div className="flex gap-2">
                <Skeleton className="h-5 w-12 rounded-full" />
                <Skeleton className="h-5 w-16 rounded-full" />
              </div>
            </div>
          ))}
        </SkeletonCard>
      ))}
    </div>
  )
}

/** A panel of text, such as a document or a PRD. */
export function DocumentSkeleton() {
  return (
    <div aria-hidden className="space-y-6 p-1">
      <Skeleton className="h-6 w-2/3" />
      <SkeletonText lines={4} />
      <Skeleton className="h-5 w-1/4" />
      <SkeletonText lines={3} />
      <SkeletonText lines={5} />
    </div>
  )
}
