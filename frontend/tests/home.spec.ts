import { openSettings, openItems, navigate } from './navigation'
import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { randomUUID } from 'node:crypto'

const screenshots = path.resolve(process.env.PLAYWRIGHT_SCREENSHOTS_DIR ? path.join(process.env.PLAYWRIGHT_SCREENSHOTS_DIR, 'regression') : process.env.PLAYWRIGHT_STATIC_DIR ? '../artifacts/interaction-v030/screenshots/regression' : '../artifacts/screenshots/v021')
let cleanArchive: Buffer
let errors: string[]

test.beforeAll(async ({ request }) => {
  cleanArchive = await (await request.get('/api/archives/export')).body()
  await fs.mkdir(screenshots, { recursive: true })
})
test.beforeEach(async ({ page, request }) => {
  const restored = await request.post('/api/archives/import', {
    multipart: { file: { name: 'clean.json', mimeType: 'application/json', buffer: cleanArchive } },
  })
  expect(restored.ok()).toBe(true)
  const { home } = await restored.json()
  expect((await request.post('/api/settings', { data: { request_id: randomUUID(), expected_version: home.version,
    settings: { ...home.settings, provider_id: '', autonomous_enabled: false, character_style: 'portrait' } } })).ok()).toBe(true)
  errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByTestId('room')).toBeVisible()
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
})
test.afterEach(() => { expect(errors).toEqual([]) })

async function clickSpot(page: any, id: string, label: string) {
  await page.getByTestId(`spot-${id}`).locator('.hotspot-marker').click()
  await page.locator('.spot-card').getByRole('button', { name: label, exact: true }).click()
  await expect(page.locator('.spot-card')).toHaveCount(0)
  await expect(page.getByTestId('character')).toHaveAttribute('data-moving', 'false', { timeout: 10000 })
}
async function snapshot(request: any) { return (await request.get('/api/state')).json() }

test('full-frame night room is immersive and all images decode', async ({ page }) => {
  await expect(page.locator('.side-panel')).toHaveCount(0)
  await expect(page.locator('.room-item')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '布置小屋', exact: true })).toHaveCount(0)
  const room = (await page.getByTestId('room').boundingBox())!
  const image = (await page.locator('.room-background').boundingBox())!
  expect(Math.abs(room.width / room.height - 1672 / 941)).toBeLessThan(.001)
  expect(image).toEqual(room)
  expect(await page.locator('.room-background').evaluate(img => getComputedStyle(img).objectFit)).toBe('contain')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: path.join(screenshots, 'night-desktop.png'), fullPage: true })
})

test('furniture selection requires confirmation and the first action animates', async ({ page, request }) => {
  const before = await snapshot(request)
  await page.getByTestId('spot-bookshelf').locator('.hotspot-marker').click()
  await expect(page.locator('.spot-card')).toContainText('书架')
  expect((await snapshot(request)).home.world_version).toBe(before.home.world_version)
  await page.getByRole('button', { name: '读一会儿书', exact: true }).click()
  await expect(page.getByTestId('character')).toHaveAttribute('data-moving', 'true')
  await expect(page.getByTestId('character')).toHaveAttribute('data-moving', 'false', { timeout: 10000 })
  const after = await snapshot(request)
  expect(after.home.character.location).toBe('desk')
  expect(after.home.character.last_path).toEqual(['window', 'desk'])
  expect(after.home.character.activity).toBe('read')
  expect(after.usage).toEqual(before.usage)
})

test('all four fixed activities work without a model or inventory consumption', async ({ page, request }) => {
  const before = await snapshot(request)
  for (const [id, label, action, location] of [
    ['bookshelf','读一会儿书','read','desk'], ['desk','玩一会儿电脑','play','desk'],
    ['window','一起看夜景','move','window'], ['bed','在床边休息','rest','bedside'],
  ]) {
    await clickSpot(page, id!, label!)
    const state = await snapshot(request)
    expect(state.home.character.activity).toBe(action)
    expect(state.home.character.location).toBe(location)
  }
  const after = await snapshot(request)
  expect(after.home.instances).toEqual(before.home.instances)
  expect(after.usage).toEqual(before.usage)
  expect(after.events[0].text).toContain('在床边休息')
})

test('opening panels never changes scene or hotspot coordinates', async ({ page }) => {
  const initial = await page.getByTestId('room').boundingBox()
  const hotspot = await page.getByTestId('spot-window').boundingBox()
  for (const label of ['聊天', '物品', '日记', '小家设置']) {
    await navigate(page,label)
    await expect(page.locator('.side-panel')).toBeVisible()
    expect(await page.getByTestId('room').boundingBox()).toEqual(initial)
    expect(await page.getByTestId('spot-window').boundingBox()).toEqual(hotspot)
    await page.getByRole('button', { name: '关闭面板', exact: true }).click()
  }
})

test('unconfigured chat never calls a model', async ({ page, request }) => {
  const before = (await snapshot(request)).usage
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByRole('textbox', { name: '聊天消息' }).fill('你好')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('选择聊天模型')
  expect((await snapshot(request)).usage).toEqual(before)
})

test('demo chat uses the actual inventory action pipeline', async ({ page, request }) => {
  const before = (await snapshot(request)).usage.chat
  await openSettings(page,'聊天与自主生活')
  await page.getByTestId('provider-select').selectOption('local-demo')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('设置已保存')
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByRole('textbox', { name: '聊天消息' }).fill('一起读一本书吧')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.chat-messages')).toContainText('海边的故事')
  await expect.poll(async () => (await snapshot(request)).home.character.activity).toBe('read')
  expect((await snapshot(request)).usage.chat).toBe(before + 1)
  await page.screenshot({ path: path.join(screenshots, 'night-chat.png'), fullPage: true })
})

test('inventory add use gift and removal require no placement', async ({ page, request }) => {
  await openItems(page)
  await page.getByRole('button', { name: '物品库', exact: true }).click()
  await page.getByRole('button', { name: '添加海边的故事', exact: true }).click()
  await expect(page.locator('.selection-info')).toContainText('海边的故事')
  await expect(page.locator('.bag-item').filter({ hasText: '海边的故事' })).toHaveCount(2)
  await page.getByRole('button', { name: '阅读', exact: true }).click()
  await expect(page.locator('.room-status')).toContainText('沉浸阅读')
  await page.getByRole('button', { name: '送给她', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('记下啦')
  await page.getByRole('button', { name: '移除物品', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click()
  await expect(page.locator('.bag-item').filter({ hasText: '海边的故事' })).toHaveCount(1)
  expect((await snapshot(request)).home.instances.every((item: any) => item.position === null)).toBe(true)
})

test('custom item image editing and deletion remain safe', async ({ page }) => {
  await openItems(page)
  await page.getByRole('button', { name: '自定义', exact: true }).click()
  await page.getByRole('button', { name: '创造物品', exact: true }).click()
  await page.getByTestId('item-name').fill('月亮旅行包')
  await page.getByLabel('描述', { exact: true }).fill('<script>window.injected = true</script> 装满回忆。')
  await page.locator('input[type=file]').setInputFiles(path.resolve('public/art/chibi-neutral.webp'))
  await expect(page.locator('.upload-tile img')).toBeVisible()
  await page.getByRole('button', { name: '保存物品', exact: true }).click()
  await expect(page.getByRole('button', { name: '添加月亮旅行包', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as any).injected)).toBeUndefined()
  await page.getByRole('button', { name: '编辑物品', exact: true }).click()
  await expect(page.getByTestId('item-name')).toHaveValue('月亮旅行包')
  await page.getByRole('button', { name: '返回物品', exact: true }).click()
  await page.getByRole('button', { name: '删除自定义种类', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click()
  await expect(page.getByRole('button', { name: '添加月亮旅行包', exact: true })).toHaveCount(0)
})

test('memory confirmation and v2 archive download work', async ({ page }) => {
  await page.getByRole('button', { name: '日记', exact: true }).click()
  await page.getByRole('button', { name: '共同记忆', exact: true }).click()
  await page.getByRole('textbox', { name: '新的记忆' }).fill('喜欢看冬天的月亮')
  await page.getByRole('button', { name: '记住这件事', exact: true }).click()
  await expect(page.locator('.memory-entry')).toContainText('喜欢看冬天的月亮')
  await page.getByRole('button', { name: '删除记忆', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.locator('.memory-entry')).toHaveCount(1)
  await page.getByRole('button', { name: '删除记忆', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click()
  await expect(page.locator('.memory-entry')).toHaveCount(0)
  await openSettings(page,'聊天与自主生活')
  const download = page.waitForEvent('download')
  await openSettings(page,'数据与关于')
  await page.getByRole('button', { name: '导出存档', exact: true }).click()
  const result = await download
  const archive = JSON.parse(await fs.readFile((await result.path())!, 'utf-8'))
  expect(archive.schema_version).toBe(2)
  expect(archive.state.settings.provider_id).toBe('')
  expect(archive.state.settings.autonomous_enabled).toBe(false)
})

test('portrait and chibi scale correctly and selection survives reload', async ({ page }) => {
  await openSettings(page,'聊天与自主生活')
  await openSettings(page,'角色与显示')
  await page.getByTestId('character-style').selectOption('chibi')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await page.getByRole('button', { name: '关闭面板', exact: true }).click()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', /scene-chibi/)
  await page.reload()
  await expect(page.getByTestId('room')).toBeVisible()
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  const small = (await page.getByTestId('character').boundingBox())!
  const room = (await page.getByTestId('room').boundingBox())!
  expect(small.height / room.height).toBeGreaterThan(.26)
  expect(small.height / room.height).toBeLessThan(.31)
  await page.screenshot({ path: path.join(screenshots, 'night-chibi.png'), fullPage: true })
  await openSettings(page,'聊天与自主生活')
  await openSettings(page,'角色与显示')
  await page.getByTestId('character-style').selectOption('portrait')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src', /scene-portrait/)
  const normal = (await page.getByTestId('character').boundingBox())!
  expect(normal.height / room.height).toBeCloseTo(.64, 2)
  expect((normal.y + normal.height - room.y) / room.height).toBeCloseTo(.93, 2)
})

test('old archive imports from the actual file picker flow', async ({ page, request }) => {
  const state = JSON.parse(await fs.readFile(path.resolve('../tests/fixtures/v1-home.json'), 'utf-8'))
  const archive = { format: 'whale-home', schema_version: 1, exported_at: '2026-10-31T00:00:00Z',
    state, events: [], messages: [], memories: [], assets: {} }
  await openSettings(page,'聊天与自主生活')
  await page.locator('input[accept=".json,application/json"]').setInputFiles({ name: 'old-v1.json',
    mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(archive)) })
  await page.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('存档已恢复')
  const after = await snapshot(request)
  expect(after.home.schema_version).toBe(2)
  expect(after.home.character.location).toBe('window')
  expect(after.home.instances.every((item: any) => item.position === null)).toBe(true)
  expect(after.home.settings.autonomous_enabled).toBe(false)
})

for (const viewport of [{width:390,height:844},{width:320,height:640}]) {
  test(`mobile ${viewport.width} keeps the whole image and accessible drawers`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const room = (await page.getByTestId('room').boundingBox())!
    expect(room.width / room.height).toBeCloseTo(1672 / 941, 2)
    expect(room.x).toBeGreaterThanOrEqual(0)
    expect(room.x + room.width).toBeLessThanOrEqual(viewport.width)
    const name = viewport.width === 390 ? 'night-mobile' : 'night-small'
    await page.screenshot({ path: path.join(screenshots, `${name}.png`), fullPage: true })
    for (const label of ['聊天','物品','日记','小家设置']) {
      await navigate(page,label)
      await expect(page.getByRole('button', { name: '关闭面板', exact: true })).toBeVisible()
      expect(await page.getByTestId('room').boundingBox()).toEqual(room)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
    await page.screenshot({ path: path.join(screenshots, `${name}-settings.png`), fullPage: true })
    await openSettings(page,'角色与显示')
    await page.getByLabel('她怎么称呼你', {exact:true}).fill('月亮朋友')
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('设置已保存')
    await page.getByRole('button', { name: '关闭面板', exact: true }).click()
    await expect(page.locator('.side-panel')).toHaveCount(0)
  })
}

test('keyboard activity list works and reduced motion disables travel and snow', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: '活动列表', exact: true }).focus()
  await page.keyboard.press('Enter')
  await page.locator('.activity-row').filter({hasText:'书架'}).focus()
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: '读一会儿书', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('character')).toHaveAttribute('data-location','desk')
  await expect(page.getByTestId('character')).toHaveAttribute('data-moving','false')
  await expect(page.locator('.window-snow')).toBeHidden()
})

test('two pages synchronize via events without extra autonomous calls', async ({ page, request }) => {
  const second = await page.context().newPage()
  await second.goto('/')
  await expect(second.getByTestId('room')).toBeVisible()
  const usage = (await snapshot(request)).usage
  await clickSpot(page,'bookshelf','读一会儿书')
  await expect(second.locator('.room-status')).toContainText('沉浸阅读')
  expect((await snapshot(request)).usage).toEqual(usage)
  await second.close()
})
