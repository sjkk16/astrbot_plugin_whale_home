import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs/promises'
import path from 'node:path'
const root = path.resolve(import.meta.dirname, '..')
const output = path.join(root, 'artifacts/screenshots/v020')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce' })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('http://127.0.0.1:18761')
  await page.getByTestId('room').waitFor()
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  await page.screenshot({ path: path.join(output, 'night-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.screenshot({ path: path.join(output, 'night-chat.png'), fullPage: true })
  await page.getByRole('button', { name: '关闭面板', exact: true }).click()
  for (const [name, width, height] of [['night-mobile',390,844], ['night-small',320,640]]) {
    await page.setViewportSize({ width, height })
    await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true })
    console.log(JSON.stringify({ name, overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), room: await page.getByTestId('room').boundingBox() }))
  }
  await page.getByRole('button', { name: '小家设置', exact: true }).click()
  await page.screenshot({ path: path.join(output, 'night-small-settings.png'), fullPage: true })
  console.log(JSON.stringify({ errors, output }))
} finally { await browser.close() }
