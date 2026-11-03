<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import type { Bridge, Provider } from '../types'
import type { BrowserFrame, ComputerPreferences, ComputerState, ComputerTask, ReadingMemory, ComputerEnvironment } from '../computer-types'
const clonePrefs = (value: ComputerPreferences): ComputerPreferences => JSON.parse(JSON.stringify(value))
const props = defineProps<{ bridge: Bridge; providers: Provider[]; initialTab?: 'screen' | 'settings' }>()
const emit = defineEmits<{ dirty: [boolean] }>()
const state = ref<ComputerState>()
const draft = ref<ComputerPreferences>()
const frame = ref<BrowserFrame | null>(null)
const history = ref<ComputerTask[]>([])
const memories = ref<ReadingMemory[]>([])
const busy = ref(false)
const controlBusy = ref(false)
const detecting = ref(false)
const downloadBusy = ref(false)
const downloadConfirm = ref(false)
const downloading = computed(() => ['preparing','downloading','verifying','cancelling'].includes(state.value?.download?.status || ''))
const taskOpen = ref(true)
const warning = ref('')
const draftVersion = ref(0)
let baseline = ''
let failures = 0
let lastStateCheck = 0
let frameSequence = 0
const error = ref('')
const topic = ref('')
const address = ref('https://www.bing.com/')
const manualText = ref('')
const domain = ref('')
const domains = ref('')
const tab = ref<'screen' | 'settings' | 'reading'>(props.initialTab || 'screen')
const resumeConfirm = ref(false)
const clearConfirm = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let refreshing = false
const labels: Record<string, string> = { running:'正在上网', paused:'已暂停', waiting_user:'等待确认', completed:'已完成', failed:'失败', stopped:'已停止', unknown:'结果未确认' }
const phases: Record<string,string> = {preparing:'准备浏览器',observing:'读取页面',thinking:'模型理解',acting:'执行操作'}
const manual = computed(() => Boolean(state.value?.task?.takeover && state.value.task.status === 'paused'))
const safeUrl = (url: string) => /^https?:\/\//i.test(url) ? url : undefined
const budgets: { key: 'start_hour'|'end_hour'|'interval_minutes'|'daily_runs'|'extended_daily_runs'|'minutes'|'steps'|'extended_minutes'|'extended_steps'|'daily_calls'; label: string; min: number; max: number }[] = [
  {key:'start_hour',label:'开始时刻',min:0,max:23},{key:'end_hour',label:'结束时刻',min:0,max:24},
  {key:'interval_minutes',label:'检查间隔（分钟）',min:15,max:1440},{key:'daily_runs',label:'普通每日轮数',min:1,max:24},
  {key:'extended_daily_runs',label:'长阅读每日轮数',min:1,max:8},{key:'minutes',label:'普通每轮分钟',min:1,max:30},
  {key:'steps',label:'普通每轮步骤',min:1,max:100},{key:'extended_minutes',label:'长阅读每轮分钟',min:1,max:60},
  {key:'extended_steps',label:'长阅读每轮步骤',min:1,max:200},{key:'daily_calls',label:'每日模型调用上限',min:1,max:1000},
]
const dirty = computed(() => !!draft.value && (JSON.stringify(draft.value) !== baseline || domains.value !== draft.value.domains.join('\n')))
watch(dirty, value => emit('dirty', value))
function resetDraft() {
  if (!state.value) return
  draft.value = clonePrefs(state.value.preferences)
  domains.value = draft.value.domains.join('\n')
  baseline = JSON.stringify(draft.value)
  draftVersion.value = state.value.preferences_version
}
function acceptState(next: ComputerState) {
  if (disposed || (state.value && next.version < state.value.version)) return
  if(state.value && (next.environment.revision || 0) < (state.value.environment.revision || 0)) next.environment=state.value.environment
  if(state.value?.download && (next.download?.version || 0) < state.value.download.version) next.download=state.value.download
  state.value = next
  if (!draft.value || !dirty.value) resetDraft()
}
async function refreshState() {
  if (refreshing || disposed) return
  refreshing = true
  try { acceptState(await props.bridge.apiGet<ComputerState>('computer/state')); lastStateCheck = Date.now() }
  finally { refreshing = false }
}
async function refreshFrame() {
  if (disposed || document.hidden || tab.value !== 'screen') return
  const sequence = ++frameSequence
  const result = await props.bridge.apiGet<BrowserFrame | {unchanged: true} | null>('computer/frame', frame.value?.frame_id ? {since: frame.value.frame_id} : {})
  if (disposed || sequence !== frameSequence) return
  if (!result || !('unchanged' in result)) {
    frame.value = result
    if (result && document.activeElement?.getAttribute('aria-label') !== '浏览器地址') address.value = result.url
  }
}
async function refresh() {
  try { await refreshState(); await refreshFrame(); failures=0 }
  catch (e) { error.value = connectionMessage(e); failures++ }
}
async function detect() {
  if (detecting.value || downloading.value) return
  detecting.value=true
  try { const environment=await props.bridge.apiGet<ComputerEnvironment>('computer/environment'); if(state.value && !disposed) state.value.environment=environment }
  catch(e) { error.value=connectionMessage(e) }
  finally { detecting.value=false }
}
function connectionMessage(e:unknown) {
  const message=e instanceof Error?e.message:String(e)
  return /failed to fetch|networkerror|load failed/i.test(message)
    ? '与 AstrBot 的连接中断。操作可能已受理，请刷新下载状态，不要重复点击下载；若刚重启请等待后再刷新。'
    : message
}
async function downloadCommand(cancel=false) {
  if(downloadBusy.value) return
  downloadBusy.value=true;error.value=''
  try {
    const payload=cancel?{download_id:state.value?.download?.id}:{confirm_download:true}
    acceptState(await props.bridge.apiPost<ComputerState>(cancel?'computer/cancel-download':'computer/download',{
      request_id:crypto.randomUUID(),...payload
    }))
    downloadConfirm.value=false
  } catch(e) { error.value=connectionMessage(e) }
  finally { downloadBusy.value=false }
}
async function copyCommands() {
  try { await navigator.clipboard.writeText(state.value?.environment.commands?.join('\n') || ''); warning.value='已复制，请在 AstrBot 所在机器执行。' }
  catch { warning.value='无法访问剪贴板，请手动选中下面的命令复制。' }
}
async function command(endpoint: string, payload: Record<string, unknown> = {}) {
  const control = endpoint === 'stop' || endpoint === 'takeover'
  if (control ? controlBusy.value : busy.value) return false
  if(control) controlBusy.value=true; else busy.value=true
  error.value=''; warning.value=''
  const taskId=state.value?.task?.id || null
  try {
    if (!control) await refreshState()
    const extra=control ? {task_id:taskId} : endpoint === 'preferences' ? {preferences_version:draftVersion.value} : {}
    acceptState(await props.bridge.apiPost<ComputerState>(`computer/${endpoint}`, JSON.parse(JSON.stringify({ ...payload, ...extra, request_id:crypto.randomUUID(), expected_version:state.value?.version }))))
    try { await refreshFrame() } catch { warning.value='操作已完成，但画面刷新失败。请刷新画面，不要重复提交。' }
    return true
  } catch (e) { error.value=e instanceof Error ? e.message : '操作未确认，请检查状态；不会自动重试'; await refreshState().catch(()=>{}); return false }
  finally { if(control) controlBusy.value=false; else busy.value=false }
}
async function save() {
  if (!draft.value) return
  draft.value.domains=domains.value.split(/[\s,，]+/).filter(Boolean)
  if(await command('preferences',{preferences:draft.value})) { resetDraft(); warning.value='上网设置已保存' }
}
function selectTab(next: 'screen'|'settings'|'reading') {
  if(tab.value === 'settings' && next !== 'settings' && dirty.value) {
    if(!window.confirm('上网设置尚未保存，确定放弃修改？')) return false
    resetDraft()
  }
  tab.value=next
  return true
}
async function readings() {
  if(!selectTab('reading')) return
  try { history.value=await props.bridge.apiGet('computer/history'); memories.value=await props.bridge.apiGet('computer/memories') }
  catch(e) { error.value=connectionMessage(e) }
}
async function manualCommand(action: Record<string, unknown>) {
  if(!manual.value) return
  await command('manual',{action,frame_id:frame.value?.frame_id})
}
async function clickFrame(event: MouseEvent) {
  if(!manual.value || !frame.value) return
  const box=(event.currentTarget as HTMLImageElement).getBoundingClientRect()
  await manualCommand({action:'manual_click',x:(event.clientX-box.left)/box.width*frame.value.width,y:(event.clientY-box.top)/box.height*frame.value.height})
}
async function sendText() { const text=manualText.value; manualText.value=''; await manualCommand({action:'manual_text',text}) }
function addSite() {
  if(!draft.value || !domain.value.trim()) return
  draft.value.sites.push({domain:domain.value.trim(),account:'',authenticated_read:false,like:false,favorite:false}); domain.value=''
}
async function poll() {
  if(!document.hidden) {
    try { if(Date.now()-lastStateCheck > 15000) await refreshState(); if(!busy.value && !controlBusy.value) await refreshFrame(); failures=0 }
    catch(e) { error.value=connectionMessage(e); failures++ }
  }
  if(!disposed) timer=setTimeout(poll, Math.min(15000,1000*2**Math.min(failures,4)))
}
function changed() { if(!document.hidden) void refreshState().catch(e=>{error.value=connectionMessage(e)}) }
function beforeUnload(event: BeforeUnloadEvent) { if(dirty.value) { event.preventDefault(); event.returnValue='' } }
onMounted(async()=>{ window.addEventListener('whale-computer-changed',changed); document.addEventListener('visibilitychange',changed); window.addEventListener('beforeunload',beforeUnload); await refresh(); if(!disposed) { void detect(); void poll() } })
onBeforeUnmount(()=>{ disposed=true; frameSequence++; clearTimeout(timer); frame.value=null; manualText.value=''; window.removeEventListener('whale-computer-changed',changed); document.removeEventListener('visibilitychange',changed); window.removeEventListener('beforeunload',beforeUnload); emit('dirty',false) })
</script>
<template>
<div class="computer-panel panel-scroll">
  <nav class="computer-tabs" aria-label="电脑页面">
    <button :aria-pressed="tab==='screen'" @click="selectTab('screen'); refresh()">浏览器</button>
    <button :aria-pressed="tab==='settings'" @click="selectTab('settings')">上网设置</button>
    <button :aria-pressed="tab==='reading'" @click="readings">阅读与记忆</button>
  </nav>
  <p v-if="error" role="alert" class="computer-warning">{{error}} <button @click="refresh">刷新状态</button></p>
  <p v-if="warning" role="status" class="computer-warning">{{warning}}</p>
  <p v-if="!state">正在连接电脑…</p>
  <template v-else>
    <p class="computer-subtle">专属 Chromium · 今日 {{state.usage.calls}}/{{state.preferences.daily_calls}} 次模型调用 · 可能产生费用</p>
    <section v-if="!state.environment.ready || tab==='settings' || downloading || state.download?.status==='failed'" class="computer-environment">
      <strong>{{state.environment.reason}}</strong>
      <div class="computer-controls"><button :disabled="detecting || downloading" @click="detect">{{detecting?'正在检测…':'重新检测'}}</button><button v-if="state.environment.commands?.length" @click="copyCommands">复制安装命令</button><button v-if="state.environment.download_available && !downloading" :disabled="downloadBusy" @click="downloadConfirm=true">{{state.environment.ready?'检查 / 补全 Chromium':'下载 Chromium'}}</button><button v-if="downloading" :disabled="downloadBusy || state.download?.status==='cancelling'" @click="downloadCommand(true)">取消下载</button></div>
      <div v-if="downloadConfirm" class="computer-warning" role="group" aria-label="下载 Chromium 确认">
        <p>将在 AstrBot 所在机器从 Playwright 官方来源下载并安装 Chromium，可能占用数百 MB 流量和磁盘空间（建议预留 2 GB）。只执行固定浏览器安装命令，不安装 Python 包、不调用模型。关闭页面后下载继续；最多等待 20 分钟，重启不自动续跑。请先停止电脑任务。</p>
        <button :disabled="downloadBusy || downloading" @click="downloadCommand()">确认下载</button><button :disabled="downloadBusy" @click="downloadConfirm=false">暂不下载</button>
      </div>
      <div v-if="state.download && state.download.status!=='idle'" role="status" class="computer-download">
        <strong>{{state.download.message}}</strong><p v-if="state.download.persistence_error" class="computer-warning">{{state.download.persistence_error}}</p>
        <p v-if="downloading && state.download.progress!==null">当前组件进度 {{state.download.progress}}%（不是整体进度）</p>
        <details v-if="state.download.lines.length"><summary>下载日志（最近 15 行）</summary><pre>{{state.download.lines.join('\n')}}</pre></details>
        <p v-if="state.download.status==='failed' || state.download.status==='interrupted'">不会自动重试。请检查日志、网络和剩余磁盘空间，再重新检测或确认下载。</p>
      </div>
      <details :open="!state.environment.ready"><summary>运行环境与安装说明</summary>
        <p>Python {{state.environment.python_version || '待检测'}} · Playwright {{state.environment.playwright_version || '未检测到'}}</p>
        <p>{{state.environment.launch_mode || 'Playwright 管理的独立 Chromium'}}</p>
        <code>{{state.environment.python_executable}}</code><p>{{state.environment.chromium_path}}</p>
        <pre v-if="state.environment.detail">{{state.environment.detail}}</pre>
        <pre>{{state.environment.commands?.join('\n')}}</pre>
        <p>安装包不含 Chromium。先安装 Playwright Python 依赖，再点击上方按钮下载；只有你确认后才下载。浏览器保存在插件数据目录，不使用日常 Chrome / Edge。Linux 可能还需要手动安装系统依赖。</p>
      </details>
    </section>
    <template v-if="tab==='screen'">
      <div class="computer-controls"><button :disabled="controlBusy || !state.task" @click="command('stop')">停止</button><button :disabled="controlBusy || downloading || !state.environment.ready || !state.preferences.enabled" @click="command('takeover')">接管 / 手动登录</button><button :disabled="busy || state.task?.status!=='paused'" @click="resumeConfirm=true">继续 AI 阅读</button><button :aria-expanded="taskOpen" @click="taskOpen=!taskOpen">任务与结果</button></div>
        <div v-if="state.task" class="computer-status" role="status"><strong>{{ labels[state.task.status] || state.task.status }}</strong><span>{{ state.task.notice }}</span><small>{{ phases[state.task.phase || ''] || labels[state.task.status] }} · 步骤 {{ state.task.steps }}/{{ state.task.max_steps }} · {{ state.task.trigger === 'autonomy' ? '自主探索' : '手动任务' }}</small></div>
        <div v-if="resumeConfirm" class="computer-warning" role="group" aria-label="恢复阅读确认">
          <p>请先离开密码、验证码页面，并在上网设置中重新授权精确域名及当前账号。恢复后，网页内容和截图会发送给你选择的模型供应商。</p>
          <button :disabled="busy" @click="command('resume',{confirm_content_sharing:true}).then(ok => { if(ok) resumeConfirm=false })">确认共享并继续</button>
          <button @click="resumeConfirm=false">取消</button>
        </div>
        <div v-if="state.task?.pending" class="computer-warning" role="group" aria-label="网站操作确认">
          <h3>确认对外操作</h3><p>网站：{{ state.task.pending.domain }}<br>账号（你声明）：{{ state.task.pending.account }}<br>目标：{{ state.task.pending.target }}<br>动作：{{ state.task.pending.action.intent }} / {{ state.task.pending.action.action }}</p>
          <a :href="safeUrl(state.task.pending.url)" target="_blank" rel="noopener noreferrer">目标页面</a>
          <pre>{{ state.task.pending.content || '（无文字内容）' }}</pre>
          <p>确认仅适用于当前页面和内容，五分钟后失效。无法核实当前账号时请拒绝并接管。</p>
          <button :disabled="busy" @click="command('confirm',{token:state.task!.pending!.token,approve:true})">确认执行这一次</button>
          <button :disabled="busy" @click="command('confirm',{token:state.task!.pending!.token,approve:false})">拒绝</button>
        </div>
<div class="computer-workspace" :class="{'task-collapsed':!taskOpen}"><section class="computer-browser">
  <div class="browser-tabs"><span v-for="item in frame?.tabs" :key="item.id"><button :disabled="!manual || busy" :aria-pressed="item.id===frame?.tab" @click="manualCommand({action:'tab',target:item.id})">{{item.id}} · {{item.url.slice(0,38)}}</button><button :disabled="!manual || busy || (frame?.tabs.length || 0)<2" aria-label="关闭标签页" @click="manualCommand({action:'close_tab',target:item.id})">×</button></span><button :disabled="!manual || busy" @click="manualCommand({action:'open',target:address,new_tab:true})">新标签页</button></div>
  <form class="browser-address" @submit.prevent="manualCommand({action:'open',target:address})"><button type="button" :disabled="!manual || busy" @click="manualCommand({action:'back'})">后退</button><button type="button" :disabled="!manual || busy" @click="manualCommand({action:'forward'})">前进</button><button type="button" :disabled="!manual || busy" @click="manualCommand({action:'reload'})">刷新网页</button><input v-model="address" :disabled="!manual" aria-label="浏览器地址" placeholder="https://…"><button :disabled="!manual || busy">打开</button></form>
        <div class="browser-frame">
          <template v-if="frame">
            <div class="browser-title"><strong>{{ frame.title || '新标签页' }}</strong><small>{{ frame.url }}</small></div>
            <img :src="frame.image" alt="插件专属浏览器实时画面" :class="{ interactive: manual }" @click="clickFrame">
            <small>真实浏览器截图，不是嵌入网页。{{ manual ? '点击画面进行人工操作。' : 'AI 操作中，接管后才能手动操作。' }}</small>
          </template>
          <div v-else class="browser-empty"><strong>她的电脑</strong><p>开始任务或接管后显示真实网页。</p><p>任务结束不保留截图；结论在阅读记录中。</p></div>
        </div>
 <div v-if="manual" class="computer-controls"><button :disabled="busy" @click="manualCommand({action:'scroll',target:'up'})">向上</button><button :disabled="busy" @click="manualCommand({action:'scroll',target:'down'})">向下</button></div>
        <div v-if="manual" class="computer-manual">
          <p>现在由你操作，AI 已暂停。点击画面聚焦控件，再输入文字。账号权限在接管时已撤销，需要重新保存。</p>
          <form @submit.prevent="sendText"><input v-model="manualText" type="password" autocomplete="off" aria-label="手动输入文字" placeholder="文字仅发给网页，发送后清空"><button :disabled="busy">输入到网页</button></form>
          <div class="computer-controls"><button v-for="key in ['Tab','Enter','Backspace','Escape']" :key="key" :disabled="busy" @click="manualCommand({action:'manual_key',target:key})">{{ key }}</button></div>
        </div></section><aside v-show="taskOpen" class="computer-task-sidebar" aria-label="任务与结果">
  <form class="computer-task-form" @submit.prevent="command('start',{topic})"><label>上网任务<textarea v-model="topic" maxlength="2000" rows="3" placeholder="例如：查找鲸鱼睡眠研究，比较来源后告诉我。" /></label><button class="button primary" :disabled="busy || downloading || !topic.trim() || !state.environment.ready || !state.preferences.enabled">开始上网</button></form>
  <p v-if="!state.preferences.enabled || !state.preferences.provider_id" class="computer-warning">请在上网设置中启用电脑、选择图文模型并确认内容共享。</p>
  <p v-if="state.task?.summary" class="computer-summary">{{state.task.summary}}</p>
  <ul><li v-for="source in state.task?.sources" :key="source.url"><a :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer">{{source.title || source.url}}</a></li></ul>
</aside></div></template>
      <form v-else-if="tab === 'settings' && draft" class="computer-settings" @submit.prevent="save">
        <h3>电脑与图文模型</h3>
        <label class="check"><input v-model="draft.enabled" type="checkbox">启用电脑功能</label>
        <label>上网模型<select v-model="draft.provider_id" aria-label="上网模型"><option value="">选择支持图片的模型</option><option v-for="provider in providers" :key="provider.id" :value="provider.id">{{ provider.name }}</option></select></label>
        <p>使用 AstrBot 中现有的图文模型，不保存密钥。不支持图片的模型会报错；不会偷偷切成演示模式。宿主供应商自身的重试和计费规则仍有效。</p>
        <label class="check"><input v-model="draft.vision_consent" type="checkbox">我理解网页正文和截图将发送给所选模型供应商</label>
        <label>搜索引擎<select v-model="draft.search_engine"><option value="bing">Bing</option><option value="duckduckgo">DuckDuckGo</option></select></label>
        <h3>自主探索</h3>
        <label class="check"><input v-model="draft.autonomous_enabled" type="checkbox">允许自主上网（还需开启小家的自主生活）</label>
        <label>探索模式<select v-model="draft.mode"><option value="interest">兴趣驱动</option><option value="focused">指定主题</option><option value="extended">长时间探索</option></select></label>
        <label>兴趣<textarea v-model="draft.interests" maxlength="2000" rows="2" /></label>
        <label>指定主题<textarea v-model="draft.topics" maxlength="2000" rows="2" /></label>
        <label>指定模式允许的精确域名（每行一个，可留空）<textarea v-model="domains" rows="2" /></label>
        <details><summary>高级预算与时段</summary><div class="computer-budget"><label v-for="field in budgets" :key="field.key">{{ field.label }}<input v-model.number="draft[field.key]" type="number" :min="field.min" :max="field.max" required></label></div></details>
        <p>时段遵循小家时区。等待你确认时不继续调用模型。次数/时间上限不保证金额；不补跑离线任务。</p>
        <h3>网站和账号授权</h3>
        <p>默认公开阅读。精确域名不扩展到子域名。接管或切换账号后需重新授权；请准确填写当前账号。评论、发布和私信始终逐次确认。付款、删除、账号安全操作请手动接管。</p>
        <div v-for="(site,index) in draft.sites" :key="index" class="computer-site">
          <strong>{{ site.domain }}</strong><label>当前账号（由你确认）<input v-model="site.account" maxlength="100" placeholder="账号昵称或标识"></label>
          <label class="check"><input v-model="site.authenticated_read" type="checkbox">允许登录后的阅读</label>
          <label class="check"><input v-model="site.like" type="checkbox">允许自动点赞</label><label class="check"><input v-model="site.favorite" type="checkbox">允许自动收藏</label>
          <button type="button" @click="draft.sites.splice(index,1)">移除此网站授权</button>
        </div>
        <div class="computer-controls"><input v-model="domain" aria-label="授权网站域名" placeholder="例如 www.example.com"><button type="button" @click="addSite">添加网站</button></div>
        <div class="computer-controls"><button class="button primary" :disabled="busy || !dirty">保存上网设置</button><button type="button" @click="resetDraft">重新载入设置</button><small v-if="dirty">尚未保存</small></div>
        <h3>数据与隐私</h3><p>登录资料保存在独立浏览器目录，受宿主文件权限保护，不是加密保险箱。电脑设置、账号、阅读数据不包含在 v2 家庭存档中。读后记录可单独删除。</p>
        <label class="check"><input v-model="clearConfirm" type="checkbox">确认退出所有账号并清除专属浏览器数据</label>
        <button type="button" :disabled="busy || !clearConfirm" @click="command('clear-browser',{confirm:true}).then(ok=>{ if(ok){clearConfirm=false;resetDraft()} })">清除浏览器数据</button>
      </form>
      <div v-else-if="tab === 'reading'" class="computer-reading">
        <h3>阅读日记</h3><p v-if="!history.length">还没有阅读记录。</p>
        <article v-for="entry in history" :key="entry.id"><h4>{{ entry.topic }}</h4><small>{{ labels[entry.status] }}</small><p>{{ entry.summary || entry.notice }}</p><p v-if="entry.interest">新兴趣：{{ entry.interest }}</p><ul><li v-for="source in entry.sources" :key="source.url"><a :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title || source.url }}</a><small>{{ source.private ? '登录后内容' : '公开来源' }} · {{ source.at }}</small></li></ul><button :disabled="busy || !entry.summary" @click="command('remember',{id:entry.id}).then(readings)">记住结论（含私有内容时由你确认）</button><button :disabled="busy" @click="command('delete-record',{kind:'history',id:entry.id}).then(readings)">删除记录</button></article>
        <h3>可追溯阅读记忆</h3><p>外部网页主张不是你的个人偏好；自动记忆每轮最多 3 条。删除日记不会连带删除记忆。</p><article v-for="memory in memories" :key="memory.id"><p>{{ memory.text }}</p><ul><li v-for="source in memory.sources" :key="source.url"><a :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }}</a></li></ul><button :disabled="busy" @click="command('delete-record',{kind:'memory',id:memory.id}).then(readings)">删除记忆</button></article>
      </div>
  </template>
</div>
</template>
<style scoped>
.computer-panel{color:#d8e1f1;font-size:13px;line-height:1.65;padding:20px;overflow:auto;min-height:0}
.computer-tabs,.computer-controls,.browser-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
button{border:1px solid #b5c9f433;background:#99baff10;color:inherit;border-radius:7px;padding:7px 11px;cursor:pointer;font:inherit}button:hover,button[aria-pressed=true]{background:#729ade35}button:disabled{opacity:.4;cursor:default}
input,textarea,select{width:100%;box-sizing:border-box;font:inherit;color:inherit;background:#0a1224;border:1px solid #a9bded40;border-radius:7px;padding:9px}select{color-scheme:dark}textarea{resize:vertical}
.computer-subtle,small{color:#99abc8;font-size:11px}.computer-warning{background:#bd88411a;border:1px solid #b5945755;padding:14px;border-radius:9px;color:#f0d5ad;overflow-wrap:anywhere}.computer-warning pre{white-space:pre-wrap}
.computer-status{display:grid;gap:3px;background:#839ccb14;padding:12px;border-radius:9px;margin:12px 0}.browser-frame{border:1px solid #7793c544;border-radius:10px;background:#080e1b;overflow:hidden;margin:15px 0}.browser-frame img{display:block;width:100%;height:auto}.browser-frame img.interactive{cursor:crosshair}.browser-title{padding:8px 12px;display:grid;overflow-wrap:anywhere}.browser-tabs{padding:0 8px}.browser-tabs button{font-size:10px;max-width:100%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.browser-frame>small{display:block;padding:8px}.browser-empty{text-align:center;padding:65px 12px;color:#9fb5d9}.browser-empty strong{font-size:23px;font-weight:400}
.computer-manual{border:1px solid #95bbed44;border-radius:9px;padding:12px}.computer-manual form{display:flex;gap:6px;margin:8px 0}.computer-manual input{min-width:0}.computer-task-form{display:grid;gap:8px}.computer-task-form button{justify-self:end}.computer-settings{display:grid;gap:13px}.computer-settings h3{margin:16px 0 0}.computer-settings label{display:grid;gap:5px}.computer-settings .check{display:flex;align-items:center;gap:9px}.check input{width:16px}.computer-budget{display:grid;grid-template-columns:1fr 1fr;gap:12px}.computer-site,.computer-reading article{border:1px solid #8ca3cb2b;padding:14px;border-radius:9px;margin:10px 0}.computer-site label{margin-top:8px}.computer-summary,.computer-reading p{white-space:pre-wrap;overflow-wrap:anywhere}.computer-reading a{color:#b8d4ff;overflow-wrap:anywhere}.computer-reading small{display:block}.computer-reading button{margin:5px}code{overflow-wrap:anywhere}
@media(max-width:600px){.computer-panel{padding:12px}.computer-budget{grid-template-columns:1fr 1fr}.computer-controls{gap:5px}}
.computer-workspace{display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:16px;align-items:start}.computer-workspace.task-collapsed{grid-template-columns:1fr}.computer-browser{min-width:0}.computer-task-sidebar{background:#102039;border-radius:12px;padding:14px;overflow-wrap:anywhere}.browser-address{display:flex;flex-wrap:wrap;gap:6px}.browser-address input{flex:1;min-width:130px}.computer-environment{background:#17263c;border-radius:10px;padding:12px;margin-bottom:12px}.computer-environment pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer;padding:8px 0}details{border-top:1px solid #9bb6d52a;padding-top:5px}.computer-settings{max-width:720px;margin:auto}.computer-settings .computer-controls input{flex:1;min-width:100px}.browser-tabs span{display:flex;min-width:0;max-width:100%}.browser-frame{margin:8px 0}.computer-subtle{margin:4px 0 10px}.computer-task-sidebar a{color:#b8d4ff}
@media(max-width:800px){.computer-workspace{grid-template-columns:1fr}.computer-task-sidebar{grid-row:1}.browser-empty{padding:35px 12px}.browser-address button{padding:6px}.computer-budget{grid-template-columns:1fr}.computer-panel{padding:12px}}
</style>
