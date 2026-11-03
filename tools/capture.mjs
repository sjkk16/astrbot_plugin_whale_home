import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs/promises'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(root, '.runtime', 'browsers')
await fs.mkdir(path.join(root, 'artifacts', 'screenshots'), { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto('http://127.0.0.1:18761')
await page.waitForSelector('[data-testid="character"] img')
await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode().catch(() => {}))))
await page.screenshot({ path: path.join(root, 'artifacts', 'screenshots', 'preview-desktop.png'), fullPage: true })
console.log(JSON.stringify({ errors, title: await page.title(), images: await page.locator('img').count() }))
await browser.close()
