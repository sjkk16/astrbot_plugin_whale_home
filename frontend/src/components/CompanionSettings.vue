<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { MessageCircle, Save } from '@lucide/vue'
import type { Companion, CompanionPreferences } from '../types'
const props = defineProps<{
  companion: Companion; hasModel: boolean; isChibi: boolean; pending: boolean
  save: (preferences: CompanionPreferences) => Promise<boolean>
}>()
const emit = defineEmits<{dirty:[boolean]}>()
const draft = ref<CompanionPreferences>({ ...props.companion.preferences })
const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(props.companion.preferences))
watch(dirty, value=>emit('dirty',value))
watch(() => props.companion.preferences, (value, old) => {
  if (JSON.stringify(draft.value) === JSON.stringify(old)) draft.value = { ...value }
})
async function save() {
  const value = { ...draft.value }
  if (await props.save(value)) draft.value = { ...props.companion.preferences }
}
</script>

<template>
  <form class="settings-section companion-settings" @submit.prevent="save">
    <h3><MessageCircle :size="17" />互动与偶尔搭话</h3>
    <p class="helper">与「后台自主生活」分开控制。动作总能本地完成，模型只补一句回应，不重复吃饭或使用物品。</p>
    <label class="toggle-row"><span>直接互动时，让模型接话</span><input v-model="draft.interaction_model_enabled" type="checkbox" role="switch" /></label>
    <p class="helper">至少间隔 {{ companion.limits.interaction_interval_seconds }} 秒，每天最多 {{ companion.limits.interaction_daily_limit }} 次；连点、无模型或失败时保留本地回应，不自动重试。</p>
    <label class="toggle-row"><span>允许她偶尔主动搭话</span><input v-model="draft.proactive_enabled" type="checkbox" role="switch" data-testid="proactive-toggle" :disabled="!hasModel && !draft.proactive_enabled" /></label>
    <p v-if="!hasModel" class="helper">先在上方选择并保存聊天模型。预览可以选「本地演示」，不产生在线调用。</p>
    <p v-if="isChibi" class="helper">Q 版保留原有玩法，不触发直接触碰和主动搭话；你的陪伴偏好仍会保留。</p>
    <div class="form-grid"><label>空闲至少 · 分钟<input v-model.number="draft.idle_minutes" required type="number" min="5" max="60" /></label><label>搭话间隔 · 分钟<input v-model.number="draft.interval_minutes" required type="number" min="15" max="1440" /></label></div>
    <label>每日主动搭话上限<input v-model.number="draft.daily_limit" required type="number" min="0" max="24" /></label>
    <div class="usage-summary"><span>今日互动接话 <b>{{ companion.usage.interaction }} / {{ companion.limits.interaction_daily_limit }}</b></span><span>今日主动 <b>{{ companion.usage.proactive }} / {{ companion.preferences.daily_limit }}</b></span></div>
    <p class="helper companion-boundaries">只在正常比例页面可见且空闲时开口。你没回复，就不连发；开始打字或关页会打断待发送的搭话。刷新不重置次数，跨页共享限额。</p>
    <p v-if="companion.awaiting_reply" class="companion-note">她已经说过一句啦，等你有空再接，不会追着问。</p>
    <button class="button outline full-width" :disabled="pending || !dirty"><Save :size="16" />保存陪伴设置</button>
    <p class="helper companion-boundaries">这些限频偏好保存在本机，暂不写进 v2 导出存档。恢复存档后主动搭话关闭，已有调用计数不清零。</p>
  </form>
</template>
