// Real dashboard bridge verification, only against a prepared model-free local instance.
import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import { expect } from '../frontend/node_modules/@playwright/test/index.mjs'
import fs from 'node:fs/promises'
import path from 'node:path'
const root = path.resolve(import.meta.dirname, '..')
const instance = path.join(root, '.local/astrbot-skills-verify')
const config = JSON.parse((await fs.readFile(path.join(instance, 'data/cmd_config.json'), 'utf8')).replace(/^\uFEFF/, ''))
const credentials = JSON.parse((await fs.readFile(path.join(instance, 'test-credentials.json'), 'utf8')).replace(/^\uFEFF/, ''))
if (config.dashboard.host !== '127.0.0.1' || config.provider.length || config.provider_sources.length || config.platform.length || credentials.username !== 'whale-test') throw Error('Not an isolated model-free fixture')
const origin = `http://127.0.0.1:${config.dashboard.port}`
const api = `${origin}/api/v1/plugins/extensions/astrbot_plugin_whale_home`
const output = path.join(root, 'artifacts/skills-preview/host')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: 'msedge' })
const context = await browser.newContext({ viewport: { width: 1600, height: 1040 }, reducedMotion: 'reduce' })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
try {
  await page.goto(`${origin}/#/auth/login`)
  await page.locator('input[name="username"]').fill(credentials.username)
  await page.locator('input[name="password"]').fill(credentials.password)
  await page.locator('button[type="submit"]').click()
  await page.waitForURL(url => !url.hash.includes('/auth/login'))
  const reload = await page.request.post(`${origin}/api/v1/plugins/astrbot_plugin_whale_home/reload`)
  expect(reload.status()).toBe(200)
  const initial = await (await page.request.get(`${api}/state`)).json()
  const reset = await page.request.post(`${api}/skills/preferences`, { data: { request_id: crypto.randomUUID(), expected_version: initial.home.version,
    preferences: { enabled: true, access_mode: 'restricted', allowed_tools: [], allowed_skills: [] } } })
  expect(reset.status()).toBe(200)
  const url = `${origin}/#/plugin-view/astrbot_plugin_whale_home/home`
  await page.goto(url)
  const frame = page.frameLocator('iframe').first()
  await expect(frame.getByTestId('room')).toBeVisible({ timeout: 20000 })
  const dismiss = page.getByRole('button', { name: '关闭', exact: true })
  try { await dismiss.waitFor({ state: 'visible', timeout: 4000 }); await dismiss.click() }
  catch { /* The dashboard announcement may already have been dismissed. */ }
  await frame.getByRole('button', { name: '小家设置', exact: true }).click()
  const settings = frame.getByTestId('skills-settings')
  await expect(settings.getByLabel('技能访问模式')).toHaveValue('restricted')
  await expect(settings.locator('.skills-entry').first()).toBeVisible({ timeout: 10000 })
  await settings.getByLabel('启用技能与工具', { exact: true }).uncheck()
  await settings.getByRole('button', { name: '保存技能权限' }).click()
  await expect(frame.locator('.toast-message')).toContainText('技能权限已保存')
  let state = await (await page.request.get(`${api}/state`)).json()
  expect(state.skills.preferences.enabled).toBe(false)
  await settings.getByLabel('启用技能与工具', { exact: true }).check()
  await settings.getByLabel('技能访问模式').selectOption('full')
  await settings.getByRole('button', { name: '保存技能权限' }).click()
  await settings.getByRole('button', { name: '确认完全访问', exact: true }).click()
  await expect(frame.locator('.toast-message')).toContainText('技能权限已保存')
  await page.reload()
  await expect(frame.getByTestId('room')).toBeVisible({ timeout: 20000 })
  await frame.getByRole('button', { name: '小家设置', exact: true }).click()
  await expect(settings.getByLabel('技能访问模式')).toHaveValue('full')
  const archive = await (await page.request.get(`${api}/archives/export`)).json()
  expect(JSON.stringify(archive)).not.toContain('allowed_tools')
  const restored = await page.request.post(`${api}/archives/import`, { multipart: {
    file: { name: 'synthetic-home.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(archive)) },
  } })
  expect(restored.status()).toBe(200)
  await expect(settings.getByLabel('技能访问模式')).toHaveValue('restricted')
  state = await (await page.request.get(`${api}/state`)).json()
  expect(state.skills.preferences.allowed_tools).toEqual([])
  expect(state.home.settings.autonomous_enabled).toBe(false)
  expect(state.usage.chat + state.usage.autonomy + state.usage.interaction + state.usage.proactive).toBe(0)
  await settings.locator('h3').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'skills-host-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await settings.locator('h3').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'skills-host-mobile.png'), fullPage: true })
  expect(errors).toEqual([])
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify({ passed: true,
    checks: ['real iframe bridge', 'catalog', 'JSON-safe permission save', 'full access confirmation', 'reload persistence', 'SSE import reset', 'archive exclusion', 'zero model calls', 'desktop/mobile screenshots'], errors }, null, 2))
  console.log('PASS: real AstrBot iframe, catalog, permission saves, full-access confirmation, reload, SSE, archive reset; model calls=0')
} catch (error) { await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); throw error } finally { await context.close(); await browser.close() }
