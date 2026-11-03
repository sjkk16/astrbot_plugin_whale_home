import { openSettings } from './navigation'
import { test, expect, type APIRequestContext } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { randomUUID } from 'node:crypto'

const screenshots = path.resolve(process.env.PLAYWRIGHT_SCREENSHOTS_DIR ? path.join(process.env.PLAYWRIGHT_SCREENSHOTS_DIR, '') : '../artifacts/interaction-v030/screenshots')
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
  const snapshot = await state(request)
  return mutation(request, 'settings', { settings: { ...snapshot.home.settings, ...values } })
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
  await expect(page.getByTestId('room')).toBeVisible()
  await page.locator('img').evaluateAll(images => Promise.all(images.map(img => img.decode())))
})
test.afterEach(() => { expect(errors).toEqual([]) })

test('click character, pet, and immediately show a local expression without a model', async ({ page, request }) => {
  const before = await state(request)
  await page.getByTestId('character').click()
  const tray = page.getByRole('region', { name: '直接互动' })
  await expect(tray).toBeVisible()
  await page.screenshot({ path: path.join(screenshots, 'interaction-desktop.png'), fullPage: true })
  await tray.getByRole('button', { name: '摸摸头', exact: true }).click()
  await expect(tray).toHaveCount(0)
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'pet')
  await expect(page.getByTestId('character-bubble')).toContainText('本地回应')
  const after = await state(request)
  expect(after.usage).toEqual(before.usage)
  expect(after.home.instances).toEqual(before.home.instances)
  await page.screenshot({ path: path.join(screenshots, 'pet-desktop.png'), fullPage: true })
})

test('feeding consumes one instance and shows the actual rice pose before returning to idle', async ({ page, request }) => {
  test.setTimeout(40000)
  const before = (await state(request)).home.instances.find((item: any) => item.id === 'initial-rice').quantity
  await page.getByRole('button', { name: '直接互动', exact: true }).click()
  await page.getByRole('button', { name: '递给她：一碗白饭', exact: true }).click()
  const image = page.getByTestId('character').locator('img')
  await expect(image).toHaveAttribute('src', './art/interaction-v030/eat.webp')
  await image.evaluate((img: HTMLImageElement) => img.decode())
  expect(await image.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([735, 1453])
  expect((await state(request)).home.instances.find((item: any) => item.id === 'initial-rice').quantity).toBe(before - 1)
  await page.screenshot({ path: path.join(screenshots, 'rice-desktop.png'), fullPage: true })
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'neutral', { timeout: 22000 })
  await expect(page.getByTestId('character-bubble')).toHaveCount(0)
})

test('gift and fixed-activity controls remain real actions without furniture placement', async ({ page, request }) => {
  await page.getByTestId('character').click()
  await page.getByRole('button', { name: '递给她：窗边绿植', exact: true }).click()
  await expect(page.getByTestId('character-bubble')).toContainText('窗边绿植')
  const count = (await state(request)).home.instances.find((item: any) => item.id === 'initial-plant').quantity
  expect(count).toBe(1)
  await page.getByRole('button', { name: '直接互动', exact: true }).click()
  await page.getByRole('button', { name: '一起做点事', exact: true }).click()
  await page.getByRole('region', { name: '直接互动' }).getByRole('button', { name: /读一会儿书/ }).click()
  await expect(page.getByTestId('character')).toHaveAttribute('data-location', 'desk')
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'read')
  expect((await state(request)).home.instances.find((item: any) => item.id === 'initial-rice').quantity).toBe(5)
})

test('offline chat is playful but responds gently to a serious message', async ({ page, request }) => {
  await configure(request, { provider_id: 'local-demo' })
  await page.reload()
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByRole('textbox', { name: '聊天消息' }).fill('今天想摸鱼')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.chat-messages .message.assistant').last()).toContainText(/摸鱼不等于摸鲸鱼|摸鱼小队收到/)
  await page.getByRole('textbox', { name: '聊天消息' }).fill('其实今天很难过')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.chat-messages .message.assistant').last()).toContainText(/那先不逗你|难过的时候不必|今天的小玩笑先收起来/)
  await expect(page.getByTestId('character')).toHaveAttribute('data-frame', 'sad')
  await expect(page.locator('.chat-composer')).toContainText('不调用在线模型')
  await page.screenshot({ path: path.join(screenshots, 'chat-desktop.png'), fullPage: true })
})

test('model reactions replace the local line once and retain the five-second limit', async ({ page, request }) => {
  await configure(request, { provider_id: 'local-demo' })
  await mutation(request, 'companion/preferences', { preferences: { interaction_model_enabled: true, proactive_enabled: false, idle_minutes: 5, interval_minutes: 15, daily_limit: 6 } })
  // A previous test may have used a model; the real persistent limiter must not be reset.
  await page.waitForTimeout(5100)
  await page.reload()
  const before = await state(request)
  await page.getByTestId('character').click()
  await page.getByRole('button', { name: '递给她：一碗白饭', exact: true }).click()
  await expect(page.getByTestId('character-bubble')).toContainText('演示接话')
  const after = await state(request)
  expect(after.usage.interaction).toBe(before.usage.interaction + 1)
  expect(after.home.instances.find((item: any) => item.id === 'initial-rice').quantity).toBe(4)
  expect(after.messages.length).toBe(before.messages.length + 1)
  await page.getByRole('button', { name: '直接互动', exact: true }).click()
  await page.getByRole('button', { name: '递给她：清香热茶', exact: true }).click()
  await expect(page.getByTestId('character-bubble')).toContainText('本地回应')
  expect((await state(request)).usage.interaction).toBe(after.usage.interaction)
})

test('proactive settings are opt-in, bounded, persistent, and distinct from autonomy', async ({ page, request }) => {
  await configure(request, { provider_id: 'local-demo' })
  await page.reload()
  await openSettings(page,'聊天与自主生活')
  await expect(page.getByTestId('proactive-toggle')).not.toBeChecked()
  await page.getByTestId('proactive-toggle').check()
  await page.getByRole('button', { name: '保存陪伴设置', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('陪伴偏好已保存')
  let snapshot = await state(request)
  expect(snapshot.companion.preferences).toMatchObject({ proactive_enabled: true, idle_minutes: 5, interval_minutes: 15, daily_limit: 6 })
  expect(snapshot.home.settings.autonomous_enabled).toBe(false)
  await page.reload()
  await openSettings(page,'聊天与自主生活')
  await expect(page.getByTestId('proactive-toggle')).toBeChecked()
  await page.getByTestId('proactive-toggle').uncheck()
  await page.getByRole('button', { name: '保存陪伴设置', exact: true }).click()
  await expect.poll(async () => (await state(request)).companion.preferences.proactive_enabled).toBe(false)
})

test('custom art, persona, and user name survive direct interaction and reload', async ({ page, request }) => {
  const content = await fs.readFile(path.resolve('public/art/portrait.webp'))
  const response = await request.post('/api/assets/upload', { multipart: { file: { name: 'custom.webp', mimeType: 'image/webp', buffer: content } } })
  expect(response.ok()).toBe(true)
  const asset = (await response.json()).asset_id
  await configure(request, { portrait_asset: asset, persona: '这是我的自定义人设，不要自动替换。', user_name: '星屑' })
  await page.reload()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', /^data:image\/webp;base64,/)
  const original = await page.getByTestId('character').locator('img').getAttribute('src')
  await page.getByTestId('character').click()
  await page.getByRole('button', { name: '递给她：一碗白饭', exact: true }).click()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', original!)
  await page.reload()
  const saved = (await state(request)).home.settings
  expect(saved.portrait_asset).toBe(asset)
  expect(saved.persona).toBe('这是我的自定义人设，不要自动替换。')
  expect(saved.user_name).toBe('星屑')
  await openSettings(page,'聊天与自主生活')
  await openSettings(page,'角色与显示')
  await page.getByRole('button', { name: '使用俏皮人设预设', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click()
  expect((await state(request)).home.settings.persona).toBe(saved.persona)
})

test('Q remains the original size and clicking it still opens chat', async ({ page, request }) => {
  await configure(request, { character_style: 'chibi' })
  await page.reload()
  const character = page.getByTestId('character')
  await expect(character.locator('img')).toHaveAttribute('src', './art/scene-chibi-neutral.webp')
  await expect(page.getByRole('button', { name: '直接互动', exact: true })).toHaveCount(0)
  await character.click()
  await expect(page.getByRole('textbox', { name: '聊天消息' })).toBeVisible()
  await expect(page.getByRole('region', { name: '直接互动' })).toHaveCount(0)
  const scene = (await state(request)).scene
  const room = (await page.getByTestId('room').boundingBox())!
  const box = (await character.boundingBox())!
  expect(box.height / room.height).toBeCloseTo(scene.locations.window.height * .44, 2)
})

test('interaction tray is keyboard accessible and Escape returns focus', async ({ page }) => {
  const character = page.getByTestId('character')
  await character.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('region', { name: '直接互动' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('region', { name: '直接互动' })).toHaveCount(0)
  await expect(character).toBeFocused()
})

for (const width of [390, 320]) {
  test('mobile interaction and bubble stay usable at ' + width + 'px', async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.getByRole('button', { name: '直接互动', exact: true }).click()
    const tray = page.getByRole('region', { name: '直接互动' })
    const box = (await tray.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(width)
    await page.screenshot({ path: path.join(screenshots, 'interaction-mobile-' + width + '.png'), fullPage: true })
    await tray.getByRole('button', { name: '摸摸头', exact: true }).click()
    await expect(page.getByTestId('character-bubble')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: path.join(screenshots, 'pet-mobile-' + width + '.png'), fullPage: true })
  })
}


test('presence follows page visibility without model calls or world mutations', async ({ page, request }) => {
  await expect.poll(async () => (await state(request)).companion.visible).toBe(true)
  const before = await state(request)
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect.poll(async () => (await state(request)).companion.visible).toBe(false)
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect.poll(async () => (await state(request)).companion.visible).toBe(true)
  const after = await state(request)
  expect(after.home.version).toBe(before.home.version)
  expect(after.usage).toEqual(before.usage)
})
