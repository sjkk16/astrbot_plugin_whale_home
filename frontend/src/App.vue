<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  ArrowLeft, ArrowUpFromLine, BookHeart, BookOpen, Check, ChevronRight, Coffee,
  Download, Gift, Heart, House, ImagePlus, LoaderCircle, MapPin, MessageCircle,
  Moon, Package, Pencil, Plus, RefreshCw, Save, Search, Send, Settings2,
  Smile, Sparkles, Trash2, Utensils, X, Zap,
} from '@lucide/vue'
import CharacterRenderer from './components/CharacterRenderer.vue'
import CharacterMotionSettings from './components/CharacterMotionSettings.vue'
import { modeLabels } from './character-motion'
import type { RendererStatus } from './character-motion'
import RoomScene from './components/RoomScene.vue'
import InteractionTray from './components/InteractionTray.vue'
import CompanionSettings from './components/CompanionSettings.vue'
import SkillsSettings from './components/SkillsSettings.vue'
import ComputerPanel from './components/ComputerPanel.vue'
import { artworkProgress, missingPoseLabel, portraitSource } from './character-art'
import { useCharacterSprite } from './use-character-sprite'
import { usePresence } from './use-presence'
import ItemArt from './components/ItemArt.vue'
import { activityNames, usageNames } from './icons'
import type { Bridge, CompanionPreferences, DirectInteraction, Definition, HomeEvent, Instance, Memory, Message, Panel, Provider, SceneSpot, Settings, Snapshot, SpotId } from './types'

const roomRendererStatus = ref<RendererStatus>()
const chatRendererStatus = ref<RendererStatus>()
const snapshot = ref<Snapshot>()
const providers = ref<Provider[]>([])
const panel = ref<Panel>(null)
const interactionOpen = ref(false)
const serverNow = ref(Date.now())
let serverEpoch = Date.now()
let clientTick = performance.now()
let presentationTimer: ReturnType<typeof setInterval>
const selectedSpotId = ref<SpotId | null>(null)
const panelElement = ref<HTMLElement>()
const itemScroll = ref<HTMLElement>()
let returnFocus: HTMLElement | null = null
const selectedId = ref<string | null>(null)
const pending = ref(false)
const skillStopping = ref(false)
const connected = ref(false)
const demo = ref(false)
const fatalError = ref('')
const toast = ref<{ text: string; error: boolean } | null>(null)
const assetUrls = reactive<Record<string, string>>({})
const message = ref('')
const search = ref('')
const itemTab = ref('inventory')
const diaryTab = ref('events')
const category = ref('all')
const settingsDraft = ref<Settings>()
const settingsBaseline = ref('')
const settingsGroup = ref('life')
const computerDirty = ref(false)
const companionDirty = ref(false)
const skillsDirty = ref(false)
const settingsGroups = [{id:'character',name:'角色与显示'},{id:'life',name:'聊天与自主生活'},{id:'computer',name:'电脑上网'},{id:'skills',name:'Skills 权限'},{id:'data',name:'数据与关于'}]
const draftItem = ref<Definition | null>(null)
const memoryText = ref('')
const olderMessages = ref<Message[]>([])
const olderEvents = ref<HomeEvent[]>([])
const olderMemories = ref<Memory[]>([])
const chatScroll = ref<HTMLElement>()
const confirmation = ref<{ title: string; text: string; action: () => Promise<void> } | null>(null)
const confirmDialog = ref<HTMLDialogElement>()
const fileInput = ref<HTMLInputElement>()
const customImageInput = ref<HTMLInputElement>()
const portraitInput = ref<HTMLInputElement>()
const imageSlot = ref<'portrait_asset' | 'chibi_asset'>('portrait_asset')
let bridge: Bridge
let subscription: string | undefined
let polling: ReturnType<typeof setInterval>
let reconnectTimer: ReturnType<typeof setTimeout>
let refreshTimer: ReturnType<typeof setTimeout>
let toastTimer: ReturnType<typeof setTimeout>
let refreshPromise: Promise<void> | null = null
let refreshAgain = false
let disposed = false
const home = computed(() => snapshot.value!.home)
const selected = computed(() => home.value?.instances.find(item => item.id === selectedId.value))
const selectedDefinition = computed(() => home.value?.definitions.find(item => item.id === selected.value?.definition_id))
const selectedSpot = computed(() => snapshot.value?.scene.spots.find(spot => spot.id === selectedSpotId.value))
const panelTitle = computed(() => ({chat:'和她聊聊', items:'随手的小心意', diary:'一起留下的日常', settings:'小家设置', activities:'房间里的日常',computer:'她的电脑',more:'更多功能'}[panel.value || 'chat']))
const isDefinitionTab = computed(() => itemTab.value === 'catalog' || itemTab.value === 'custom')
const visibleInstances = computed(() => home.value?.instances.filter(item =>
  home.value.definitions.find(definition => definition.id === item.definition_id)?.name.includes(search.value.trim())) || [])
const filteredDefinitions = computed(() => home.value?.definitions.filter(item =>
  (category.value === 'all' || item.category === category.value) &&
  (itemTab.value !== 'custom' || !item.builtin) &&
  item.name.includes(search.value.trim())) || [])
const settingsChanged = computed(() => settingsDraft.value &&
  JSON.stringify(settingsDraft.value) !== settingsBaseline.value)
const chatMessages = computed(() => mergeById(olderMessages.value, snapshot.value?.messages || []))
const diaryEvents = computed(() => mergeById(olderEvents.value, snapshot.value?.events || []).reverse())
const memories = computed(() => mergeById(olderMemories.value, snapshot.value?.memories || []).reverse())
const portraitTarget = computed(() => home.value ? portraitSource(home.value, snapshot.value?.companion, serverNow.value, assetUrls) : './art/portrait.webp')
const portraitImage = useCharacterSprite(() => portraitTarget.value, () => './art/portrait.webp')
const portrait = computed(() => portraitImage.value.src)
const missingArtwork = computed(() => home.value ? missingPoseLabel(home.value, snapshot.value?.companion, serverNow.value) : '')
const demoTopics = [
  { label: '夸夸她', prompt: '你今天真可爱' }, { label: '一起想想', prompt: '陪我想想周末做什么' },
  { label: '有点难过', prompt: '今天有点难过' }, { label: '困困了', prompt: '我有点困了' },
]
async function tryDemoTopic(text: string) {
  message.value = text
  await nextTick()
  panelElement.value?.querySelector('textarea')?.focus()
}
const chatBlocked = computed(() => pending.value || Boolean(snapshot.value?.runtime.busy && !snapshot.value?.companion?.reply_interruptible))
const currentDate = computed(() => snapshot.value ? new Intl.DateTimeFormat('zh-CN', {
  month: 'long', day: 'numeric', weekday: 'short', timeZone: home.value.settings.timezone,
}).format(new Date(snapshot.value.runtime.server_time)) : '')
const currentTime = computed(() => snapshot.value ? time(snapshot.value.runtime.server_time) : '')
const status = computed(() => snapshot.value?.runtime.busy ? '正在想事情'
  : home.value?.settings.character_style === 'portrait' && snapshot.value?.companion?.preferences.proactive_enabled
    ? snapshot.value.companion.awaiting_reply ? '等你有空再聊 · 不催促' : '安静陪着你 · 偶尔搭话'
  : home.value?.settings.autonomous_enabled
    ? snapshot.value!.usage.autonomy >= home.value.settings.daily_limit ? '今日自主次数已用完' : '自在生活中'
    : '自主生活已暂停')
const bondName = computed(() => !home.value ? '' : home.value.character.bond < 25 ? '慢慢熟悉'
  : home.value.character.bond < 60 ? '默契伙伴' : '珍贵的陪伴')

function mergeById<T extends { id: number }>(older: T[], recent: T[]): T[] {
  return [...new Map([...older, ...recent].map(item => [item.id, item])).values()].sort((a, b) => a.id - b.id)
}
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}
function time(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit',
    timeZone: home.value?.settings.timezone || 'Asia/Shanghai' }).format(new Date(value))
}
function notice(text: string, error = false) {
  toast.value = { text, error }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, error ? 7000 : 2800)
}
function id() {
  if (crypto.randomUUID) return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = bytes[6] & 15 | 64
  bytes[8] = bytes[8] & 63 | 128
  const text = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
  return `${text.slice(0, 8)}-${text.slice(8, 12)}-${text.slice(12, 16)}-${text.slice(16, 20)}-${text.slice(20)}`
}
async function loadImages(state: Snapshot) {
  const ids = new Set([state.home.settings.chibi_asset, state.home.settings.portrait_asset,
    ...state.home.definitions.map(item => item.asset_id)])
  for (const assetId of ids) {
    if (!assetId || assetUrls[assetId]) continue
    try {
      const result = await bridge.apiGet<{ data_url: string }>(`assets/${assetId}`)
      assetUrls[assetId] = result.data_url
    } catch { /* A missing user image keeps the built-in fallback usable. */ }
  }
}
function update(state: Snapshot) {
  if (snapshot.value && state.home.version < snapshot.value.home.version) return
  snapshot.value = state
  void loadImages(state)
}
async function refresh() {
  if (refreshPromise) { refreshAgain = true; return refreshPromise }
  refreshPromise = (async () => {
    try { update(await bridge.apiGet<Snapshot>('state')) }
    catch (error) { connected.value = false; if (!snapshot.value) throw error }
    finally { refreshPromise = null; if (refreshAgain && !disposed) { refreshAgain = false; void refresh() } }
  })()
  return refreshPromise
}
async function perform(endpoint: string, data: object = {}, success = '') {
  if (pending.value) return false
  pending.value = true
  try {
    const state = await bridge.apiPost<Snapshot>(endpoint, {
      // The real iframe bridge uses postMessage; nested Vue proxies are not cloneable.
      request_id: id(), expected_version: home.value.version, ...clone(data),
    })
    update(state)
    if (success) notice(success)
    return true
  } catch (error) {
    notice(error instanceof Error ? error.message : '这次操作没有完成。', true)
    await refresh()
    return false
  } finally { pending.value = false }
}
function protectDrafts(event: BeforeUnloadEvent) {
  if (computerDirty.value || (panel.value === 'settings' && (settingsChanged.value || companionDirty.value || skillsDirty.value))) { event.preventDefault(); event.returnValue='' }
}
onMounted(()=>window.addEventListener('beforeunload',protectDrafts))
onBeforeUnmount(()=>window.removeEventListener('beforeunload',protectDrafts))
function mayLeave() {
  const dirty = computerDirty.value || (panel.value === 'settings' && (settingsChanged.value || companionDirty.value || skillsDirty.value))
  return !dirty || window.confirm('还有未保存的设置，确定放弃修改并离开？')
}
function selectSettingsGroup(next: string) {
  if (settingsGroup.value === 'computer' && computerDirty.value && !window.confirm('上网设置尚未保存，确定放弃修改？')) return
  settingsGroup.value = next
}
function openPanel(next: Panel) {
  if (!mayLeave()) return
  computerDirty.value = companionDirty.value = skillsDirty.value = false
  interactionOpen.value = false
  if (next === 'settings') {
    settingsGroup.value = 'life'
    settingsDraft.value = clone(home.value.settings); settingsBaseline.value = JSON.stringify(home.value.settings)
    void bridge.apiGet<Provider[]>('providers').then(list => { providers.value = list }).catch(() => {})
  }
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  draftItem.value = null
  selectedSpotId.value = null
  panel.value = panel.value === next ? null : next
}
async function stopSkills() {
  if (skillStopping.value) return
  skillStopping.value = true
  try {
    const latest = await bridge.apiGet<Snapshot>('state')
    update(await bridge.apiPost<Snapshot>('skills/stop', { request_id: id(), expected_version: latest.home.version }))
    notice('已请求停止；已开始的外部操作不保证撤销')
  } catch (e) { notice(e instanceof Error ? e.message : '停止请求失败，请重试', true); await refresh() }
  finally { skillStopping.value = false }
}
async function sendMessage() {
  const text = message.value.trim()
  if (!text || chatBlocked.value) return
  message.value = ''
  const result = await perform('chat', { message: text })
  if (!result) message.value = text
  await nextTick()
  chatScroll.value?.scrollTo({ top: chatScroll.value.scrollHeight, behavior: 'smooth' })
}
function chatKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void sendMessage()
  }
}
async function addItem(definition: Definition) {
  const before = new Set(home.value.instances.map(item => item.id))
  if (await perform('items/add', { definition_id: definition.id, quantity: definition.consumable ? 5 : 1 }, '已经放进收纳了')) {
    selectedId.value = home.value.instances.find(item => !before.has(item.id))?.id || null
    itemTab.value = 'inventory'
    await nextTick()
    itemScroll.value?.scrollTo({ top: 0 })
  }
}
async function selectInventory(instance: Instance) {
  selectedId.value = instance.id
  await nextTick()
  itemScroll.value?.scrollTo({ top: 0 })
}
function removeSelected() {
  const instanceId = selected.value?.id
  if (!instanceId) return
  ask('移除这件物品？', '仅移除这件收纳物品，历史记录不变。', async () => {
    if (await perform('items/remove', { instance_id: instanceId })) selectedId.value = null
  })
}
async function interact(mode: string) {
  if (!selected.value) return
  if (home.value.settings.character_style === 'portrait' && snapshot.value?.companion) {
    if (await directInteract({ kind: 'item', instance_id: selected.value.id, mode: mode === 'gift' ? 'gift' : 'use' })) notice('这份日常，记下啦')
  } else await perform('interact', { instance_id: selected.value.id, mode }, '这份日常，记下啦')
}
function chooseSpot(spotId: SpotId) {
  if (!mayLeave()) return
  interactionOpen.value = false
  panel.value = null
  selectedSpotId.value = spotId
}
async function useSpot(spot: SceneSpot) {
  const result = home.value.settings.character_style === 'portrait' && snapshot.value?.companion
    ? await directInteract({ kind: 'scene', spot_id: spot.id })
    : await perform('scene/interact', { spot_id: spot.id, action: spot.action })
  if (result) {
    selectedSpotId.value = null
  }
}
function closePanel() {
  if (!mayLeave()) return
  computerDirty.value = companionDirty.value = skillsDirty.value = false
  interactionOpen.value = false
  panel.value = null
  draftItem.value = null
  returnFocus?.focus()
}
function escapeKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && interactionOpen.value) { closeInteraction(); return }
  if (event.key !== 'Escape' || confirmation.value) return
  if (draftItem.value) draftItem.value = null
  else { closePanel(); selectedSpotId.value = null }
}
watch(panel, async value => { if (value) { await nextTick(); panelElement.value?.focus() } })
function newItem() {
  draftItem.value = { id: id().replaceAll('-', ''), name: '', description: '', category: 'toy', usage: 'play',
    width: 1, height: 1, blocks_movement: true, consumable: false, builtin: false, icon: 'package', asset_id: null }
}
async function saveItem() {
  if (!draftItem.value || !draftItem.value.name.trim()) return
  const item = clone(draftItem.value)
  item.consumable = item.usage === 'eat' || item.usage === 'drink'
  if (await perform('items/edit', { definition: item }, '物品已保存')) {
    draftItem.value = null
    itemTab.value = 'custom'
  }
}
async function uploadImage(event: Event, target: 'item' | 'character') {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  input.value = ''
  if (pending.value) return
  const itemTarget = draftItem.value
  const settingsTarget = settingsDraft.value
  const slot = imageSlot.value
  if (file.size > 5 * 1024 * 1024) { notice('图片需小于 5 MB。', true); return }
  pending.value = true
  try {
    const result = await bridge.upload<{ asset_id: string }>('assets/upload', file)
    const image = await bridge.apiGet<{ data_url: string }>(`assets/${result.asset_id}`)
    assetUrls[result.asset_id] = image.data_url
    if (target === 'item' && itemTarget && draftItem.value === itemTarget) itemTarget.asset_id = result.asset_id
    if (target === 'character' && settingsTarget && settingsDraft.value === settingsTarget) settingsTarget[slot] = result.asset_id
  } catch (error) { notice((error as Error).message, true) }
  finally { pending.value = false }
}
function ask(title: string, text: string, action: () => Promise<void>) {
  confirmation.value = { title, text, action }
}
async function confirm() {
  const action = confirmation.value?.action
  confirmDialog.value?.close()
  confirmation.value = null
  await action?.()
}
watch(confirmation, async value => { if (value) { await nextTick(); confirmDialog.value?.showModal() } })
async function saveSettings() {
  if (!settingsDraft.value) return
  if (JSON.stringify(home.value.settings) !== settingsBaseline.value) { notice('设置已在其他页面修改，请重新打开设置后编辑。', true); return }
  if (await perform('settings', { settings: settingsDraft.value }, '设置已保存')) {
    settingsDraft.value = clone(home.value.settings); settingsBaseline.value = JSON.stringify(home.value.settings)
  }
}
function openCharacter() {
  if (!mayLeave()) return
  if (home.value.settings.character_style === 'chibi' || !snapshot.value?.companion) { openPanel('chat'); return }
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  panel.value = null
  selectedSpotId.value = null
  interactionOpen.value = !interactionOpen.value
}
function closeInteraction() {
  interactionOpen.value = false
  returnFocus?.focus()
}
async function directInteract(value: DirectInteraction) {
  const result = await perform('character/interact', value)
  if (result) { closeInteraction(); selectedSpotId.value = null }
  return result
}
async function saveCompanion(preferences: CompanionPreferences) {
  return perform('companion/preferences', { preferences }, '陪伴偏好已保存')
}
function choosePlayfulPersona() {
  ask('使用俏皮人设预设？', '只替换此处的角色设定草稿，点击「保存设置」才生效。不会重置图片、称呼、聊天或记忆。', async () => {
    if (settingsDraft.value && snapshot.value?.companion) settingsDraft.value.persona = snapshot.value.companion.persona_preset
  })
}
async function addMemory() {
  if (!memoryText.value.trim()) return
  if (await perform('memories/add', { text: memoryText.value.trim() }, '记住啦')) memoryText.value = ''
}
async function exportArchive() {
  try { await bridge.download('archives/export', {}, 'whale-home-v2.json') }
  catch (error) { notice((error as Error).message, true) }
}
async function importArchive(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 25 * 1024 * 1024) { notice('存档不能超过 25 MB。', true); return }
  ask('恢复这份存档？', '当前小家将先自动备份，再由这份存档替换。恢复后，自主生活会暂停。', async () => {
    pending.value = true
    try {
      update(await bridge.upload<Snapshot>('archives/import', file))
      olderMessages.value = []; olderEvents.value = []; olderMemories.value = []
      settingsDraft.value = clone(home.value.settings); settingsBaseline.value = JSON.stringify(home.value.settings)
      notice('存档已恢复')
    } catch (error) { notice((error as Error).message, true) }
    finally { pending.value = false }
  })
}
async function loadMore(type: 'messages' | 'events' | 'memories') {
  const items = type === 'messages' ? chatMessages.value : type === 'events' ? diaryEvents.value : memories.value
  if (!items.length) return
  try {
    const result = await bridge.apiGet<{ items: Message[] & HomeEvent[] & Memory[] }>(
      type === 'events' ? 'events/history' : type, { before: Math.min(...items.map(item => item.id)), limit: 60 })
    if (!result.items.length) notice('已经到最初的记录了')
    if (type === 'messages') olderMessages.value = mergeById<Message>(olderMessages.value, result.items)
    if (type === 'events') olderEvents.value = mergeById<HomeEvent>(olderEvents.value, result.items)
    if (type === 'memories') olderMemories.value = mergeById<Memory>(olderMemories.value, result.items)
  } catch (error) { notice((error as Error).message, true) }
}
async function connectStream() {
  if (disposed) return
  if (subscription) await bridge.unsubscribeSSE(subscription).catch(() => {})
  subscription = await bridge.subscribeSSE('events', {
    onOpen: () => { connected.value = true },
    onMessage: event => {
      if (event.parsed.type === 'computer_changed') { window.dispatchEvent(new Event('whale-computer-changed')); return }
      if (event.parsed.type === 'changed' || event.parsed.type === 'ready') {
        clearTimeout(refreshTimer)
        refreshTimer = setTimeout(() => void refresh(), 50)
      }
      if (event.parsed.type === 'closed') {
        connected.value = false
        clearTimeout(reconnectTimer)
        reconnectTimer = setTimeout(() => void connectStream(), 1500)
      }
    },
    onError: () => {
      connected.value = false
      clearTimeout(reconnectTimer)
      reconnectTimer = setTimeout(() => void connectStream(), 5000)
    },
  }).catch(() => {
    reconnectTimer = setTimeout(() => void connectStream(), 5000)
    return undefined
  })
}
const presence = usePresence(() => bridge, () => Boolean(snapshot.value?.companion && home.value?.settings.character_style === 'portrait'), id())
watch(() => snapshot.value?.runtime.server_time, value => {
  if (!value) return
  serverEpoch = Date.parse(value)
  clientTick = performance.now()
  serverNow.value = serverEpoch
})
watch(() => snapshot.value?.home.settings.character_style, () => { interactionOpen.value = false })
watch(() => snapshot.value?.messages.length, async () => {
  await nextTick()
  chatScroll.value?.scrollTo({ top: chatScroll.value.scrollHeight, behavior: 'smooth' })
})
onMounted(async () => {
  document.addEventListener('keydown', escapeKey)
  try {
    if (!window.AstrBotPluginView) throw new Error('请从 AstrBot 的插件页面打开小家。')
    bridge = window.AstrBotPluginView
    const context = await bridge.ready()
    demo.value = Boolean(context.demo)
    await refresh()
    providers.value = await bridge.apiGet<Provider[]>('providers')
    connected.value = true
    void connectStream()
    polling = setInterval(() => void refresh(), 30000)
    presentationTimer = setInterval(() => { serverNow.value = serverEpoch + performance.now() - clientTick }, 250)
    if (snapshot.value?.companion) presence.start()
  } catch (error) { fatalError.value = (error as Error).message }
})
onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('keydown', escapeKey)
  clearInterval(polling); clearInterval(presentationTimer)
  clearTimeout(reconnectTimer); clearTimeout(refreshTimer); clearTimeout(toastTimer)
  if (subscription) void bridge.unsubscribeSSE(subscription)
})
</script>

<template>
  <div v-if="!snapshot" class="loading-page">
    <Moon :size="38" /><h1>鲸鱼娘的小家</h1>
    <p v-if="fatalError" role="alert">{{ fatalError }}</p><p v-else>为你留着一盏灯。</p>
    <LoaderCircle v-if="!fatalError" class="spin" :size="20" />
  </div>
  <div v-else class="home-app">
    <header class="app-header">
      <button class="brand" aria-label="回到小屋" @click="closePanel(); selectedSpotId = null">
        <span class="brand-mark"><Moon :size="24" /></span>
        <span><h1>鲸鱼娘的小家</h1><span class="brand-sub">WHALE HOME <i> / </i> AFTER HOURS</span></span>
      </button>
      <div class="header-date"><span>{{ currentDate }}</span><b>{{ currentTime }}</b></div>
      <div class="header-end"><span v-if="demo" class="demo-label">本地演示</span>
        <span class="connection" :class="{ offline: !connected }"><i></i><span>{{ connected ? '已同步' : '重连中' }}</span></span>
        <span class="preview-label">公开版</span><button v-if="snapshot.skills?.active" type="button" class="text-button skills-stop-global" :disabled="skillStopping || snapshot.skills.active.stopping" @click="stopSkills">停止本轮技能</button>
      </div>
    </header>

    <main class="room-stage">
      <div class="scene-container">
        <div class="scene-eyebrow"><span><span class="small-star">✧</span> 夜晚的小家</span><span class="scene-guide">{{ home.settings.character_style === 'portrait' ? '点角色互动 · 点微光去散步' : '点击微光，走近她的日常' }}</span></div>
        <RoomScene @renderer="roomRendererStatus = $event" :home="home" :scene="snapshot.scene" :images="assetUrls" :selected-id="selectedSpotId" :companion="snapshot.companion" :now="serverNow" :demo="demo" :show-bubbles="!panel && !interactionOpen"
          @select="chooseSpot" @character="openCharacter" @chat="openPanel('chat')" />
        <div class="scene-underbar">
          <button v-if="home.settings.character_style === 'portrait' && snapshot.companion" class="interaction-launch" @click="openCharacter"><Heart :size="14" />直接互动</button>
          <div class="room-status" aria-live="polite"><span class="status-dot" :class="{ paused: !home.settings.autonomous_enabled }"></span><span>{{ status }}</span><span class="status-divider">·</span><span>{{ activityNames[home.character.activity] || '在小家里' }}</span></div>
          <button class="text-button activity-button" @click="openPanel('activities')"><MapPin :size="14" />活动列表<ChevronRight :size="14" /></button>
        </div>
        <button class="moment" @click="openPanel('chat')"><span class="quote-mark">“</span><span><span class="moment-name">{{ home.settings.character_name }}的此刻</span><span class="moment-speech">{{ home.character.speech || '不用急着说什么，陪她待一会儿也很好。' }}</span></span><MessageCircle :size="20" /></button>
        <div class="mobile-activities" aria-label="快捷活动"><span>今晚，想一起做点什么？</span><div><button v-for="spot in snapshot.scene.spots" :key="spot.id" @click="chooseSpot(spot.id)"><component :is="spot.id === 'bookshelf' ? BookOpen : spot.id === 'desk' ? Sparkles : spot.id === 'window' ? Moon : Coffee" :size="17" /><span>{{ spot.label }}</span><ChevronRight :size="13" /></button></div></div>
      </div>
    </main>

    <footer class="home-footer">
      <div class="needs-strip" aria-label="角色状态">
        <div class="need" v-for="need in [{key:'satiety', name:'饱腹', icon:Utensils, color:'#d3aa87'}, {key:'energy', name:'精力', icon:Zap, color:'#bbbd8b'}, {key:'mood', name:'心情', icon:Smile, color:'#a6b9da'}]" :key="need.key" :style="{ '--need-color': need.color }">
          <component :is="need.icon" :size="15" /><span>{{ need.name }}</span><b>{{ Math.round(home.character[need.key as 'satiety' | 'energy' | 'mood']) }}</b>
          <span class="need-track" role="meter" :aria-label="need.name" :aria-valuenow="Math.round(home.character[need.key as 'satiety' | 'energy' | 'mood'])" aria-valuemin="0" aria-valuemax="100"><i :style="{width: `${home.character[need.key as 'satiety' | 'energy' | 'mood']}%`}"></i></span>
        </div>
      </div>
      <nav class="bottom-nav" aria-label="小家导航">
        <button :class="{ active: panel === null }" aria-label="小屋" @click="closePanel(); selectedSpotId = null"><House :size="21" /><span>小屋</span></button>
        <button :class="{ active: panel === 'chat' }" aria-label="聊天" @click="openPanel('chat')"><MessageCircle :size="21" /><span>聊天</span></button>
        
        <button :class="{ active: panel === 'computer' }" aria-label="电脑" @click="openPanel('computer')"><Search :size="21" /><span>电脑</span></button>
        <button :class="{ active: panel === 'diary' }" aria-label="日记" @click="openPanel('diary')"><BookHeart :size="21" /><span>日记</span></button>
        <button :class="{ active: ['more','items','settings'].includes(panel || '') }" aria-label="更多" @click="openPanel('more')"><Settings2 :size="21" /><span>更多</span></button>
      </nav>
      <span class="footer-note"><Heart :size="13" />{{ bondName }}<small>v0.4.2 · PUBLIC RELEASE</small></span>
    </footer>

    <Transition name="panel">
      <InteractionTray v-if="interactionOpen && home.settings.character_style === 'portrait'" :home="home" :scene="snapshot.scene" :pending="pending" :pet-blocked="Boolean(snapshot.companion?.touch_available_at && serverNow < Date.parse(snapshot.companion.touch_available_at))"
        @interact="directInteract" @close="closeInteraction" @chat="openPanel('chat')" @items="openPanel('items')" />
    </Transition>

    <Transition name="panel">
      <section v-if="selectedSpot && !panel" class="spot-card" aria-label="场景活动确认">
        <div class="spot-card-heading"><span class="eyebrow">A MOMENT HERE</span><button class="icon-button" aria-label="取消场景选择" @click="selectedSpotId = null"><X :size="18" /></button></div>
        <h2>{{ selectedSpot.name }}</h2><p>{{ selectedSpot.description }}</p>
        <button v-if="selectedSpot.id === 'desk'" class="button outline" @click="openPanel('computer')">打开电脑</button>
        <button class="button primary" :disabled="pending" @click="useSpot(selectedSpot)"><Sparkles :size="16" />{{ selectedSpot.label }}</button>
      </section>
    </Transition>

    <Transition name="panel">
      <aside v-if="panel" ref="panelElement" class="side-panel" :class="{ 'computer-wide': panel === 'computer' || (panel === 'settings' && settingsGroup === 'computer') }" tabindex="-1" :aria-label="panelTitle">
        <header class="panel-header"><div><span class="eyebrow">OUR LITTLE WORLD</span><h2>{{ panelTitle }}</h2></div><button class="icon-button" aria-label="关闭面板" @click="closePanel"><X :size="21" /></button></header>

        <ComputerPanel v-if="panel === 'computer'" :bridge="bridge" :providers="providers" @dirty="computerDirty=$event" />
        <div v-else-if="panel === 'more'" class="panel-scroll more-menu"><button class="button outline" aria-label="物品" @click="openPanel('items')"><Package :size="20" />物品与收纳</button><button class="button outline" aria-label="小家设置" @click="openPanel('settings')"><Settings2 :size="20" />小家设置</button><p class="helper">房间里的书架、书桌和床边仍可直接互动。</p></div>
        <template v-else-if="panel === 'activities'">
          <div class="panel-scroll"><p class="helper">家具留在画里，日常发生在这里。选择一个位置，再决定要做什么。</p>
            <button v-for="spot in snapshot.scene.spots" :key="spot.id" class="activity-row" @click="chooseSpot(spot.id)"><span class="activity-icon"><MapPin :size="20" /></span><span><strong>{{ spot.name }}</strong><small>{{ spot.label }}</small></span><ChevronRight :size="18" /></button>
            <p class="subtle-note">手动活动不调用模型。角色当前使用站立形象，未包含坐卧动作。</p>
          </div>
        </template>

        <template v-else-if="panel === 'chat'">
          <div class="portrait-stage"><span class="portrait-moon" aria-hidden="true"></span><div><span class="eyebrow">SOMEONE IS HERE</span><h3>{{ home.settings.character_name }}</h3><p>今晚的时间，可以慢一点。</p><small v-if="missingArtwork" class="artwork-fallback" data-testid="portrait-artwork-fallback">{{ missingArtwork }}</small></div><CharacterRenderer @status="chatRendererStatus = $event" :source="portrait" style-id="portrait" :alt="`${home.settings.character_name}的立绘`" :custom="Boolean(home.settings.portrait_asset)" :event-id="snapshot.companion?.presentation?.id || 'idle'" /></div>
          <p v-if="chatRendererStatus" class="helper" data-testid="chat-renderer-status">当前立绘：{{ modeLabels[chatRendererStatus.mode] }}<span v-if="chatRendererStatus.reason"> · {{ chatRendererStatus.reason }}</span></p>
          <div ref="chatScroll" class="chat-messages">
            <button v-if="chatMessages.length" class="text-button load-more" @click="loadMore('messages')">更早的聊天</button>
            <div v-if="!chatMessages.length" class="message assistant"><span>{{ home.settings.character_name }}</span><p>{{ home.character.speech }}</p></div>
            <div v-for="entry in chatMessages" :key="entry.id" class="message" :class="entry.role"><span>{{ entry.role === 'user' ? home.settings.user_name : home.settings.character_name }}<time>{{ time(entry.created_at) }}</time></span><p>{{ entry.text }}</p></div>
            <div v-if="snapshot.runtime.busy" class="thinking"><LoaderCircle class="spin" :size="14" />她在想怎么回应你…</div>
          </div>
          <div class="chat-composer">
            <div v-if="demo && !message.trim()" class="demo-topics" aria-label="离线演示话题"><span>试着聊聊</span><button v-for="topic in demoTopics" :key="topic.label" type="button" @click="tryDemoTopic(topic.prompt)">{{ topic.label }}</button></div>
            <p v-if="snapshot.companion?.reply_interruptible" class="helper interrupt-hint">想说就说：发送消息会打断她正在准备的接话。</p>
            <button v-if="!home.settings.provider_id" class="model-notice" @click="openPanel('settings')">还没有选择聊天模型<span>去设置 <ChevronRight :size="13" /></span></button>
            <form @submit.prevent="sendMessage"><textarea v-model="message" aria-label="聊天消息" placeholder="今晚，想和她说些什么？" maxlength="3000" rows="2" @keydown="chatKey"></textarea><div><span>{{ demo ? '本地演示 · 不调用在线模型' : 'Enter 发送 · Shift + Enter 换行' }}</span><button class="send-button" aria-label="发送" :disabled="chatBlocked || !message.trim()"><Send :size="17" /></button></div></form>
          </div>
        </template>

        <template v-else-if="panel === 'items'">
          <div v-if="draftItem" class="panel-scroll">
            <button class="text-button" @click="draftItem = null"><ArrowLeft :size="16" />返回物品</button>
            <form class="item-editor" @submit.prevent="saveItem">
              <h3>{{ home.definitions.some(item => item.id === draftItem!.id) ? '编辑物品' : '创造一件小心意' }}</h3>
              <button type="button" class="upload-tile" :disabled="pending" @click="customImageInput?.click()"><img v-if="draftItem.asset_id && assetUrls[draftItem.asset_id]" :src="assetUrls[draftItem.asset_id]" alt="自定义物品图片" /><span v-else><ImagePlus :size="26" />添加一张图片</span></button>
              <input ref="customImageInput" class="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" @change="uploadImage($event, 'item')" />
              <label>名称<input v-model="draftItem.name" data-testid="item-name" required maxlength="40" placeholder="给它起个名字" /></label>
              <label>描述<textarea v-model="draftItem.description" maxlength="800" rows="4" placeholder="它有什么特别的故事？"></textarea></label>
              <div class="form-grid"><label>类别<select v-model="draftItem.category"><option value="food">食物</option><option value="drink">饮品</option><option value="book">书籍</option><option value="toy">玩具</option><option value="furniture">家具纪念物</option><option value="decoration">装饰</option></select></label><label>用途<select v-model="draftItem.usage"><option value="eat">吃</option><option value="drink">喝</option><option value="read">阅读</option><option value="play">玩耍</option><option value="rest">休息</option><option value="decorate">赠送心意</option></select></label></div>
              <p class="helper">物品用于互动，不改变背景里的家具。描述不能赋予执行代码或访问网络的能力。</p>
              <button class="button primary full-width" :disabled="pending || !draftItem.name.trim()"><Save :size="16" />保存物品</button>
            </form>
          </div>
          <template v-else>
            <div class="item-controls"><div class="tabs"><button :class="{active:itemTab === 'inventory'}" @click="itemTab = 'inventory'">收纳</button><button :class="{active:itemTab === 'catalog'}" @click="itemTab = 'catalog'">物品库</button><button :class="{active:itemTab === 'custom'}" @click="itemTab = 'custom'">自定义</button></div><label class="search-field"><Search :size="16" /><input v-model="search" aria-label="搜索物品" placeholder="找一件小心意…" /></label></div>
            <div ref="itemScroll" class="panel-scroll item-scroll">
              <template v-if="isDefinitionTab">
                <div class="catalog-heading"><span>所有物品都可以免费添加</span><button class="text-button" aria-label="创造物品" @click="newItem"><Plus :size="16" />创造物品</button></div>
                <label class="category-select"><span>类别</span><select v-model="category"><option value="all">全部</option><option value="food">食物</option><option value="drink">饮品</option><option value="book">书籍</option><option value="toy">玩具</option><option value="furniture">家具纪念物</option><option value="decoration">装饰</option></select></label>
                <div v-if="!filteredDefinitions.length" class="empty-state"><Package :size="28" /><p>这里还没有物品。创造一件吧。</p></div>
                <div class="catalog-grid"><article v-for="definition in filteredDefinitions" :key="definition.id" class="catalog-card"><button class="catalog-art" :aria-label="`添加${definition.name}`" :disabled="pending" @click="addItem(definition)"><ItemArt :definition="definition" :images="assetUrls" /><span class="add-mark"><Plus :size="15" /></span></button><strong>{{ definition.name }}</strong><div class="catalog-meta"><span>{{ usageNames[definition.usage] }}</span><span v-if="!definition.builtin"><button class="tiny-icon" aria-label="编辑物品" @click="draftItem = clone(definition)"><Pencil :size="14" /></button><button class="tiny-icon danger" aria-label="删除自定义种类" @click="ask('删除这类物品？', '对应的收纳物品会一并移除，历史日记仍会保留。', async () => { await perform('items/delete-definition', {definition_id: definition.id}) })"><Trash2 :size="14" /></button></span></div></article></div>
              </template>
              <template v-else>
                <p class="helper inventory-hint">从收纳里直接使用或赠送。不必摆放，也不会把家具叠到房间画面上。</p>
                <section v-if="selected && selectedDefinition" class="selected-item" aria-label="选中的物品"><div class="selection-info"><ItemArt :definition="selectedDefinition" :images="assetUrls" /><div><strong>{{ selectedDefinition.name }}</strong><span>{{ selectedDefinition.consumable ? `剩余 ${selected.quantity} 份` : usageNames[selectedDefinition.usage] }}</span></div><button class="tiny-icon" aria-label="取消选择" @click="selectedId = null"><X :size="17" /></button></div><p>{{ selectedDefinition.description }}</p><div class="selection-actions"><button v-if="selectedDefinition.usage !== 'decorate'" class="button primary" :disabled="pending || !selected.quantity" @click="interact('use')">{{ usageNames[selectedDefinition.usage] }}</button><button class="button outline" :disabled="pending || !selected.quantity" @click="interact('gift')"><Gift :size="16" />送给她</button><button class="icon-button danger" aria-label="移除物品" :disabled="pending" @click="removeSelected"><Trash2 :size="17" /></button></div></section>
                <div v-if="!visibleInstances.length" class="empty-state"><Package :size="28" /><p>收纳里暂时没有这些物品。</p><button class="button outline" @click="itemTab = 'catalog'">去物品库看看</button></div>
                <button v-for="item in visibleInstances" :key="item.id" class="bag-item" :class="{selected:selectedId === item.id}" :aria-label="`选择${home.definitions.find(d => d.id === item.definition_id)?.name}`" @click="selectInventory(item)"><ItemArt :definition="home.definitions.find(d => d.id === item.definition_id)!" :images="assetUrls" /><span><strong>{{ home.definitions.find(d => d.id === item.definition_id)?.name }}</strong><small>{{ item.quantity ? usageNames[home.definitions.find(d => d.id === item.definition_id)!.usage] : '已经用完，可移除后补充' }}</small></span><b>×{{ item.quantity }}</b><ChevronRight :size="16" /></button>
              </template>
            </div>
          </template>
        </template>

        <template v-else-if="panel === 'diary'">
          <div class="tabs diary-tabs"><button :class="{active:diaryTab === 'events'}" @click="diaryTab = 'events'">日常足迹</button><button :class="{active:diaryTab === 'memories'}" @click="diaryTab = 'memories'">共同记忆</button></div>
          <div class="panel-scroll"><template v-if="diaryTab === 'events'"><p class="helper">只记下真实发生的小事。</p><div v-if="!diaryEvents.length" class="empty-state"><BookHeart :size="28" /><p>今晚的故事，还等着一起写。</p></div><article v-for="entry in diaryEvents" :key="entry.id" class="timeline-entry"><span class="timeline-dot"></span><time>{{ time(entry.created_at) }}</time><p>{{ entry.text }}</p></article><button v-if="diaryEvents.length" class="text-button load-more" @click="loadMore('events')">更早的足迹</button></template>
            <template v-else><p class="helper">从共同经历里记住的小事，也可以亲手告诉她。</p><form class="memory-form" @submit.prevent="addMemory"><textarea v-model="memoryText" aria-label="新的记忆" placeholder="比如，你喜欢少糖的热茶。" maxlength="500" rows="3"></textarea><button class="button primary" :disabled="pending || !memoryText.trim()"><Plus :size="16" />记住这件事</button></form><article v-for="memory in memories" :key="memory.id" class="memory-entry"><span class="memory-source">{{ memory.source === 'user' ? '你告诉她的' : '一起经历的' }}</span><p>{{ memory.text }}</p><button class="tiny-icon" aria-label="删除记忆" @click="ask('忘记这条记忆？', '只删除这条共同记忆，不会删除对应聊天或日记。', async () => { if (await perform('memories/delete', {memory_id: memory.id})) olderMemories = olderMemories.filter(m => m.id !== memory.id) })"><Trash2 :size="15" /></button></article><button v-if="memories.length" class="text-button load-more" @click="loadMore('memories')">更早的记忆</button></template>
          </div>
        </template>

        <template v-else-if="panel === 'settings' && settingsDraft">
          <div class="settings-categories" role="group" aria-label="设置分类"><button v-for="group in settingsGroups" :key="group.id" :aria-pressed="settingsGroup===group.id" @click="selectSettingsGroup(group.id)">{{group.name}}</button></div>
          <div class="panel-scroll settings-scroll">
            <ComputerPanel v-if="settingsGroup === 'computer'" initial-tab="settings" :bridge="bridge" :providers="providers" @dirty="computerDirty=$event" />
            <form v-show="settingsGroup==='life' || settingsGroup==='character'" @submit.prevent="saveSettings">
              <section v-show="settingsGroup==='life'" class="settings-section"><h3><Sparkles :size="17" />聊天与自主生活</h3><p class="helper">后台生活默认暂停。聊天、直接互动接话和主动搭话分别计数；下方可关闭互动模型回应。</p>
                <label>聊天模型<select v-model="settingsDraft.provider_id" data-testid="provider-select"><option value="">请选择已配置的模型</option><option v-for="provider in providers" :key="provider.id" :value="provider.id">{{ provider.name }}</option></select></label>
                <label class="toggle-row"><span>开启自主生活</span><input v-model="settingsDraft.autonomous_enabled" type="checkbox" role="switch" :disabled="!settingsDraft.provider_id" data-testid="autonomy-toggle" /></label>
                <details><summary>高级频率与额度</summary><div class="form-grid"><label>间隔 · 分钟<input v-model.number="settingsDraft.interval_minutes" required type="number" min="1" max="1440" /></label><label>每日自主调用上限<input v-model.number="settingsDraft.daily_limit" required type="number" min="0" max="1440" /></label></div></details>
                <div class="usage-summary"><span>今日自主 <b>{{ snapshot.usage.autonomy }} / {{ home.settings.daily_limit }}</b></span><span>今日聊天 <b>{{ snapshot.usage.chat }}</b></span></div><p v-if="snapshot.runtime.last_error" class="inline-error">{{ snapshot.runtime.last_error }}</p>
              </section>
              <section v-show="settingsGroup==='character'" class="settings-section"><h3><Heart :size="17" />你和她</h3><div class="form-grid"><label>她的名字<input v-model="settingsDraft.character_name" required maxlength="30" /></label><label>她怎么称呼你<input v-model="settingsDraft.user_name" required maxlength="30" /></label></div><label>角色设定<textarea v-model="settingsDraft.persona" maxlength="6000" rows="5"></textarea></label><button v-if="snapshot.companion" type="button" class="text-button" @click="choosePlayfulPersona"><Sparkles :size="14" />使用俏皮人设预设</button><p class="helper">已有自定义人设不会自动替换。只有你确认并保存后才修改。</p><label>时区<input v-model="settingsDraft.timezone" required placeholder="Asia/Shanghai" /></label></section>
              <section v-show="settingsGroup==='character'" class="settings-section"><h3><ImagePlus :size="17" />她在房间里的模样</h3>
                <label>角色比例<select v-model="settingsDraft.character_style" data-testid="character-style"><option value="portrait">正常人物比例</option><option value="chibi">Q 版形象</option></select></label>
                <div v-for="slot in [{key:'portrait_asset',label:'正常比例立绘'}, {key:'chibi_asset',label:'Q 版形象'}]" :key="slot.key" class="asset-setting"><span>{{ slot.label }}</span><div><button type="button" class="icon-button" :aria-label="`更换${slot.label}`" :disabled="pending" @click="imageSlot = slot.key as typeof imageSlot; portraitInput?.click()"><ImagePlus :size="18" /></button><button v-if="settingsDraft[slot.key as typeof imageSlot]" type="button" class="icon-button" aria-label="恢复默认图片" @click="settingsDraft![slot.key as typeof imageSlot] = null"><RefreshCw :size="16" /></button></div></div>
                <p class="helper">建议使用脚底对齐、无额外透明边缘的立绘。固定夜景背景不可替换；旧背景图片仍随存档保存。</p>
              </section><button class="button primary full-width" :disabled="pending || !settingsChanged"><Save :size="17" />保存设置</button>
            </form>
            <CharacterMotionSettings v-show="settingsGroup==='character'" :status="roomRendererStatus" />
            <CompanionSettings v-show="settingsGroup==='life'" @dirty="companionDirty=$event" v-if="snapshot.companion" :companion="snapshot.companion" :has-model="Boolean(home.settings.provider_id)" :is-chibi="home.settings.character_style === 'chibi'" :pending="pending" :save="saveCompanion" />
            <SkillsSettings v-show="settingsGroup==='skills'" @dirty="skillsDirty=$event" v-if="snapshot.skills" :bridge="bridge" :skills="snapshot.skills" :stopping="skillStopping" :timezone="home.settings.timezone" @saved="update" @stop="stopSkills" @notice="notice" />
            <section v-show="settingsGroup==='data'" class="settings-section archive-section"><h3><Package :size="17" />存档</h3><p class="helper">支持导入 v1 / v2 存档；恢复前自动备份，恢复后暂停自主生活。旧布局转入收纳。</p><div class="form-grid"><button class="button outline" @click="exportArchive"><Download :size="16" />导出存档</button><button class="button outline" :disabled="pending || snapshot.runtime.busy" @click="fileInput?.click()"><ArrowUpFromLine :size="16" />恢复存档</button></div></section>
            <section v-show="settingsGroup==='data'" class="settings-section"><h3>数据整理</h3><button class="text-button danger" @click="ask('清空聊天记录？', '全部聊天记录将被删除，共同记忆与小家保持不变。', async () => { if (await perform('messages/clear')) olderMessages = [] })"><Trash2 :size="15" />清空聊天记录</button><button class="text-button danger" @click="ask('清空共同记忆？', '长期记忆将被清空，聊天和日常足迹仍然保留。', async () => { if (await perform('memories/clear')) olderMemories = [] })"><Trash2 :size="15" />清空共同记忆</button></section>
            <div v-show="settingsGroup==='data'" class="preview-art-note" data-testid="artwork-progress"><strong>互动可玩预览 · {{ artworkProgress.count }}/{{ artworkProgress.total }} 张差分</strong><p v-if="artworkProgress.pending.length">待补齐：{{ artworkProgress.pending.join('、') }}。未接入的动作暂用表情反馈，不算专用插画。</p><p v-else>表情与专用动作图已齐。动作结束后回到当前表情，再恢复待机；休息是在床边站立放松。</p><p>自定义图片不套用默认差分。Q 版已更换为新正面，进食暂用同一张静态图。公开版本，已包含全部 12 张差分。</p></div>
            <footer v-show="settingsGroup==='data'" class="about"><span>WHALE HOME · v0.4.2 PUBLIC RELEASE</span><p>非官方社区同人作品 · 素材公开分发由用户确认</p><p>夜景图为已有概念图衍生，公开分发已由用户确认。<br />Q 版：用户提供的三视图正面（2026-11-02）<br />正常比例立绘：用户提供的 deepseek.png<br />公开分发依据用户确认 · 作者及底层授权未独立核实 · 图片不自动适用 MIT</p></footer>
          </div>
          <input ref="portraitInput" class="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" @change="uploadImage($event, 'character')" />
          <input ref="fileInput" class="visually-hidden" type="file" accept=".json,application/json" @change="importArchive" />
        </template>
      </aside>
    </Transition>

    <Transition name="toast"><div v-if="toast" class="toast-message" :class="{ error: toast.error }" role="status"><Check v-if="!toast.error" :size="17" /><span>{{ toast.text }}</span><button class="tiny-icon" aria-label="关闭提示" @click="toast = null"><X :size="15" /></button></div></Transition>
    <dialog v-if="confirmation" ref="confirmDialog" class="confirmation-dialog" @cancel="confirmation = null" @close="confirmation = null"><h2>{{ confirmation.title }}</h2><p>{{ confirmation.text }}</p><div><button class="button outline" autofocus @click="confirmDialog?.close(); confirmation = null">取消</button><button class="button primary" :disabled="pending" @click="confirm">确认</button></div></dialog>
  </div>
</template>
