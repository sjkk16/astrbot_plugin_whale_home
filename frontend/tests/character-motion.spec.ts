import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { openSettings } from './navigation'
const key='whale-home:character-renderer:v1'
let clean: Buffer

test.beforeAll(async({request})=>{clean=await (await request.get('/api/archives/export')).body()})
test.beforeEach(async({request})=>{
  const result=await request.post('/api/archives/import',{multipart:{file:{name:'clean.json',mimeType:'application/json',buffer:clean}}})
  const {home}=await result.json()
  await request.post('/api/settings',{data:{request_id:randomUUID(),expected_version:home.version,settings:{...home.settings,provider_id:'',autonomous_enabled:false,character_style:'portrait',portrait_asset:null,chibi_asset:null}}})
})

test('reviewed WebP is default and runtime has no model scripts',async({page})=>{
  const requests:string[]=[];page.on('request',r=>requests.push(r.url()))
  await page.goto('/')
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('data-renderer','webp')
  await openSettings(page,'角色与显示')
  await expect(page.getByTestId('character-render-mode')).toHaveValue('webp')
  await expect(page.getByTestId('character-render-mode').locator('option')).toHaveCount(2)
  await expect(page.getByTestId('character-motion-readiness')).toContainText('1/15')
  expect(requests.some(url=>/cubism|\.moc3|\/sdk\//i.test(url))).toBe(false)
})

test('legacy browser preference migrates without changing household archive',async({page,request})=>{
  await page.addInitScript(key=>localStorage.setItem(key,'live2d'),key)
  const before=(await (await request.get('/api/state')).json()).home.settings
  await page.goto('/')
  expect(await page.evaluate(key=>localStorage.getItem(key),key)).toBe('webp')
  await openSettings(page,'角色与显示')
  await page.getByTestId('character-render-mode').selectOption('static')
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('data-renderer','static')
  expect((await (await request.get('/api/state')).json()).home.settings).toEqual(before)
  expect(await (await request.get('/api/archives/export')).text()).not.toContain(key)
})

test('static preference persists across reload',async({page})=>{
  await page.goto('/');await openSettings(page,'角色与显示')
  await page.getByTestId('character-render-mode').selectOption('static')
  await page.reload();await openSettings(page,'角色与显示')
  await expect(page.getByTestId('character-render-mode')).toHaveValue('static')
})

test('reduced motion always displays static',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/')
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('data-renderer','static')
  await page.emulateMedia({reducedMotion:'no-preference'})
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('data-renderer','webp')
})

test('room and chat decode the verified transparent animation',async({page})=>{
  await page.goto('/')
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('data-renderer','webp')
  await page.getByRole('button',{name:'聊天',exact:true}).click()
  await expect(page.locator('.portrait-stage > img')).toHaveAttribute('data-renderer','webp')
  expect(await page.locator('.portrait-stage > img').evaluate((img:HTMLImageElement)=>[img.naturalWidth,img.naturalHeight])).toEqual([500,991])
})

test('tampered bytes fail closed to the original artwork',async({page})=>{
  await page.route('**/art/character-motion/portrait/idle-v1.webp',r=>r.fulfill({contentType:'image/webp',body:'tampered'}))
  await page.goto('/')
  await expect(page.getByTestId('room-renderer-status')).toContainText('加载失败')
  await expect(page.getByTestId('character').locator('img')).toHaveAttribute('src','./art/scene-portrait.webp')
})

test('disabled storage leaves the renderer usable',async({page})=>{
  await page.addInitScript(()=>{Storage.prototype.getItem=()=>{throw new Error('disabled')};Storage.prototype.setItem=()=>{throw new Error('disabled')}})
  await page.goto('/');await openSettings(page,'角色与显示')
  await expect(page.getByTestId('character-motion-storage-warning')).toBeVisible()
  await expect(page.getByTestId('character').locator('img')).toBeVisible()
})

test('320px character settings fit without horizontal scroll',async({page})=>{
  await page.setViewportSize({width:320,height:740});await page.goto('/');await openSettings(page,'角色与显示')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:`${process.env.PLAYWRIGHT_SCREENSHOTS_DIR || '../artifacts/release-v042/screenshots'}/character-mobile.png`,fullPage:true})
})
