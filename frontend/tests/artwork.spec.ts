import { openSettings } from './navigation'
import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
const manifest = JSON.parse(readFileSync(new URL('../preview-assets/art/interaction-v030/manifest.json', import.meta.url), 'utf8'))

const frames: Record<string, { path: string; width: number; height: number; foot_anchor: number[] }> = manifest.variants
const screenshots = path.resolve(process.env.PLAYWRIGHT_SCREENSHOTS_DIR || '../artifacts/interaction-v030/screenshots', 'artwork')
let clean: Buffer
let errors: string[]
async function state(request: APIRequestContext) { return (await request.get('/api/state')).json() }
async function mutation(request: APIRequestContext, endpoint: string, values: object) {
  const snapshot = await state(request)
  const response = await request.post('/api/' + endpoint, { data: { request_id: randomUUID(), expected_version: snapshot.home.version, ...values } })
  expect(response.ok(), await response.text()).toBe(true)
  return response.json()
}
async function configure(request: APIRequestContext, values: object) {
  return mutation(request, 'settings', { settings: { ...(await state(request)).home.settings, ...values } })
}
async function geometry(page: Page, snapshot: any, name: string) {
  const sprite = page.getByTestId('character')
  const box = (await sprite.boundingBox())!
  const room = (await page.getByTestId('room').boundingBox())!
  const location = snapshot.scene.locations[snapshot.home.character.location]
  const entry = name === 'neutral' ? manifest.reference : frames[name]!
  expect(box.width / box.height).toBeCloseTo(entry.width / entry.height, 3)
  expect(Math.abs(box.y + box.height - (room.y + room.height * location.y))).toBeLessThan(1)
  expect(Math.abs(box.x + box.width * entry.foot_anchor[0]! - (room.x + room.width * location.x))).toBeLessThan(1)
}

test.beforeAll(async ({ request }) => {
  clean = await (await request.get('/api/archives/export')).body()
  await fs.mkdir(screenshots, { recursive: true })
})
test.beforeEach(async ({ page, request }) => {
  await expect.poll(async () => (await state(request)).runtime.busy).toBe(false)
  const restored = await request.post('/api/archives/import', { multipart: { file: { name: 'clean.json', mimeType: 'application/json', buffer: clean } } })
  expect(restored.ok()).toBe(true)
  await configure(request, { provider_id: '', autonomous_enabled: false, character_style: 'portrait', portrait_asset: null, chibi_asset: null })
  await mutation(request, 'companion/preferences', { preferences: { interaction_model_enabled: false, proactive_enabled: false, idle_minutes: 5, interval_minutes: 15, daily_limit: 6 } })
  errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByTestId('character')).toBeVisible()
  await page.getByTestId('character').locator('img').evaluate((image: HTMLImageElement) => image.decode())
})
test.afterEach(() => { expect(errors).toEqual([]) })
test.afterAll(async ({ request }) => {
  await expect.poll(async () => (await state(request)).runtime.busy).toBe(false)
  const restored = await request.post('/api/archives/import', { multipart: { file: { name: 'clean.json', mimeType: 'application/json', buffer: clean } } })
  expect(restored.ok()).toBe(true)
})

for (const [emotion, text] of [
  ['happy', '今天想摸鱼'], ['thinking', '陪我想想周末做什么'], ['sleepy', '我有点困了'],
  ['shy', '你今天真可爱'], ['sad', '今天有点难过'],
]) {
  test(`offline emotion ${emotion} uses its real artwork in both room and chat`, async ({ page, request }) => {
    await configure(request, { provider_id: 'local-demo' })
    await page.reload()
    await page.getByRole('button', { name: '聊天', exact: true }).click()
    await page.getByRole('textbox', { name: '聊天消息' }).fill(text!)
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.getByTestId('character')).toHaveAttribute('data-frame', emotion!)
    await expect(page.locator('.portrait-stage > img')).toHaveAttribute('src', frames[emotion!]!.path)
    await geometry(page, await state(request), emotion!)
    await page.screenshot({ path: path.join(screenshots, `emotion-${emotion}.png`), fullPage: true })
  })
}

const actions = [
  { pose: 'pet', payload: { kind: 'pet' } },
  { pose: 'accept', payload: { kind: 'item', instance_id: 'initial-plant', mode: 'gift' } },
  { pose: 'eat', payload: { kind: 'item', instance_id: 'initial-rice' } },
  { pose: 'drink', payload: { kind: 'item', instance_id: 'initial-tea' } },
  { pose: 'read', payload: { kind: 'scene', spot_id: 'bookshelf' } },
  { pose: 'play', payload: { kind: 'item' } },
  { pose: 'rest', payload: { kind: 'scene', spot_id: 'bed' } },
]
for (const { pose, payload } of actions) {
  const available = Boolean(frames[pose])
  test(`action ${pose}: ${available ? 'dedicated illustration' : 'honestly labeled fallback (illustration pending)'}`, async ({ page, request }) => {
    let values: object = payload
    if (pose === 'play') {
      const added = await mutation(request, 'items/add', { definition_id: 'game', quantity: 1 })
      values = { kind: 'item', instance_id: added.home.instances.find((item: any) => item.definition_id === 'game').id }
    }
    const before = await state(request)
    const after = await mutation(request, 'character/interact', values)
    const frame = available ? pose : pose === 'rest' ? 'sleepy' : 'happy'
    await expect(page.getByTestId('character')).toHaveAttribute('data-pose', pose)
    await expect(page.getByTestId('character')).toHaveAttribute('data-frame', frame)
    await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', frames[frame]!.path)
    if (available) await expect(page.getByTestId('artwork-fallback')).toHaveCount(0)
    else await expect(page.getByTestId('artwork-fallback')).toContainText('专用图待补')
    expect(after.usage).toEqual(before.usage)
    if (pose === 'eat' || pose === 'drink') {
      const id = pose === 'eat' ? 'initial-rice' : 'initial-tea'
      expect(after.home.instances.find((item: any) => item.id === id).quantity).toBe(before.home.instances.find((item: any) => item.id === id).quantity - 1)
    } else expect(after.home.instances).toEqual(before.home.instances)
    await geometry(page, after, frame)
    await page.screenshot({ path: path.join(screenshots, `action-${pose}${available ? '' : '-fallback'}.png`), fullPage: true })
    await page.getByRole('button', { name: '聊天', exact: true }).click()
    await expect(page.locator('.portrait-stage > img')).toHaveAttribute('src', frames[frame]!.path)
    if (!available) await expect(page.getByTestId('portrait-artwork-fallback')).toContainText('专用图待补')
  })
}

test('action expires to the response emotion, then returns to the original idle art', async ({ page, request }) => {
  test.setTimeout(40000)
  await mutation(request, 'character/interact', { kind: 'item', instance_id: 'initial-tea' })
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'drink')
  // Use real elapsed time: live snapshots legitimately resync the presentation clock.
  // Advancing only a browser clock would race that sync and would not test the actual timer.
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'happy', { timeout: 11000 })
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'neutral', { timeout: 14000 })
  await expect(page.getByTestId('character-bubble')).toHaveCount(0)
})

test('slow previous decoding cannot overwrite a newer action or its dimensions', async ({ page, request }) => {
  await page.addInitScript(() => {
    const native = HTMLImageElement.prototype.decode
    const gate: { waiting: boolean; release?: () => void } = { waiting: false }
    const ready = new Promise<void>(resolve => { gate.release = resolve })
    ;(window as any).__spriteGate = gate
    HTMLImageElement.prototype.decode = function () {
      const decoded = native.call(this)
      if (!this.src.endsWith('/interaction-v030/read.webp')) return decoded
      gate.waiting = true
      return decoded.then(() => ready)
    }
  })
  await page.reload()
  await expect.poll(() => page.evaluate(() => (window as any).__spriteGate.waiting)).toBe(true)
  await mutation(request, 'character/interact', { kind: 'item', instance_id: 'initial-book' })
  await expect(page.getByTestId('character')).toHaveAttribute('data-requested-frame', 'read')
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'neutral')
  await geometry(page, await state(request), 'neutral')
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  const after = await mutation(request, 'character/interact', { kind: 'item', instance_id: 'initial-rice' })
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'eat')
  await expect(page.locator('.portrait-stage > img')).toHaveAttribute('src', frames.eat!.path)
  await page.evaluate(async () => {
    ;(window as any).__spriteGate.release()
    await new Promise(requestAnimationFrame)
    await new Promise(requestAnimationFrame)
  })
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'eat')
  await expect(page.locator('.portrait-stage > img')).toHaveAttribute('src', frames.eat!.path)
  await geometry(page, after, 'eat')
})

test('failed sprite load falls back without undoing or repeating the completed action', async ({ page, request }) => {
  await page.route('**/art/interaction-v030/drink.webp', route => route.abort('failed'))
  await page.reload()
  const before = await state(request)
  const after = await mutation(request, 'character/interact', { kind: 'item', instance_id: 'initial-tea' })
  await expect(page.getByTestId('character')).toHaveAttribute('data-requested-frame', 'drink')
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', './art/scene-portrait.webp')
  await expect(page.getByTestId('character-bubble')).toContainText('清香热茶')
  await geometry(page, after, 'neutral')
  expect(after.usage).toEqual(before.usage)
  expect(after.home.instances.find((item: any) => item.id === 'initial-tea').quantity).toBe(4)
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await expect(page.locator('.portrait-stage > img')).toHaveAttribute('src', './art/portrait.webp')
})

test('the settings disclose the exact installed and pending illustration count', async ({ page }) => {
  await openSettings(page,'聊天与自主生活')
  await expect(page.getByTestId('artwork-progress')).toContainText(`${Object.keys(frames).length}/12 张差分`)
  if (manifest.pending_illustrations.length) {
    await expect(page.getByTestId('artwork-progress')).toContainText('待补齐')
    await expect(page.getByTestId('artwork-progress')).not.toContainText('表情与专用动作图已齐')
  }
})

test('a clear conversational boundary stops playful teasing without taking an action', async ({ page, request }) => {
  await configure(request, { provider_id: 'local-demo' })
  await page.reload()
  const before = await state(request)
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByRole('textbox', { name: '聊天消息' }).fill('先别逗我，认真一点')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.chat-messages')).toContainText('尊重你的边界')
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'neutral')
  expect((await state(request)).home.instances).toEqual(before.home.instances)
})
