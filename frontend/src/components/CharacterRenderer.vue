<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { chooseRenderer, entryForSource, useCharacterMotionPreference } from '../character-motion'
import type { CharacterStyle, RendererStatus } from '../character-motion'
import { loadAnimatedWebp } from '../animated-webp'

const props = withDefaults(defineProps<{ source: string; styleId: CharacterStyle; alt: string; eventId: string; custom?: boolean; active?: boolean }>(), { custom: false, active: true })
const emit = defineEmits<{ status: [value: RendererStatus] }>()
const { mode } = useCharacterMotionPreference()
const media = matchMedia('(prefers-reduced-motion: reduce)')
const reduced = ref(media.matches)
const visible = ref(!document.hidden)
const webpReady = ref(false)
const webpUrl = ref('')
const webpFailed = ref(false)
const onceInterrupted = ref(false)
const entry = computed(() => entryForSource(props.styleId, props.source)?.[1])
const selection = computed(() => chooseRenderer(props.styleId, entry.value, mode.value, reduced.value, props.custom))
const wantsWebp = computed(() => mode.value !== 'static' && !reduced.value && !props.custom && entry.value?.webp?.reviewed && !webpFailed.value)
const running = computed(() => visible.value && props.active)
const showingWebp = computed(() => wantsWebp.value && webpReady.value && running.value && !onceInterrupted.value)
const imageSource = computed(() => showingWebp.value ? webpUrl.value : props.source)
const status = computed<RendererStatus>(() => {
  if (props.custom || reduced.value || mode.value === 'static') return selection.value
  if (showingWebp.value) return { mode: 'webp', reason: selection.value.reason, loading: false }
  if (!running.value && wantsWebp.value) return { mode: 'static', reason: '页面不可见，已暂停动画', loading: false }
  if (onceInterrupted.value) return { mode: 'static', reason: '一次性动作已播放，不重复触发', loading: false }
  if (webpFailed.value) return { mode: 'static', reason: '动态资源加载失败，已回退到静态原图', loading: false }
  if (wantsWebp.value) return { mode: 'static', reason: '正在加载动图，暂时显示静态原图', loading: true }
  return selection.value
})
watch(status, value => emit('status', value), { immediate: true })
watch([mode, () => props.styleId], () => { webpFailed.value = false })
watch([() => props.source, () => props.eventId], () => { webpFailed.value = false; onceInterrupted.value = false })
watch(running, value => { if (!value && showingWebp.value === false && webpReady.value && !entry.value?.loop) onceInterrupted.value = true })
watch([wantsWebp, entry, () => props.eventId, running, onceInterrupted], async ([enabled], _, onCleanup) => {
  webpReady.value = false; webpUrl.value = ''
  if (!enabled || !entry.value?.webp || !running.value || onceInterrupted.value) return
  const controller = new AbortController()
  let owned: Awaited<ReturnType<typeof loadAnimatedWebp>> | undefined
  const timeout = setTimeout(() => { controller.abort(); webpFailed.value = true }, 15000)
  onCleanup(() => { controller.abort(); clearTimeout(timeout); owned?.dispose() })
  try {
    owned = await loadAnimatedWebp(entry.value.webp, controller.signal)
    if (controller.signal.aborted) { owned.dispose(); return }
    webpUrl.value = owned.url; webpReady.value = true
  } catch { if (!controller.signal.aborted) webpFailed.value = true }
  finally { clearTimeout(timeout) }
}, { immediate: true })

function visibility() { visible.value = !document.hidden }
function preference() { reduced.value = media.matches }
media.addEventListener('change', preference)
document.addEventListener('visibilitychange', visibility)
onBeforeUnmount(() => { media.removeEventListener('change', preference); document.removeEventListener('visibilitychange', visibility) })
</script>

<template>
  <img :key="showingWebp ? eventId + imageSource : imageSource" class="character-surface" :src="imageSource" :alt="alt" :data-renderer="showingWebp ? 'webp' : 'static'" draggable="false" @error="showingWebp && (webpFailed = true)" />
</template>
