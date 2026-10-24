import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BoardSkeleton, ChartCardSkeleton, FadeIn, ListCardSkeleton, Loading, RowsSkeleton, Skeleton, SkeletonText, StatCardsSkeleton } from './Skeleton'

describe('Loading', () => {
  it('announces a single "Loading" status and marks the area busy, whatever shapes are inside', () => {
    render(
      <Loading label="Loading your dashboard">
        <StatCardsSkeleton />
        <ListCardSkeleton />
      </Loading>,
    )
    const status = screen.getByRole('status', { name: 'Loading your dashboard' })
    expect(status).toHaveAttribute('aria-busy', 'true')
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  it('hides every placeholder shape from screen readers', () => {
    const { container } = render(
      <Loading label="Loading">
        <Skeleton data-testid="block" />
        <SkeletonText lines={2} />
        <RowsSkeleton rows={2} />
        <ChartCardSkeleton />
        <BoardSkeleton />
      </Loading>,
    )
    expect(screen.getByTestId('block')).toHaveAttribute('aria-hidden', 'true')
    // everything inside the status wrapper is either aria-hidden itself or inside something that is
    const visibleToReaders = [...container.querySelectorAll('.skeleton')].filter((el) => !el.closest('[aria-hidden="true"]'))
    expect(visibleToReaders).toEqual([])
  })
})

describe('the shapes', () => {
  it('draw the number of placeholders asked for', () => {
    const { container, rerender } = render(<StatCardsSkeleton count={3} />)
    expect(container.querySelectorAll('.h-\\[132px\\]')).toHaveLength(3)
    rerender(<SkeletonText lines={4} />)
    expect(container.querySelectorAll('.skeleton')).toHaveLength(4)
    rerender(<RowsSkeleton rows={6} />)
    expect(container.querySelectorAll('.divide-y > div')).toHaveLength(6)
  })
  it('make the last line of text shorter than the others, but a single line full width', () => {
    const { container, rerender } = render(<SkeletonText lines={3} />)
    const lines = [...container.querySelectorAll('.skeleton')]
    expect(lines.map((l) => l.className.includes('w-2/3'))).toEqual([false, false, true])
    rerender(<SkeletonText lines={1} />)
    expect(container.querySelector('.skeleton')?.className).toContain('w-full')
  })
  it('lay the board out as three columns', () => {
    const { container } = render(<BoardSkeleton />)
    expect(container.querySelector('.lg\\:grid-cols-3')?.children).toHaveLength(3)
  })
})

describe('FadeIn', () => {
  it('shows its content', () => {
    render(<FadeIn>Hello, content</FadeIn>)
    expect(screen.getByText('Hello, content')).toBeInTheDocument()
  })
})
