import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'

// Needs a signed-in account whose active campaign has been analysed (the demo sandbox is enough).
const email = process.env.E2E_EMAIL
const password = process.env.E2E_PASSWORD

async function openBoard(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email!)
  await page.getByLabel('Password').fill(password!)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 })
  await page.getByRole('link', { name: 'Roadmap', exact: true }).click()
  await page.getByRole('tab', { name: 'Roadmap board' }).click()
  await expect(page).toHaveURL(/\/roadmap\?tab=board$/)
  await expect(page.getByRole('region', { name: /^Now:/ })).toBeVisible({ timeout: 30_000 })
}

const column = (page: Page, name: string) => page.getByRole('region', { name: new RegExp(`^${name}:`) })
const cards = (page: Page, name: string) => column(page, name).getByRole('button', { name: /^Open / })

test.describe('roadmap board', () => {
  test.skip(!email || !password, 'E2E_EMAIL and E2E_PASSWORD are not set')

  test('drag a card to another column, and it stays there after a reload', async ({ page, isMobile }) => {
    test.skip(isMobile, 'dragging is for a mouse; a phone uses the card menu, below')
    await openBoard(page)
    await page.screenshot({ path: 'test-results/board-1.png', fullPage: true })

    const before = await cards(page, 'Now').count()
    const laterBefore = await cards(page, 'Later').count()
    expect(before).toBeGreaterThanOrEqual(1)
    const card = cards(page, 'Now').first()
    const title = (await card.getAttribute('aria-label'))!.replace('Open ', '')

    // A real drag with the mouse: down on the card, move over the Later column in steps, release.
    const from = (await card.boundingBox())!
    const to = (await column(page, 'Later').boundingBox())!
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(from.x + from.width / 2 + 20, from.y + from.height / 2 + 10, { steps: 5 })
    await page.mouse.move(to.x + to.width / 2, to.y + 80, { steps: 20 })
    await page.screenshot({ path: 'test-results/board-2-dragging.png' })
    await page.mouse.up()

    await expect(cards(page, 'Later').filter({ hasText: title })).toHaveCount(1)
    await expect(cards(page, 'Later')).toHaveCount(laterBefore + 1)
    await expect(cards(page, 'Now')).toHaveCount(before - 1)
    await expect(page.getByText('Moved to Later.')).toBeVisible()

    await page.reload()
    await expect(cards(page, 'Later').filter({ hasText: title })).toHaveCount(1, { timeout: 30_000 })

    // And back, with the menu.
    await page.getByRole('button', { name: `Move ${title}` }).click()
    await page.getByRole('menuitem', { name: 'Now' }).click()
    await expect(cards(page, 'Now').filter({ hasText: title })).toHaveCount(1)
    await expect(cards(page, 'Later')).toHaveCount(laterBefore)
  })

  test('on a phone a card moves with its menu', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'the desktop test drags')
    await openBoard(page)
    const card = cards(page, 'Now').first()
    const title = (await card.getAttribute('aria-label'))!.replace('Open ', '')
    await page.getByRole('button', { name: `Move ${title}` }).click()
    await page.getByRole('menuitem', { name: 'Next' }).click()
    await expect(cards(page, 'Next').filter({ hasText: title })).toHaveCount(1)
    await page.screenshot({ path: 'test-results/board-phone.png', fullPage: true })
    await page.getByRole('button', { name: `Move ${title}` }).click()
    await page.getByRole('menuitem', { name: 'Now' }).click()
    await expect(cards(page, 'Now').filter({ hasText: title })).toHaveCount(1)
  })

  test('edit a card, write its PRD from the evidence, download and print it, delete it', async ({ page, isMobile }) => {
    test.setTimeout(240_000)
    await openBoard(page)
    const card = cards(page, 'Now').first()
    const title = (await card.getAttribute('aria-label'))!.replace('Open ', '')
    await card.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Title')).toHaveValue(title)

    // Change ease; ICE follows and survives a reload.
    const ease = dialog.getByRole('slider', { name: 'Ease' })
    const was = Number(await ease.inputValue())
    await ease.focus()
    await page.keyboard.press(was < 10 ? 'ArrowRight' : 'ArrowLeft')
    await dialog.getByRole('button', { name: 'Save changes' }).click()
    await expect(page.getByText('Saved.')).toBeVisible()

    // A PRD written from the theme's evidence by a live model.
    await dialog.getByRole('button', { name: /Write a PRD|Write a new version/ }).click()
    await expect(dialog.getByText(/Reading the evidence and writing the PRD/)).toBeVisible()
    await expect(dialog.getByRole('article')).toBeVisible({ timeout: 120_000 }) // the PRD itself (the panel's own title is also a heading)
    await expect(dialog.getByText('User stories')).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Evidence' })).toBeVisible()
    await page.screenshot({ path: `test-results/board-prd${isMobile ? '-phone' : ''}.png`, fullPage: true })

    const download = page.waitForEvent('download')
    await dialog.getByRole('button', { name: 'Markdown' }).click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(/-prd\.md$/)
    const md = fs.readFileSync((await file.path())!, 'utf8')
    expect(md.startsWith('#')).toBe(true)

    // Printing shows the PRD and nothing else.
    await page.evaluate(() => { document.body.dataset.printing = 'prd' })
    await page.emulateMedia({ media: 'print' })
    await expect(page.locator('#prd-print')).toBeVisible()
    await expect(page.getByRole('banner')).toBeHidden()
    await expect(page.getByRole('dialog')).toBeHidden()
    await page.screenshot({ path: 'test-results/board-print.png', fullPage: true })
    await page.emulateMedia({ media: 'screen' })
    await page.evaluate(() => { delete document.body.dataset.printing })

    // Delete this version.
    await dialog.getByRole('button', { name: 'Delete this version' }).click()
    await dialog.getByRole('button', { name: 'Yes, delete' }).click()
    await expect(page.getByText('Version deleted.')).toBeVisible()
  })
})
