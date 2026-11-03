import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import path from 'node:path'

const evidence=(name:string)=>path.join(process.env.PLAYWRIGHT_SCREENSHOTS_DIR || '../artifacts/release-v042/screenshots',name)

test.beforeEach(async ({ page, request }) => {
  const state = await (await request.get('/api/computer/state')).json()
  await request.post('/api/computer/preferences', { data: { request_id:randomUUID(),expected_version:state.version,
    preferences:{ ...state.preferences, enabled:false, autonomous_enabled:false, sites:[] } } })
  await page.goto('/')
  await page.getByRole('button',{name:'电脑',exact:true}).click()
})

test('computer uses its own panel and is disabled by default', async ({page, request}) => {
  await expect(page.getByRole('heading',{name:'她的电脑'})).toBeVisible()
  await expect(page.locator('.browser-empty')).toContainText('任务结束不保留截图')
  await page.getByLabel('上网任务').fill('查找鲸鱼睡眠研究')
  await expect(page.getByRole('button',{name:'开始上网',exact:true})).toBeDisabled()
  await expect(page.locator('.computer-task-sidebar')).toContainText('请在上网设置中启用电脑')
  const state = await (await request.get('/api/computer/state')).json()
  expect(state.usage.calls).toBe(0)
})

test('settings keep draft on refresh and provide three exploration modes', async ({page, request}) => {
  await page.getByRole('button',{name:'上网设置',exact:true}).click()
  await page.getByLabel('探索模式').selectOption('extended')
  await page.getByLabel('兴趣',{exact:true}).fill('海洋、天文学')
  await page.waitForTimeout(2300)
  await expect(page.getByLabel('兴趣',{exact:true})).toHaveValue('海洋、天文学')
  await page.getByLabel('授权网站域名').fill('www.example.com')
  await page.getByRole('button',{name:'添加网站',exact:true}).click()
  await page.getByLabel('当前账号（由你确认）').fill('测试账号')
  await page.getByLabel('允许登录后的阅读').check()
  await page.getByRole('button',{name:'保存上网设置',exact:true}).click()
  await expect.poll(async()=> (await (await request.get('/api/computer/state')).json()).preferences.mode).toBe('extended')
  const state=await (await request.get('/api/computer/state')).json()
  expect(state.preferences.sites[0].domain).toBe('www.example.com')
  expect(state.preferences.sites[0].like).toBe(false)
})

test('computer settings do not alter the home world version or enable tools',async({page,request})=>{
  const before=await (await request.get('/api/state')).json()
  await page.getByRole('button',{name:'上网设置',exact:true}).click()
  await page.getByText('高级预算与时段',{exact:true}).click()
  await page.getByLabel('每日模型调用上限').fill('99')
  await page.getByRole('button',{name:'保存上网设置',exact:true}).click()
  await expect.poll(async()=> (await (await request.get('/api/computer/state')).json()).preferences.daily_calls).toBe(99)
  const after=await (await request.get('/api/state')).json()
  expect(after.home.world_version).toBe(before.home.world_version)
  expect(after.skills.preferences).toEqual(before.skills.preferences)
})

test('reading panel and mobile layout do not overflow',async({page})=>{
  await page.setViewportSize({width:390,height:844})
  await page.getByRole('button',{name:'阅读与记忆',exact:true}).click()
  await expect(page.getByRole('heading',{name:'可追溯阅读记忆'})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:evidence('computer-mobile.png')})
})

test('clearing browser data requires explicit confirmation',async({page})=>{
  await page.getByRole('button',{name:'上网设置',exact:true}).click()
  await expect(page.getByRole('button',{name:'清除浏览器数据',exact:true})).toBeDisabled()
  await page.screenshot({path:evidence('computer-settings.png')})
})

test('environment diagnostics show the actual interpreter and copyable commands',async({page,request})=>{
  const environment=await (await request.get('/api/computer/environment')).json()
  await page.getByRole('button',{name:'上网设置',exact:true}).click()
  await page.getByRole('button',{name:'重新检测',exact:true}).click()
  await expect(page.locator('.computer-environment')).toContainText(environment.python_executable)
  await expect(page.getByRole('button',{name:'复制安装命令',exact:true})).toBeVisible()
  await expect(page.locator('.computer-environment')).toContainText('-m playwright install chromium')
})

test('unsaved settings prevent accidental navigation',async({page})=>{
  await page.getByRole('button',{name:'上网设置',exact:true}).click()
  await page.getByLabel('兴趣',{exact:true}).fill('未保存的兴趣')
  page.once('dialog',dialog=>dialog.dismiss())
  await page.getByRole('button',{name:'聊天',exact:true}).click()
  await expect(page.getByLabel('兴趣',{exact:true})).toHaveValue('未保存的兴趣')
  page.once('dialog',dialog=>dialog.accept())
  await page.getByRole('button',{name:'聊天',exact:true}).click()
  await expect(page.getByRole('heading',{name:'和她聊聊',exact:true})).toBeVisible()
})

test('external settings changes do not overwrite a draft or silently save over them',async({page,request})=>{
  await page.getByRole('button',{name:'上网设置',exact:true}).click()
  await page.getByLabel('兴趣',{exact:true}).fill('正在编辑')
  const state=await (await request.get('/api/computer/state')).json()
  await request.post('/api/computer/preferences',{data:{request_id:randomUUID(),preferences_version:state.preferences_version,expected_version:state.version,preferences:{...state.preferences,interests:'另一个窗口'}}})
  await page.waitForTimeout(200)
  await expect(page.getByLabel('兴趣',{exact:true})).toHaveValue('正在编辑')
  await page.getByRole('button',{name:'保存上网设置',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('其他页面')
  await page.getByRole('button',{name:'重新载入设置',exact:true}).click()
  await expect(page.getByLabel('兴趣',{exact:true})).toHaveValue('另一个窗口')
})

test('browser controls require takeover and mobile viewport remains bounded',async({page})=>{
  await expect(page.getByRole('button',{name:'前进',exact:true})).toBeDisabled()
  await expect(page.getByRole('button',{name:'刷新网页',exact:true})).toBeDisabled()
  await expect(page.getByLabel('手动输入文字')).toHaveCount(0)
  for(const width of [320,390,1440]) {
    await page.setViewportSize({width,height:900})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  }
  await page.screenshot({path:evidence('computer-desktop.png'),fullPage:true})
})

test('real rendered fixture fits browser panel and manual click carries the displayed frame',async({page,request,browser})=>{
  const source=await browser.newPage({viewport:{width:1100,height:760}})
  await source.setContent('<html lang="zh"><body style="margin:0;background:#eef5fa;font:18px system-ui;color:#183b56"><header style="background:#153d57;color:white;padding:25px">本地浏览器测试页 · 无账号 / 无模型调用</header><main style="padding:40px"><h1>鲸鱼如何睡觉？</h1><p>此页面只用于验证真实截图、缩放与人工接管坐标。</p><button style="padding:12px">阅读测试资料</button><hr><p>测试内容不是联网研究结论。</p></main></body></html>')
  const image='data:image/png;base64,'+(await source.screenshot()).toString('base64');await source.close()
  const state=await (await request.get('/api/computer/state')).json()
  state.preferences.enabled=true
  state.environment={ready:true,reason:'本地 UI 验证',revision:9999}
  state.task={id:'fixture-task',topic:'人工浏览布局验证',status:'paused',notice:'由你接管；未调用模型',phase:'paused',trigger:'manual',steps:0,max_steps:20,max_seconds:300,elapsed:0,summary:'',sources:[],interest:'',takeover:true,pending:null}
  const frame={frame_id:'fixture-frame',session_id:'fixture-session',page_version:'fixture-page',captured_at:new Date().toISOString(),viewport:{x:0,y:0,width:1100,height:760},width:1100,height:760,tab:'1',tabs:[{id:'1',url:'https://example.test/local-fixture'}],url:'https://example.test/local-fixture',title:'本地浏览器测试页',image,private:false,sensitive:false}
  await page.route('**/api/computer/state*',route=>route.fulfill({json:state}))
  await page.route('**/api/computer/environment*',route=>route.fulfill({json:state.environment}))
  await page.route('**/api/computer/frame*',route=>route.fulfill({json:frame}))
  const actions:any[]=[]
  await page.route('**/api/computer/manual',route=>{actions.push(route.request().postDataJSON());state.version++;return route.fulfill({json:state})})
  await page.reload();await page.getByRole('button',{name:'电脑',exact:true}).click()
  const screen=page.getByAltText('插件专属浏览器实时画面')
  await expect(screen).toBeVisible()
  await page.screenshot({path:evidence('browser-layout-desktop.png'),fullPage:true})
  await page.setViewportSize({width:320,height:900})
  const box=(await screen.boundingBox())!
  await screen.click({position:{x:box.width/2,y:box.height/2}})
  await expect.poll(()=>actions.length).toBe(1)
  expect(actions[0].frame_id).toBe('fixture-frame')
  // Browser pointer coordinates are CSS pixels; allow one scaled pixel of rounding.
  expect(Math.abs(actions[0].action.x-550)).toBeLessThan(1100/box.width+1)
  expect(Math.abs(actions[0].action.y-380)).toBeLessThan(760/box.height+1)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:evidence('browser-layout-mobile.png'),fullPage:true})
})

test('Chromium download needs confirmation, uses fixed API, supports progress and cancellation',async({page,request})=>{
  const state=await (await request.get('/api/computer/state')).json()
  state.environment={ready:false,reason:'尚未安装 Chromium',revision:99999,download_available:true,python_executable:'C:/AstrBot/python.exe',commands:['python -m playwright install chromium']}
  state.download={id:null,version:0,status:'idle',message:'等待下载',progress:null,lines:[]}
  await page.route('**/api/computer/state*',route=>route.fulfill({json:state}))
  await page.route('**/api/computer/environment*',route=>route.fulfill({json:state.environment}))
  const actions:any[]=[]
  await page.route('**/api/computer/download',route=>{
    actions.push(route.request().postDataJSON())
    state.download={id:'download-test',version:1,status:'downloading',message:'正在下载 Chromium',progress:30,lines:['Downloading Chromium 30%']}
    return route.fulfill({json:state})
  })
  await page.route('**/api/computer/cancel-download',route=>{
    actions.push(route.request().postDataJSON())
    state.download={...state.download,version:2,status:'cancelled',message:'下载已取消',progress:null}
    return route.fulfill({json:state})
  })
  await page.reload();await page.getByRole('button',{name:'电脑',exact:true}).click()
  await page.getByRole('button',{name:'下载 Chromium',exact:true}).click()
  expect(actions.length).toBe(0)
  const confirmation=page.getByRole('group',{name:'下载 Chromium 确认'})
  await expect(confirmation).toContainText('数百 MB')
  await confirmation.getByRole('button',{name:'暂不下载'}).click()
  expect(actions.length).toBe(0)
  await page.getByRole('button',{name:'下载 Chromium',exact:true}).click()
  await page.getByRole('button',{name:'确认下载',exact:true}).click()
  await expect(page.getByText('当前组件进度 30%（不是整体进度）',{exact:true})).toBeVisible()
  expect(Object.keys(actions[0]).sort()).toEqual(['confirm_download','request_id'])
  expect(actions[0].confirm_download).toBe(true)
  await expect(page.getByRole('button',{name:'重新检测',exact:true})).toBeDisabled()
  await page.setViewportSize({width:320,height:900})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:evidence('download-mobile.png'),fullPage:true})
  await page.getByRole('button',{name:'取消下载',exact:true}).click()
  expect(actions[1].download_id).toBe('download-test')
  await expect(page.getByText('下载已取消',{exact:true})).toBeVisible()
})

test('download connection failure does not auto retry and gives actionable message',async({page,request})=>{
  const state=await (await request.get('/api/computer/state')).json()
  state.environment={ready:false,reason:'尚未安装 Chromium',revision:99999,download_available:true}
  let count=0
  await page.route('**/api/computer/state*',route=>route.fulfill({json:state}))
  await page.route('**/api/computer/environment*',route=>route.fulfill({json:state.environment}))
  await page.route('**/api/computer/download',route=>{count++;return route.abort('failed')})
  await page.reload();await page.getByRole('button',{name:'电脑',exact:true}).click()
  await page.getByRole('button',{name:'下载 Chromium',exact:true}).click()
  await page.getByRole('button',{name:'确认下载',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('操作可能已受理')
  await page.waitForTimeout(1600)
  expect(count).toBe(1)
})

test('missing Python dependency does not offer browser download',async({page,request})=>{
  const state=await (await request.get('/api/computer/state')).json()
  state.environment={ready:false,reason:'AstrBot 当前 Python 未安装 Playwright',revision:99999,download_available:false}
  await page.route('**/api/computer/state*',route=>route.fulfill({json:state}))
  await page.route('**/api/computer/environment*',route=>route.fulfill({json:state.environment}))
  await page.reload();await page.getByRole('button',{name:'电脑',exact:true}).click()
  await expect(page.getByRole('button',{name:'下载 Chromium',exact:true})).toHaveCount(0)
  await expect(page.locator('.computer-environment')).toContainText('未安装 Playwright')
})
