import { expect, test } from '@playwright/test'
import fs from 'node:fs'

// Needs a signed-in account whose active campaign has been analysed (the demo sandbox is enough).
const email = process.env.E2E_EMAIL
const password = process.env.E2E_PASSWORD

test.describe('problem space report', () => {
  test.skip(!email || !password, 'E2E_EMAIL and E2E_PASSWORD are not set')

  test('rank, read the evidence, see who raises what, export', async ({ page, isMobile }) => {
    test.setTimeout(120_000)
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 })

    await page.getByRole('link', { name: 'Roadmap', exact: true }).click()
    await expect(page).toHaveURL(/\/roadmap$/)
    await expect(page.getByText(/themes?, ranked by/)).toBeVisible({ timeout: 30_000 })
    const rows = page.locator('li > button[aria-expanded]')
    await expect(rows.first()).toBeVisible()
    const count = await rows.count()
    expect(count).toBeGreaterThanOrEqual(2)
    await page.screenshot({ path: `test-results/roadmap-1-report${isMobile ? '-phone' : ''}.png`, fullPage: true })

    // Ranking by mentions changes the order, or at least keeps every theme.
    const withoutRank = (texts: string[]) => texts.map((t) => t.replace(/^\d+\s*/, '')).sort() // the rank is the one thing that moves
    const before = withoutRank(await rows.allInnerTexts())
    await page.getByRole('tab', { name: 'Mentions' }).click()
    expect(await rows.count()).toBe(count)
    expect(withoutRank(await rows.allInnerTexts())).toEqual(before)

    // Open one theme: what customers were doing, and their own words.
    await rows.first().click()
    await expect(page.locator('blockquote').first()).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: `test-results/roadmap-2-theme${isMobile ? '-phone' : ''}.png`, fullPage: true })

    // The heatmap writes its numbers.
    const heat = page.getByRole('table', { name: 'Pain points by theme and customer segment' })
    await expect(heat).toBeVisible()
    await expect(heat.getByRole('columnheader').first()).toHaveText('Theme')
    await expect(heat.getByRole('cell').first()).toHaveText(/^(\d+|–)$/)

    if (isMobile) return // downloads and print are checked on desktop

    // CSV: opens in Excel as UTF-8, one row per theme.
    const csv = page.waitForEvent('download')
    await page.getByRole('button', { name: /CSV/ }).click()
    const csvFile = await csv
    expect(csvFile.suggestedFilename()).toMatch(/-themes\.csv$/)
    const bytes = fs.readFileSync((await csvFile.path())!)
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf])
    const lines = bytes.toString('utf8').replace(/^﻿/, '').trimEnd().split('\r\n')
    expect(lines[0]).toMatch(/^Rank,Theme,Description,Business impact/)
    expect(lines.length).toBe(count + 1)

    const md = page.waitForEvent('download')
    await page.getByRole('button', { name: /Markdown/ }).click()
    const mdText = fs.readFileSync((await (await md).path())!, 'utf8')
    expect(mdText).toContain('# Problem space report:')
    expect(mdText).toContain('## 1.')

    // Print: the navigation goes away and the report stays.
    await page.emulateMedia({ media: 'print' })
    await expect(page.getByRole('banner')).toBeHidden()
    await expect(page.getByRole('heading', { name: /Problem space report:/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /CSV/ })).toBeHidden()
    await page.screenshot({ path: 'test-results/roadmap-3-print.png', fullPage: true })
  })
})
