import { openSettings } from './navigation'
import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'

const interactionPreview = true // v0.4.2 release includes the interaction artwork
const screenshots = path.resolve(process.env.PLAYWRIGHT_SCREENSHOTS_DIR ? path.join(process.env.PLAYWRIGHT_SCREENSHOTS_DIR, 'portrait') : interactionPreview ? '../artifacts/interaction-v030/screenshots/regression/portrait' : '../artifacts/screenshots/v021/portrait')
let cleanArchive: Buffer

test.beforeAll(async ({ request }) => {
  const initial=await (await request.get('/api/archives/export')).json()
  initial.state.character.activity='idle'
  cleanArchive=Buffer.from(JSON.stringify(initial))
  await fs.mkdir(screenshots, { recursive: true })
})

test.beforeEach(async ({ page, request }) => {
  const restored = await request.post('/api/archives/import', {
    multipart: { file: { name: 'clean.json', mimeType: 'application/json', buffer: cleanArchive } },
  })
  expect(restored.ok()).toBe(true)
  const { home } = await restored.json()
  expect((await request.post('/api/settings', { data: {
    request_id: randomUUID(), expected_version: home.version,
    settings: { ...home.settings, provider_id: '', autonomous_enabled: false, character_style: 'portrait',
      portrait_asset: null, chibi_asset: null },
  } })).ok()).toBe(true)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByTestId('room')).toBeVisible()
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
})

test('new adult portrait is undistorted, foot-anchored at every spot, and used in chat', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const character = page.getByTestId('character')
  const artwork = interactionPreview ? (await (await request.get('/art/interaction-v030/manifest.json')).json()).variants : {}
  let shown = { path: './art/portrait.webp', width: 500, height: 991, foot_anchor: [.5, 1] }
  await expect(character.locator('img')).toHaveAttribute('src', './art/scene-portrait.webp')
  expect(await character.locator('img').evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([500, 991])
  for (const [spot, label, location] of [
    ['window', '一起看夜景', 'window'], ['bookshelf', '读一会儿书', 'desk'], ['bed', '在床边休息', 'bedside'],
  ]) {
    await page.getByTestId(`spot-${spot}`).locator('.hotspot-marker').click()
    await page.locator('.spot-card').getByRole('button', { name: label, exact: true }).click()
    await expect(character).toHaveAttribute('data-location', location!)
    shown = interactionPreview ? (spot === 'bookshelf' ? artwork.read || artwork.thinking : spot === 'bed' ? artwork.rest || artwork.sleepy : artwork.happy) : shown
    await expect(character.locator('img')).toHaveAttribute('src', interactionPreview ? shown.path : './art/scene-portrait.webp')
    const { scene } = await (await request.get('/api/state')).json()
    const room = (await page.getByTestId('room').boundingBox())!
    const image = (await character.locator('img').boundingBox())!
    const anchor = scene.locations[location!]
    expect(image.width / image.height).toBeCloseTo(shown.width / shown.height, 3)
    expect((image.y + image.height - room.y) / room.height).toBeCloseTo(anchor.y, 2)
    expect((image.x + image.width * shown.foot_anchor[0]! - room.x) / room.width).toBeCloseTo(anchor.x, 2)
    expect(image.x).toBeGreaterThanOrEqual(room.x)
    expect(image.x + image.width).toBeLessThanOrEqual(room.x + room.width)
    await page.screenshot({ path: path.join(screenshots, `room-${location}.png`), fullPage: true })
  }
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  const panelImage = page.locator('.portrait-stage > img')
  await expect(panelImage).toHaveAttribute('src', shown.path)
  await panelImage.evaluate((img: HTMLImageElement) => img.decode())
  expect(await panelImage.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([shown.width, shown.height])
  await page.screenshot({ path: path.join(screenshots, 'chat-panel.png'), fullPage: true })
  await page.getByRole('button', { name: '关闭面板', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByTestId('room')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: path.join(screenshots, 'room-mobile.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('Q sprites use the selected front and switching back preserves the adult portrait', async ({ page, request }) => {
  const hashes = {
    'scene-chibi-neutral.webp': 'ff0cff01c5b2790b6a9d50699411691b58f6b18d86d0e3b4d11f63aa6e6a59a1',
    'scene-chibi-eat.webp': 'ff0cff01c5b2790b6a9d50699411691b58f6b18d86d0e3b4d11f63aa6e6a59a1',
  }
  for (const [name, expected] of Object.entries(hashes)) {
    const response = await request.get(`/art/${name}`)
    expect(response.ok()).toBe(true)
    expect(createHash('sha256').update(await response.body()).digest('hex')).toBe(expected)
  }
  await openSettings(page,'角色与显示')
  await page.getByTestId('character-style').selectOption('chibi')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await page.getByRole('button', { name: '关闭面板', exact: true }).click()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', './art/scene-chibi-neutral.webp')
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  await page.screenshot({ path: path.join(screenshots, 'q-replaced.png'), fullPage: true })
  await openSettings(page,'角色与显示')
  await page.getByTestId('character-style').selectOption('portrait')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await page.reload()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', './art/scene-portrait.webp')
})


test('release version and the new portrait provenance are visible', async ({ page }) => {
  await expect(page.locator('.footer-note small')).toHaveText('v0.4.2 · PUBLIC RELEASE')
  await openSettings(page,'角色与显示')
  await expect(page.locator('.about')).toContainText('WHALE HOME · v0.4.2 PUBLIC RELEASE')
  await expect(page.locator('.about')).toContainText('用户提供的 deepseek.png')
  await expect(page.locator('.about')).toContainText('Q 版：用户提供的三视图正面（2026-11-02）')
  await expect(page.locator('.about')).not.toContainText('CC BY-NC-SA 4.0')
  await expect(page.locator('.about')).toContainText('作者及底层授权未独立核实')
})


test('settings payload crosses a structured-clone bridge and survives reload', async ({ page, request }) => {
  await page.evaluate(() => {
    const bridge = (window as any).AstrBotPluginView
    const apiPost = bridge.apiPost.bind(bridge)
    bridge.apiPost = (endpoint: string, body: unknown) => apiPost(endpoint, structuredClone(body))
  })
  await openSettings(page,'角色与显示')
  await page.getByTestId('character-style').selectOption('chibi')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('设置已保存')
  const state = await (await request.get('/api/state')).json()
  expect(state.home.settings.character_style).toBe('chibi')
  await page.reload()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', './art/scene-chibi-neutral.webp')
})
