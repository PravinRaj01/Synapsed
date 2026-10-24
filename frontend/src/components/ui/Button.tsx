import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const button = cva(
  'inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-ink text-ink-contrast hover:opacity-90',
        secondary: 'bg-inner text-ink hover:bg-line',
        ghost: 'text-muted hover:bg-inner hover:text-ink',
        accent: 'bg-accent-gradient text-white hover:opacity-90',
      },
      size: { sm: 'h-8 px-3 text-xs', md: 'h-10 px-5 text-sm', lg: 'h-12 px-6 text-sm' },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

type Props = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button> & { loading?: boolean }

export function Button({ className, variant, size, loading, disabled, children, ...rest }: Props) {
  return (
    <button className={cn(button({ variant, size }), className)} disabled={disabled || loading} {...rest}>
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

/** A 40 px round icon button, like the search and bell buttons in the reference top bar. */
export function IconButton({ className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        'grid size-10 place-items-center rounded-full border border-line bg-card text-ink shadow-card transition-transform hover:-translate-y-0.5',
        className,
      )}
      {...rest}
    />
  )
}
