import { expect, test } from '@playwright/test'

// Needs a signed-in account whose active campaign has been analysed (the demo sandbox is enough).
const email = process.env.E2E_EMAIL
const password = process.env.E2E_PASSWORD

test.describe('insights studio', () => {
  test.skip(!email || !password, 'E2E_EMAIL and E2E_PASSWORD are not set')

  test('the matrix and the dashboard are drawn, tables match, and a chart can be asked for', async ({ page, isMobile }) => {
    test.setTimeout(150_000)
    const suffix = isMobile ? '-phone' : ''
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))

    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 })

    await page.getByRole('link', { name: 'Roadmap', exact: true }).click()
    await page.getByRole('tab', { name: 'Insights Studio' }).click()
    await expect(page).toHaveURL(/\/roadmap\?tab=insights$/)
    await expect(page.getByRole('heading', { name: 'Opportunity matrix' })).toBeVisible({ timeout: 30_000 })

    // Charts are really drawn: marks in the SVG, not an empty frame.
    const dots = page.locator('.recharts-scatter circle')
    await expect(dots.first()).toBeVisible({ timeout: 30_000 })
    const themes = page.getByRole('list', { name: 'Themes in the matrix' }).getByRole('listitem')
    expect(await dots.count()).toBe(await themes.count()) // a numbered dot for every theme listed under the chart
    expect(await dots.count()).toBeGreaterThanOrEqual(2)
    await expect(page.getByRole('heading', { name: 'Themes by Business Impact' })).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.recharts-bar-rectangle').first()).toBeVisible()
    expect(await page.locator('.recharts-wrapper').count()).toBeGreaterThanOrEqual(5)
    await page.screenshot({ path: `test-results/insights-1-light${suffix}.png`, fullPage: true })

    // Table view of a stacked chart: the same numbers with a total.
    const sentiment = page.getByRole('heading', { name: 'Sentiment by customer segment' }).locator('xpath=ancestor::div[contains(@class,"rounded-card")][1]')
    // The legend is there exactly when there is more than one series (the campaign in use may only have negative feedback).
    await sentiment.getByRole('tab', { name: 'Table' }).click()
    const columns = await sentiment.getByRole('columnheader').count() // the category, each series, and a Total for a stack
    await expect(sentiment.getByRole('columnheader', { name: 'Total' })).toBeVisible()
    await sentiment.getByRole('tab', { name: 'Chart' }).click()
    if (columns - 2 > 1) await expect(sentiment.getByRole('list', { name: 'Legend' })).toBeVisible()
    else await expect(sentiment.getByRole('list', { name: 'Legend' })).toHaveCount(0)

    // The dark theme keeps the charts readable.
    await page.getByRole('button', { name: 'Account menu' }).click()
    const toggle = page.getByRole('menuitem', { name: /theme/i })
    if (await toggle.isVisible()) await toggle.click()
    else {
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: 'Switch to dark theme' }).click()
    }
    await page.waitForTimeout(500)
    await page.screenshot({ path: `test-results/insights-2-dark${suffix}.png`, fullPage: true })

    // Ask for a chart in words. The model is live, so it may occasionally decline a perfectly good request: ask again once.
    const asked = page.getByText(/You asked: “Sentiment by segment/)
    for (let attempt = 0; attempt < 2 && !(await asked.isVisible()); attempt++) {
      await page.getByRole('button', { name: 'Sentiment by segment as a stacked bar' }).click()
      await expect(asked.or(page.getByRole('alert'))).toBeVisible({ timeout: 90_000 })
    }
    await expect(asked).toBeVisible()
    await page.screenshot({ path: `test-results/insights-3-asked${suffix}.png` })
    expect(errors, 'no uncaught errors in the page').toEqual([])
  })
})
