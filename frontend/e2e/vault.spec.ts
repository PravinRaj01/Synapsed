import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

// Needs a signed-in account that already has a workspace. The journey makes its own empty campaign.
const email = process.env.E2E_EMAIL
const password = process.env.E2E_PASSWORD
const fixture = (name: string) => ({ name, mimeType: 'text/plain', buffer: fs.readFileSync(path.join(import.meta.dirname, 'fixtures', name)) })

test.describe('knowledge vault', () => {
  test.skip(!email || !password, 'E2E_EMAIL and E2E_PASSWORD are not set')
  test.skip(({ isMobile }) => isMobile, 'the long journey runs on desktop; the layout is checked on a phone in the screenshots test')

  test('add sources, review and approve them, run the analysis, read the pain points', async ({ page }) => {
    test.setTimeout(240_000)
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/(dashboard|onboarding)$/, { timeout: 30_000 })

    // An empty campaign of our own.
    await page.goto('/onboarding')
    await page.getByLabel('Campaign name').fill(`Vault e2e ${Date.now()}`)
    await page.getByRole('button', { name: 'Continue' }).click()
    await page.getByRole('button', { name: /Upload my own data/ }).click()
    await expect(page).toHaveURL(/\/vault$/, { timeout: 30_000 })
    await expect(page.getByRole('heading', { name: 'No sources yet' })).toBeVisible()

    // Add two files and a bad one, plus a pasted note.
    await page.getByRole('button', { name: 'Add sources' }).first().click()
    await page.getByLabel('Choose files').setInputFiles([
      fixture('interview-finance.txt'),
      fixture('ticket-export.txt'),
      { name: 'archive.zip', mimeType: 'application/zip', buffer: Buffer.from('PK') },
    ])
    await expect(page.getByText('.zip files are not supported')).toBeVisible()
    await page.getByRole('button', { name: 'Add 2 files' }).click()
    await expect(page.getByRole('img', { name: 'Added' }).or(page.getByLabel('Added'))).toHaveCount(2, { timeout: 90_000 })
    await page.screenshot({ path: 'test-results/vault-1-added.png' })

    await page.getByRole('tab', { name: 'Paste text' }).click()
    await page.getByLabel('Title').fill('Call with a mid-market customer')
    await page.getByLabel('Text', { exact: true }).fill('Our bank connection drops every couple of weeks and we only notice when a payment is missing from the ledger. Reconnecting means logging in with the bank again every single time, which is really annoying.')
    await page.getByRole('button', { name: 'Add note' }).click()
    await expect(page.getByText(/characters/).first()).toBeVisible({ timeout: 60_000 })
    await page.keyboard.press('Escape')

    // Three sources awaiting approval.
    await expect(page.getByRole('tab', { name: /Sources \(3\)/ })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Awaiting approval')).toHaveCount(3)
    await page.screenshot({ path: 'test-results/vault-2-table.png', fullPage: true })

    // Read one, approve it from the viewer.
    await page.getByRole('button', { name: /^Interview-finance|interview-finance/i }).first().click()
    await expect(page.getByTestId('source-text')).toContainText('three days')
    await page.screenshot({ path: 'test-results/vault-3-viewer.png' })
    await page.getByRole('button', { name: /Approve and embed/ }).click()
    await expect(page.getByText('Approved and ready to analyse.').first()).toBeVisible({ timeout: 60_000 })
    await page.keyboard.press('Escape')

    // Approve the rest in one go.
    await page.getByLabel('Select all sources').check()
    await page.getByRole('button', { name: /Approve 2/ }).click()
    await expect(page.getByText('Approved 2 sources.')).toBeVisible({ timeout: 120_000 })
    await expect(page.getByText('Approved', { exact: true })).toHaveCount(3)

    // Analyse.
    await expect(page.getByText('3 approved sources are ready to be analysed.')).toBeVisible()
    await page.getByRole('button', { name: 'Run analysis' }).click()
    await expect(page.getByRole('list', { name: 'Analysis steps' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText(/sources? analysed/)).toBeVisible({ timeout: 180_000 })
    await expect(page.getByText('Everything approved has been analysed.')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: 'test-results/vault-4-analysed.png', fullPage: true })

    // Pain points, with the customers' own words, and the highlight in the source.
    await page.getByRole('tab', { name: 'Pain points' }).click()
    const firstTheme = page.getByRole('button', { expanded: false }).filter({ hasText: /mentions?/ }).first()
    await firstTheme.click()
    await expect(page.locator('blockquote').first()).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: 'test-results/vault-5-painpoints.png', fullPage: true })
    await page.locator('blockquote button').first().click()
    await expect(page.locator('[data-testid="source-text"] mark').first()).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: 'test-results/vault-6-highlight.png' })
  })
})
