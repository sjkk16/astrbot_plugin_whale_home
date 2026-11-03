<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { Bridge, Capability, SkillCall, SkillPreferences, SkillsState, Snapshot } from '../types'

const props = defineProps<{ bridge: Bridge; skills: SkillsState; stopping: boolean; timezone: string }>()
const emit = defineEmits<{ dirty:[boolean]; saved: [Snapshot]; stop: []; notice: [string, boolean] }>()
const clone = (value: SkillPreferences): SkillPreferences => JSON.parse(JSON.stringify(value))
const draft = ref(clone(props.skills.preferences))
const catalog = ref<Capability[]>([])
const query = ref('')
const kind = ref('all')
const saving = ref(false)
const loading = ref(false)
const error = ref('')
const older = ref<SkillCall[]>([])
const confirmation = ref<HTMLDialogElement>()
const baseline = ref(JSON.stringify(props.skills.preferences))
const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
watch(dirty,value=>emit('dirty',value))
const visible = computed(() => catalog.value.filter(item => (kind.value === 'all' || item.kind === kind.value)
  && `${item.name} ${item.description} ${item.source}`.toLowerCase().includes(query.value.toLowerCase())))
const records = computed(() => [...new Map([...older.value, ...props.skills.calls].map(item => [item.id, item])).values()].sort((a, b) => b.id - a.id))
const labels: Record<string, string> = { running: '执行中', succeeded: '已完成', failed: '失败', denied: '未获授权', unknown: '结果未确认', chat: '聊天', interaction: '直接互动', proactive: '主动搭话', autonomy: '自主生活' }
watch(() => JSON.stringify(props.skills.preferences), value => { if(!dirty.value) { draft.value=JSON.parse(value); baseline.value=value } })
function callTime(value: string) {
  const parsed = new Date(value)
  return Number.isFinite(parsed.getTime()) ? new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: props.timezone,
  }).format(parsed) : '时间不可用'
}
async function load() {
  loading.value = true
  error.value = ''
  try { catalog.value = await props.bridge.apiGet<Capability[]>('skills/catalog') }
  catch (e) { error.value = e instanceof Error ? e.message : '能力目录暂不可用' }
  finally { loading.value = false }
}
function selected(item: Capability) {
  return (item.kind === 'tool' ? draft.value.allowed_tools : draft.value.allowed_skills).includes(item.name)
}
function toggle(item: Capability, checked: boolean) {
  const key = item.kind === 'tool' ? 'allowed_tools' : 'allowed_skills'
  draft.value[key] = checked ? [...new Set([...draft.value[key], item.name])].sort() : draft.value[key].filter(name => name !== item.name)
}
function save() {
  const old = props.skills.preferences
  if (draft.value.enabled && draft.value.access_mode === 'full' && !(old.enabled && old.access_mode === 'full')) confirmation.value?.showModal()
  else void submit(false)
}
async function submit(confirmed: boolean) {
  confirmation.value?.close()
  saving.value = true
  try {
    const latest = await props.bridge.apiGet<Snapshot>('state')
    if(JSON.stringify(latest.skills?.preferences) !== baseline.value) throw new Error('技能权限已在其他页面修改，请重新打开设置后编辑。')
    const state = await props.bridge.apiPost<Snapshot>('skills/preferences', {
      request_id: crypto.randomUUID(), expected_version: latest.home.version,
      preferences: clone(draft.value), confirm_full_access: confirmed,
    })
    baseline.value=JSON.stringify(state.skills!.preferences); draft.value=clone(state.skills!.preferences)
    emit('saved', state)
    emit('notice', '技能权限已保存', false)
  } catch (e) {
    emit('notice', e instanceof Error ? e.message : '保存失败，请刷新后重试', true)
  } finally { saving.value = false }
}
async function history() {
  try {
    const before = records.value.at(-1)?.id
    const result = await props.bridge.apiGet<{ items: SkillCall[] }>('skills/calls', before ? { before } : {})
    older.value.push(...result.items)
  } catch { emit('notice', '调用记录暂时无法加载', true) }
}
onMounted(load)
</script>

<template>
  <section class="settings-section skills-settings" aria-label="技能与工具" data-testid="skills-settings">
    <h3>技能与工具 <span class="skills-badge">开发预览</span></h3>
    <p class="helper">聊天、直接互动接话、主动搭话和自主生活共用这些权限。原有场景开关独立生效。</p>
    <label class="toggle-row"><span>启用技能与工具</span><input v-model="draft.enabled" type="checkbox" role="switch" aria-label="启用技能与工具" /></label>
    <label>访问模式<select v-model="draft.access_mode" aria-label="技能访问模式"><option value="restricted">限制访问</option><option value="full">完全访问</option></select></label>
    <p class="helper" v-if="draft.access_mode === 'restricted'">只有勾选的能力可用，白名单内自动执行，不逐次确认。选择技能不会自动授权依赖工具。</p>
    <p class="skills-warning" v-else>完全访问会自动开放宿主已启用且兼容的能力，后台也可能执行命令、修改文件或发送消息。宿主权限和沙箱仍然生效。</p>
    <p class="helper">白名单控制工具选择，不是额外的脚本沙箱。命令工具或第三方插件内部能做什么，仍取决于宿主权限和工具本身。</p>
    <div class="skills-filters"><input v-model="query" type="search" aria-label="搜索技能与工具" placeholder="搜索名称、说明或来源" /><select v-model="kind" aria-label="能力类别"><option value="all">全部</option><option value="tool">工具</option><option value="skill">Skills</option></select><button type="button" class="text-button" :disabled="loading" @click="load">刷新目录</button></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <p v-else-if="loading" class="helper">正在读取宿主能力目录…</p>
    <p v-else-if="!visible.length" class="helper">没有匹配的能力。请先在 AstrBot 中安装并启用工具或技能。</p>
    <div class="skills-catalog">
      <label v-for="item in visible" :key="`${item.kind}:${item.name}`" class="skills-entry">
        <input type="checkbox" :aria-label="`允许 ${item.name}`" :checked="draft.access_mode === 'full' ? item.available : selected(item)" :disabled="(!item.available && !selected(item)) || draft.access_mode === 'full'" @change="toggle(item, ($event.target as HTMLInputElement).checked)" />
        <span><strong>{{ item.name }}</strong><small>{{ item.kind === 'skill' ? 'Skill' : '工具' }} · {{ item.source }}</small><span>{{ item.description }}</span><em v-if="!item.available">不可用：{{ item.reason }}</em></span>
      </label>
    </div>
    <button type="button" class="button primary" :disabled="saving || !dirty" @click="save">{{ saving ? '正在保存…' : '保存技能权限' }}</button>
    <p class="helper">无每日／单轮工具次数配额；保留 60 秒整轮超时和宿主限制。调用可能产生额外费用。权限不进入导出存档，恢复存档后白名单清空。</p>
    <div v-if="skills.active" class="skills-active" role="status"><span>{{ skills.active.stopping ? '正在停止' : '正在使用技能' }} · {{ labels[skills.active.trigger] }}<br />{{ skills.active.name || '正在思考下一步' }}</span><button type="button" class="button outline" :disabled="stopping || skills.active.stopping" @click="emit('stop')">停止本轮技能</button></div>
    <p class="helper">停止只阻止后续调用，不能保证撤销已开始的外部操作。“结果未确认”不代表没有执行。</p>
    <pre v-if="skills.output" class="skills-output" aria-label="工具会话输出">{{ skills.output }}</pre>
    <h4>调用记录</h4>
    <p v-if="!records.length" class="helper">还没有工具调用。记录不保存完整参数或工具输出。</p>
    <ol class="skills-history"><li v-for="call in records" :key="call.id"><div><strong>{{ call.name }}</strong><span :class="`call-${call.status}`">{{ labels[call.status] }}</span></div><small>{{ labels[call.trigger] }} · {{ call.source }} · {{ callTime(call.created_at) }} · {{ call.duration_ms === null ? '—' : `${call.duration_ms} ms` }}</small><small v-if="call.error_code">{{ call.error_code }}</small></li></ol>
    <button v-if="records.length" type="button" class="text-button" @click="history">更早的调用</button>
    <dialog ref="confirmation" class="confirmation-dialog"><h2>开启完全访问？</h2><p>所有模型场景（包括后台）都可自动使用宿主已启用且兼容的能力，可能修改文件、执行命令、对外发送信息并产生费用。不绕过宿主权限；已执行操作不保证撤销。</p><div><button type="button" class="button outline" autofocus @click="confirmation?.close()">取消</button><button type="button" class="button primary" @click="submit(true)">确认完全访问</button></div></dialog>
  </section>
</template>

<style scoped>
.skills-badge { font-size: 10px; font-weight: 400; color: #b6c4e6; border: 1px solid #ffffff25; border-radius: 5px; padding: 2px 5px; }
.skills-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 14px 0; }
.skills-filters input { flex: 1 1 160px; min-width: 0; }
.skills-filters select { width: auto; }
.skills-warning { border: 1px solid #d6a78055; background: #d6a78010; border-radius: 8px; padding: 12px; font-size: 12px; line-height: 1.7; color: #e4c19f; }
.skills-catalog { max-height: 300px; overflow: auto; margin-bottom: 14px; }
.skills-entry { display: flex; align-items: flex-start; gap: 10px; padding: 12px 2px; border-bottom: 1px solid #ffffff12; cursor: pointer; }
.skills-entry > input { flex: 0 0 16px; width: 16px; margin-top: 3px; }
.skills-entry > span { display: grid; gap: 4px; min-width: 0; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.skills-entry small, .skills-history small { color: #8f9ab5; font-size: 10px; display: block; overflow-wrap: anywhere; }
.skills-entry em { font-style: normal; color: #d5ad91; }
.skills-active { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12px; padding: 12px; background: #91a5dd12; border-radius: 8px; }
.skills-output { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 180px; overflow: auto; font-size: 12px; }
.skills-history { padding: 0; list-style: none; max-height: 260px; overflow: auto; }
.skills-history li { padding: 10px 0; border-bottom: 1px solid #ffffff12; }
.skills-history li > div { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; overflow-wrap: anywhere; }
.call-succeeded { color: #a3c7b5; }.call-unknown, .call-denied, .call-failed { color: #dfb08a; }
</style>
