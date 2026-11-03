import { defineConfig } from '@playwright/test'
import path from 'node:path'

process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.resolve('../.runtime/browsers')
process.env.PLAYWRIGHT_SCREENSHOTS_DIR ||= path.resolve('../artifacts/release-v042/screenshots')
const python = process.env.WHALE_HOME_PYTHON || path.resolve(process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python')

export default defineConfig({
  testDir: './tests',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || '../artifacts/playwright',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:18762', viewport: { width: 1440, height: 960 }, channel: process.env.PLAYWRIGHT_CHANNEL, headless: true, trace: 'retain-on-failure' },
  reporter: 'list',
  webServer: {
    command: `"${python}" -B "${path.resolve('../tools/dev_server.py')}" --port 18762${process.env.PLAYWRIGHT_STATIC_DIR ? ` --static-dir "${path.resolve(process.env.PLAYWRIGHT_STATIC_DIR)}" --interaction-preview` : ''} --data-dir "${path.resolve(`../.local/e2e-${Date.now()}`)}"`,
    url: 'http://127.0.0.1:18762/health',
    reuseExistingServer: false,
    timeout: 30000,
  },
})

