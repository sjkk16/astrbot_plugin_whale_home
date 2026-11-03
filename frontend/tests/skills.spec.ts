import { openSettings } from './navigation'
import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'

async function state(request: any) { return (await request.get('/api/state')).json() }
async function preferences(request: any, values: object = {}) {
  const s = await state(request)
  const response = await request.post('/api/skills/preferences', { data: {
    request_id: randomUUID(), expected_version: s.home.version,
    preferences: { enabled: true, access_mode: 'restricted', allowed_tools: [], allowed_skills: [], ...values }, confirm_full_access: true,
  } })
  expect(response.ok()).toBe(true)
}
test.beforeEach(async ({ page, request }) => {
  await preferences(request)
  const s = await state(request)
  await request.post('/api/settings', { data: { request_id: randomUUID(), expected_version: s.home.version,
    settings: { ...s.home.settings, provider_id: 'local-demo', autonomous_enabled: false, character_style: 'portrait' } } })
  await page.goto('/')
  await expect(page.getByRole('button', { name: '更多', exact: true })).toBeVisible()
})
test.afterEach(async ({ request }) => { await preferences(request) })

test('default restricted catalogue, unavailable reasons and draft survives SSE', async ({ page, request }) => {
  await openSettings(page,'Skills 权限')
  const settings = page.getByTestId('skills-settings')
  await expect(settings.getByLabel('技能访问模式')).toHaveValue('restricted')
  await expect(settings.getByLabel('允许 demo_weather', { exact: true })).not.toBeChecked()
  await expect(settings.getByLabel('允许 demo_detached', { exact: true })).toBeDisabled()
  await settings.getByLabel('允许 demo_weather', { exact: true }).check()
  const s = await state(request)
  await request.post('/api/settings', { data: { request_id: randomUUID(), expected_version: s.home.version, settings: s.home.settings } })
  await expect(page.locator('.connection')).toContainText('已同步')
  await page.waitForTimeout(250)
  await expect(settings.getByLabel('允许 demo_weather', { exact: true })).toBeChecked()
  await settings.getByLabel('搜索技能与工具').fill('demo_weather')
  await expect(settings.locator('.skills-entry')).toHaveCount(1)
})

test('allowlisted skill and tool execute automatically and show metadata', async ({ page, request }) => {
  await openSettings(page,'Skills 权限')
  const settings = page.getByTestId('skills-settings')
  await settings.getByLabel('允许 demo_weather', { exact: true }).check()
  await settings.getByLabel('允许 demo_companion', { exact: true }).check()
  await settings.getByRole('button', { name: '保存技能权限' }).click()
  await expect(page.locator('.toast-message')).toContainText('技能权限已保存')
  await page.getByRole('button', { name: '关闭面板', exact: true }).click()
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByLabel('聊天消息', { exact: true }).fill('请用技能查询天气')
  await page.getByLabel('聊天消息', { exact: true }).press('Enter')
  await expect(page.locator('.chat-messages')).toContainText('模拟天气')
  const s = await state(request)
  expect(s.skills.calls.slice(0, 2).map((r: any) => r.name)).toEqual(['demo_weather', 'demo_companion'])
  expect(JSON.stringify(s.skills.calls)).not.toContain('22℃')
})

test('full access needs explicit confirmation and cancel leaves saved mode unchanged', async ({ page, request }) => {
  await openSettings(page,'Skills 权限')
  const settings = page.getByTestId('skills-settings')
  await settings.getByLabel('技能访问模式').selectOption('full')
  await settings.getByRole('button', { name: '保存技能权限' }).click()
  const dialog = settings.locator('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  expect((await state(request)).skills.preferences.access_mode).toBe('restricted')
  await settings.getByRole('button', { name: '保存技能权限' }).click()
  await dialog.getByRole('button', { name: '确认完全访问', exact: true }).click()
  await expect(page.locator('.toast-message')).toContainText('技能权限已保存')
  expect((await state(request)).skills.preferences.access_mode).toBe('full')
})

test('stop remains available while chat is pending, second page sees result', async ({ page, request, context }) => {
  await preferences(request, { allowed_tools: ['demo_slow'] })
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByLabel('聊天消息', { exact: true }).fill('运行慢速演示')
  await page.getByLabel('聊天消息', { exact: true }).press('Enter')
  await expect.poll(async () => (await state(request)).skills.active?.name).toBe('demo_slow')
  const second = await context.newPage()
  await second.goto('/')
  await openSettings(second,'Skills 权限')
  await expect(second.getByTestId('skills-settings').locator('.skills-active')).toContainText('demo_slow')
  await page.getByRole('button', { name: '停止本轮技能', exact: true }).first().click()
  await expect(second.getByTestId('skills-settings').locator('.skills-history').first()).toContainText('结果未确认')
  await expect.poll(async () => (await state(request)).skills.active).toBeNull()
  await second.close()
})

test('permission save is independent of pending chat', async ({ page, request }) => {
  await preferences(request, { allowed_tools: ['demo_slow'] })
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByLabel('聊天消息', { exact: true }).fill('运行慢速演示')
  await page.getByLabel('聊天消息', { exact: true }).press('Enter')
  await expect.poll(async () => (await state(request)).skills.active?.name).toBe('demo_slow')
  await openSettings(page,'Skills 权限')
  const settings = page.getByTestId('skills-settings')
  await settings.getByLabel('启用技能与工具', { exact: true }).uncheck()
  await settings.getByRole('button', { name: '保存技能权限' }).click()
  await expect.poll(async () => (await state(request)).skills.active).toBeNull()
  expect((await state(request)).skills.preferences.enabled).toBe(false)
})

test('mobile skill controls have no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openSettings(page,'Skills 权限')
  const settings = page.getByTestId('skills-settings')
  await settings.locator('h3').scrollIntoViewIfNeeded()
  await expect(settings.getByLabel('技能访问模式')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const directory = path.resolve(process.env.PLAYWRIGHT_SCREENSHOTS_DIR || '../artifacts/release-v041/screenshots', 'skills')
  await fs.mkdir(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, 'skills-mobile.png'), fullPage: true })
})
