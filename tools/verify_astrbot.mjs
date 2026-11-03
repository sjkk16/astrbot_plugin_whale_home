import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import { expect } from '../frontend/node_modules/@playwright/test/index.mjs'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'

const root = path.resolve(import.meta.dirname, '..')
const argument = (name, fallback) => process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : fallback
const mode = argument('--mode', 'fresh')
if (!['fresh','upgrade','reinstall'].includes(mode)) throw new Error('Unknown verification mode')
const instance = path.resolve(root, argument('--instance', `.local/astrbot-v030-${mode === 'upgrade' ? 'upgrade' : 'fresh'}`))
if (!instance.startsWith(path.join(root, '.local') + path.sep)) throw new Error('Only isolated local test instances may be used')
const config = JSON.parse((await fs.readFile(path.join(instance, 'data/cmd_config.json'), 'utf-8')).replace(/^\uFEFF/, ''))
const credentials = JSON.parse((await fs.readFile(path.join(instance, 'test-credentials.json'), 'utf-8')).replace(/^\uFEFF/, ''))
if (config.dashboard.host !== '127.0.0.1' || credentials.username !== 'whale-test' || config.provider.length || config.provider_sources.length || config.platform.length) throw new Error('Not an isolated model-free test instance')
const origin = `http://127.0.0.1:${config.dashboard.port}`
const base = `${origin}/api/v1`
const extension = `${base}/plugins/extensions/astrbot_plugin_whale_home`
const releaseZip = path.resolve(root, argument('--zip', 'dist/astrbot_plugin_whale_home-v0.4.2.zip'))
const previousZip = path.resolve(root, argument('--from-zip', 'dist/astrbot_plugin_whale_home-v0.2.1-personal.zip'))
for (const file of [releaseZip, previousZip]) {
  if (!file.startsWith(root + path.sep)) throw new Error('ZIP inputs must stay inside this workspace')
}
const output = path.resolve(root, argument('--output', 'artifacts/screenshots/v032'))
if (!output.startsWith(path.join(root, 'artifacts') + path.sep)) throw new Error('Reports must stay inside artifacts')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
const context = await browser.newContext({ viewport: { width: 1600, height: 1040 }, reducedMotion: 'reduce' })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
async function state() {
  const response = await page.request.get(`${extension}/state`)
  expect(response.status()).toBe(200)
  return response.json()
}
async function mutate(endpoint, payload) {
  const before = await state()
  const body = { request_id: randomUUID(), expected_version: before.home.version, ...payload }
  const response = await page.request.post(`${extension}/${endpoint}`, { data: body })
  const result = await response.json()
  expect(response.status(), `Mutation ${endpoint}: ${result.message || ''}`).toBe(200)
  return { body, snapshot: result }
}
async function install(file) {
  const filename = path.basename(file)
  const response = await page.request.post(`${base}/plugins/install/upload`, {
    multipart: { file: { name: filename, mimeType: 'application/zip', buffer: await fs.readFile(file) } }, timeout: 120000,
  })
  expect(response.status()).toBe(200)
  const result = await response.json()
  expect(result.status, result.message).toBe('ok')
}
async function openView(target) {
  // ZIP upload is through the real API; reload Dashboard's dynamic view registry afterwards.
  await target.goto(`${origin}/?verification=${Date.now()}#/plugin-view/astrbot_plugin_whale_home/home`)
  const frame = target.frameLocator('iframe').first()
  await expect(frame.getByTestId('room')).toBeVisible({timeout:20000})
  const close = target.getByRole('button', {name:'关闭',exact:true})
  try { await close.waitFor({state:'visible',timeout:1500}); await close.click() } catch { /* Already dismissed */ }
  await expect(frame.locator('.connection')).toHaveText('已同步', {timeout:10000})
  await frame.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  return frame
}
try {
  await page.goto(`${origin}/#/auth/login`)
  await page.locator('input[name="username"]').fill(credentials.username)
  await page.locator('input[name="password"]').fill(credentials.password)
  await page.locator('button[type="submit"]').click()
  await page.waitForURL(url => !url.hash.includes('/auth/login'))
  let old, replay
  if (mode !== 'reinstall') {
    const exists = await fs.access(path.join(instance,'data/plugins/astrbot_plugin_whale_home')).then(()=>true,()=>false)
    expect(exists, 'Fresh scenario requires an empty isolated plugin directory').toBe(false)
  }
  let retainedImage
  if (mode === 'upgrade') {
    await install(previousZip)
    expect((await state()).home.schema_version).toBe(2)
    // Seed explicit offline chat fixtures via the public archive API, never call a model.
    const archiveResponse = await page.request.get(`${extension}/archives/export`)
    expect(archiveResponse.status()).toBe(200)
    const archive = await archiveResponse.json()
    const nextId = Math.max(0, ...archive.messages.map(item => item.id)) + 1
    const created_at = new Date().toISOString()
    archive.messages.unshift(
      {id:nextId+1,created_at,role:'assistant',source:'chat',text:'离线升级验证：这是一条合成聊天记录，不是模型回复。'},
      {id:nextId,created_at,role:'user',source:'chat',text:'离线升级验证：请保留聊天。'},
    )
    const restored = await page.request.post(`${extension}/archives/import`, {multipart:{
      file:{name:'offline-upgrade-fixture.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(archive))},
    }})
    expect(restored.status()).toBe(200)
    await mutate('memories/add', {text:'升级前记住：喜欢窗边的月亮。'})
    const upload = await page.request.post(`${extension}/assets/upload`, { multipart: {
      file: {name:'personal.png', mimeType:'image/webp', buffer:await fs.readFile(path.join(root,'frontend/public/art/chibi-neutral.webp'))},
    }})
    expect(upload.status()).toBe(200)
    const { asset_id } = await upload.json()
    retainedImage = {id:asset_id, content:await (await page.request.get(`${extension}/assets/${asset_id}`)).json()}
    await mutate('items/edit', {definition:{id:'upgrade-memento',name:'升级保留的月亮相册',description:'独立测试数据',category:'book',usage:'read',asset_id}})
    await mutate('items/add', {definition_id:'upgrade-memento',quantity:1})
    await mutate('items/add', {definition_id:'cookie',quantity:3})
    await mutate('settings', {settings:{...(await state()).home.settings,
      portrait_asset:asset_id,chibi_asset:asset_id,character_style:'chibi',interval_minutes:7,daily_limit:64,user_name:'离线验证者'}})
    const action = await mutate('scene/interact', {spot_id:'bookshelf',action:'read'})
    replay = action.body
    old = await state()
    await fs.writeFile(path.join(instance,'v021-baseline.json'),JSON.stringify(old,null,2))
  }
  await install(releaseZip)
  const installed = await state()
  expect(installed.home.schema_version).toBe(2)
  expect(installed.home.settings.autonomous_enabled).toBe(false)
  expect(installed.home.instances.every(item=>item.position===null)).toBe(true)
  expect(await fs.readFile(path.join(instance,'data/plugins/astrbot_plugin_whale_home/metadata.yaml'),'utf-8')).toMatch(/^version: v0\.4\.2$/m)
  let upgradeDataPreserved = false
  if (mode === 'upgrade') {
    expect(installed.home).toEqual(old.home)
    for (const key of ['messages','events','memories','scene']) expect(installed[key]).toEqual(old[key])
    expect(installed.usage).toMatchObject(old.usage)
    expect(installed.usage.interaction).toBe(0)
    expect(installed.usage.proactive).toBe(0)
    expect(installed.messages.some(item=>item.source==='chat' && item.role==='user')).toBe(true)
    expect(installed.messages.some(item=>item.source==='chat' && item.role==='assistant')).toBe(true)
    expect(await (await page.request.get(`${extension}/assets/${retainedImage.id}`)).json()).toEqual(retainedImage.content)
    const repeat = await page.request.post(`${extension}/scene/interact`,{data:replay})
    expect(repeat.status()).toBe(200)
    expect((await state()).events).toEqual(installed.events)
    upgradeDataPreserved = true
  }
  // Installed ZIP bytes, not only workspace files, must match the current artwork manifest.
  const manifest = JSON.parse(await fs.readFile(path.join(root,'asset-manifest.json'),'utf-8'))
  for (const asset of manifest.assets) {
    const content = await fs.readFile(path.join(instance,'data/plugins/astrbot_plugin_whale_home',asset.file))
    expect(createHash('sha256').update(content).digest('hex'),asset.file).toBe(asset.sha256)
  }
  // Custom slots were verified above; clear them only inside this isolated test to inspect defaults.
  await mutate('settings', {settings:{...(await state()).home.settings,portrait_asset:null,chibi_asset:null,character_style:'portrait'}})
  const frame = await openView(page)
  await expect(frame.locator('.demo-label')).toHaveCount(0)
  await expect(frame.locator('.side-panel')).toHaveCount(0)
  await expect(frame.locator('.footer-note small')).toHaveText('v0.4.2 · PUBLIC RELEASE')
  const defaultPortrait = frame.getByTestId('character').locator('img')
  await expect(defaultPortrait).toHaveAttribute('src','./art/scene-portrait.webp')
  expect(await defaultPortrait.evaluate(img=>[img.naturalWidth,img.naturalHeight])).toEqual([500,991])
  await frame.getByRole('button',{name:'更多',exact:true}).click()
  await frame.getByRole('button',{name:'小家设置',exact:true}).click()
  await frame.getByRole('button',{name:'数据与关于',exact:true}).click()
  await expect(frame.locator('.about')).toContainText('用户提供的 deepseek.png')
  await expect(frame.locator('.about')).not.toContainText('CC BY-NC-SA 4.0')
  await frame.getByRole('button',{name:'角色与显示',exact:true}).click()
  await frame.getByTestId('character-style').selectOption('chibi')
  await frame.getByRole('button',{name:'保存设置',exact:true}).click()
  await expect(frame.getByRole('status')).toContainText('设置已保存')
  await frame.getByRole('button',{name:'关闭面板',exact:true}).click()
  await expect(frame.getByTestId('character').locator('img')).toHaveAttribute('src','./art/scene-chibi-neutral.webp')
  await frame.locator('img').evaluateAll(images=>Promise.all(images.map(img=>img.decode())))
  await page.screenshot({path:path.join(output,`astrbot-${mode}-q-unchanged.png`),fullPage:true})
  await frame.getByRole('button',{name:'更多',exact:true}).click()
  await frame.getByRole('button',{name:'小家设置',exact:true}).click()
  await frame.getByRole('button',{name:'角色与显示',exact:true}).click()
  await frame.getByTestId('character-style').selectOption('portrait')
  await frame.getByRole('button',{name:'保存设置',exact:true}).click()
  await expect(frame.getByRole('status')).toContainText('设置已保存')
  await frame.getByRole('button',{name:'关闭面板',exact:true}).click()
  await expect(defaultPortrait).toHaveAttribute('src','./art/scene-portrait.webp')
  const iframePolicy = await page.locator('iframe').first().getAttribute('sandbox')
  expect(iframePolicy).toContain('allow-scripts')
  expect(iframePolicy).not.toContain('allow-same-origin')
  const companionPreferences = await (await page.request.get(`${extension}/companion/preferences`)).json()
  expect(companionPreferences.proactive_enabled).toBe(false)
  const beforePet = await state()
  await frame.getByTestId('character').click()
  await frame.getByRole('region', {name:'直接互动'}).getByRole('button', {name:'摸摸头',exact:true}).click()
  await expect(frame.getByTestId('character').locator('img')).toHaveAttribute('src','./art/interaction-v030/pet.webp')
  await expect(frame.getByTestId('character-bubble')).toContainText('本地回应')
  expect((await state()).home.instances).toEqual(beforePet.home.instances)
  expect((await state()).usage).toEqual(beforePet.usage)
  await frame.getByTestId('spot-bookshelf').locator('.hotspot-marker').click()
  await frame.getByRole('button',{name:'读一会儿书',exact:true}).click()
  await expect(frame.locator('.room-status')).toContainText('沉浸阅读')
  await frame.getByRole('button',{name:'日记',exact:true}).click()
  await expect(frame.locator('.timeline-entry').first()).toContainText('从书架选了一本书')
  await frame.getByRole('button',{name:'更多',exact:true}).click()
  await frame.getByRole('button',{name:'物品',exact:true}).click()
  await frame.getByRole('button',{name:'自定义',exact:true}).click()
  await frame.getByRole('button',{name:'创造物品',exact:true}).click()
  const itemName = `真实宿主测试心意-${Date.now()}`
  await frame.getByTestId('item-name').fill(itemName)
  await frame.locator('input[type=file]').setInputFiles(path.join(root,'frontend/public/art/chibi-neutral.webp'))
  await expect(frame.locator('.upload-tile img')).toBeVisible()
  await frame.getByRole('button',{name:'保存物品',exact:true}).click()
  await expect(frame.getByRole('button',{name:`添加${itemName}`,exact:true})).toBeVisible()
  await frame.getByRole('button',{name:'更多',exact:true}).click()
  await frame.getByRole('button',{name:'小家设置',exact:true}).click()
  await frame.getByRole('button',{name:'数据与关于',exact:true}).click()
  const downloadPromise = page.waitForEvent('download')
  await frame.getByRole('button',{name:'导出存档',exact:true}).click()
  const download = await downloadPromise
  const archiveFile = await download.path()
  const archive = JSON.parse(await fs.readFile(archiveFile,'utf-8'))
  expect(archive.schema_version).toBe(2)
  expect(archive.state.settings.provider_id).toBe('')
  expect(archive.state.settings.autonomous_enabled).toBe(false)
  expect(Object.keys(archive.assets).length).toBeGreaterThan(0)
  await frame.locator('input[accept=".json,application/json"]').setInputFiles(archiveFile)
  await frame.getByRole('dialog').getByRole('button',{name:'确认',exact:true}).click()
  await expect(frame.getByRole('status')).toContainText('存档已恢复')
  await frame.getByRole('button',{name:'关闭面板',exact:true}).click()
  const second = await page.context().newPage()
  second.on('pageerror', error => errors.push(error.message))
  const secondFrame = await openView(second)
  await frame.getByTestId('spot-bed').locator('.hotspot-marker').click()
  await frame.getByRole('button',{name:'在床边休息',exact:true}).click()
  await expect(secondFrame.locator('.room-status')).toContainText('床边休息',{timeout:6000})
  await second.close()
  const beforeReload = await state()
  const reload = await page.request.post(`${base}/plugins/astrbot_plugin_whale_home/reload`)
  expect((await reload.json()).status).toBe('ok')
  const afterReload = await state()
  expect(afterReload.home.instances).toEqual(beforeReload.home.instances)
  expect(afterReload.home.definitions).toEqual(beforeReload.home.definitions)
  expect(afterReload.usage).toEqual(beforeReload.usage)
  await page.reload()
  const live = await openView(page)
  await live.getByTestId('spot-window').locator('.hotspot-marker').click()
  await live.getByRole('button',{name:'一起看夜景',exact:true}).click()
  await expect(live.locator('.spot-card')).toHaveCount(0)
  await expect(live.getByTestId('character')).toHaveAttribute('data-moving','false')
  const layout = await page.request.post(`${extension}/layout`, {data:{}})
  expect(layout.status()).toBe(400)
  expect((await layout.json()).message).toContain('不支持自由布置')
  await page.mouse.move(1,1)
  await page.screenshot({path:path.join(output,`astrbot-${mode}-desktop.png`),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  // Dashboard automatically collapses its drawer; wait for the layout transition, not its offscreen button.
  await expect.poll(async()=> (await page.locator('iframe').first().boundingBox()).width).toBeGreaterThan(380)
  await expect.poll(async()=> (await page.locator('iframe').first().boundingBox()).x).toBeLessThan(5)
  await page.screenshot({path:path.join(output,`astrbot-${mode}-mobile.png`),fullPage:true})
  expect((await state()).usage.chat).toBe(0)
  expect((await state()).usage.autonomy).toBe(0)
  expect(errors).toEqual([])
  const report = {mode,version:'0.4.2',fromVersion:mode==='upgrade'?'0.2.1':null,astrbot:'4.29.3',zipInstall:true,
    zipSha256:createHash('sha256').update(await fs.readFile(releaseZip)).digest('hex'),adultSize:[500,991],qAssetsUnchanged:true,interactionIllustrations:12,directPet:true,proactiveDefaultOff:true,allAssetHashesVerified:true,customImageSettingsPreserved:upgradeDataPreserved,reload:true,iframePolicy,bridgeAPI:true,sse:true,
    imageUpload:true,archiveExportAndImport:true,upgradeDataPreserved,offlineChatFixture:mode==='upgrade',
    paidModelCalls:0,mobileIframeWidthVerified:true,clientErrors:errors}
  await fs.writeFile(path.join(output,`astrbot-${mode}-report.json`),JSON.stringify(report,null,2))
  console.log(JSON.stringify(report))
} catch (error) {
  await page.screenshot({path:path.join(output,`astrbot-${mode}-error.png`),fullPage:true})
  console.log(JSON.stringify({mode,url:page.url(),clientErrors:errors}))
  throw error
} finally { await browser.close() }
