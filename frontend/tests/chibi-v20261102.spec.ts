import { openSettings } from './navigation'
import { test, expect, type APIRequestContext } from '@playwright/test'
import { randomUUID, createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'

const screenshots = path.resolve(process.env.PLAYWRIGHT_SCREENSHOTS_DIR || '../artifacts/release-v041/screenshots', 'chibi')
const hash = 'ff0cff01c5b2790b6a9d50699411691b58f6b18d86d0e3b4d11f63aa6e6a59a1'
let clean: Buffer
async function state(request: APIRequestContext) { return (await request.get('/api/state')).json() }
async function mutate(request: APIRequestContext, endpoint: string, data: object) {
  const snapshot = await state(request)
  const response = await request.post('/api/' + endpoint, { data: { request_id: randomUUID(), expected_version: snapshot.home.version, ...data } })
  expect(response.ok(), await response.text()).toBe(true)
  return response.json()
}
test.beforeAll(async ({ request }) => {
  clean = await (await request.get('/api/archives/export')).body()
  await fs.mkdir(screenshots, { recursive: true })
})
test.afterAll(async ({ request }) => {
  expect((await request.post('/api/archives/import', { multipart: { file: { name: 'clean.json', mimeType: 'application/json', buffer: clean } } })).ok()).toBe(true)
})
test.beforeEach(async ({ page, request }) => {
  expect((await request.post('/api/archives/import', { multipart: { file: { name: 'clean.json', mimeType: 'application/json', buffer: clean } } })).ok()).toBe(true)
  const snapshot = await state(request)
  await mutate(request, 'settings', { settings: { ...snapshot.home.settings, provider_id: '', autonomous_enabled: false, character_style: 'chibi', chibi_asset: null, portrait_asset: null } })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByTestId('room')).toBeVisible()
})

test('new chibi is served in both states, undistorted and grounded in all three locations', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  for (const name of ['chibi-neutral', 'chibi-eat', 'scene-chibi-neutral', 'scene-chibi-eat']) {
    const response = await request.get('/art/' + name + '.webp')
    expect(response.ok()).toBe(true)
    expect(createHash('sha256').update(await response.body()).digest('hex')).toBe(hash)
  }
  for (const [spot_id, action] of [['bookshelf', 'read'], ['window', 'move'], ['bed', 'rest']]) {
    const after = await mutate(request, 'scene/interact', { spot_id, action })
    await page.reload()
    const character = page.getByTestId('character')
    const image = character.locator('img')
    await expect(image).toHaveAttribute('src', './art/scene-chibi-neutral.webp')
    await image.evaluate((img: HTMLImageElement) => img.decode())
    expect(await image.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([362, 482])
    const box = (await character.boundingBox())!, room = (await page.getByTestId('room').boundingBox())!
    const anchor = after.scene.locations[after.home.character.location]
    expect(box.width / box.height).toBeCloseTo(362 / 482, 3)
    expect(box.height / room.height).toBeCloseTo(anchor.height * .44, 3)
    expect(Math.abs(box.y + box.height - (room.y + room.height * anchor.y))).toBeLessThan(1)
    await page.screenshot({ path: path.join(screenshots, `${spot_id}.png`), fullPage: true })
  }
  expect(errors).toEqual([])
})

test('eating retains the new appearance, consumes once, and mobile settings explain the static fallback', async ({ page, request }) => {
  const before = await state(request)
  const after = await mutate(request, 'interact', { instance_id: 'initial-rice', mode: 'use' })
  expect(after.home.instances.find((i: any) => i.id === 'initial-rice').quantity).toBe(before.home.instances.find((i: any) => i.id === 'initial-rice').quantity - 1)
  await page.reload()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', './art/scene-chibi-eat.webp')
  await page.screenshot({ path: path.join(screenshots, 'eating-static-fallback.png'), fullPage: true })
  await page.getByTestId('character').click()
  await expect(page.getByRole('textbox', { name: '聊天消息' })).toBeVisible()
  await page.getByRole('button', { name: '关闭面板', exact: true }).click()
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    await expect(page.getByTestId('character')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: path.join(screenshots, `mobile-${width}.png`), fullPage: true })
  }
  await openSettings(page,'角色与显示')
  await expect(page.getByTestId('artwork-progress')).toContainText('进食暂用同一张静态图')
  await expect(page.locator('.about')).toContainText('用户提供的三视图正面')
})
