import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** The base surface: white rounded card with a hairline border and a soft shadow. */
export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-card border border-line bg-card p-6 shadow-card', className)} {...rest} />
}

/** A tile nested inside a card (the wallet tiles and offers in the reference). */
export function InnerCard({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-inner bg-inner p-4', className)} {...rest} />
}

export function CardTitle({ className, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-base font-semibold text-ink', className)} {...rest} />
}
