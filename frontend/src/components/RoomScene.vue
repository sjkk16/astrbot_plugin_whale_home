<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import CharacterRenderer from './CharacterRenderer.vue'
import { modeLabels } from '../character-motion'
import type { RendererStatus } from '../character-motion'
import { Sparkles, X } from '@lucide/vue'
import type { Companion, Home, Scene, SceneAnchor, SceneSpot, SpotId } from '../types'
import { characterFrame, currentPresentation, frameForSource, missingPoseLabel, previewArtwork } from '../character-art'
import { preloadCharacterSprites, useCharacterSprite } from '../use-character-sprite'

const props = defineProps<{ home: Home; scene: Scene; images: Record<string, string>; selectedId: SpotId | null; companion?: Companion; now: number; demo: boolean; showBubbles: boolean }>()
const emit = defineEmits<{ select: [id: SpotId]; character: []; chat: []; renderer: [value: RendererStatus] }>()
const renderStatus = ref<RendererStatus>({ mode: 'static', reason: '', loading: false })
function rendererStatus(value: RendererStatus) { renderStatus.value = value; emit('renderer', value) }
const customSprite = computed(() => Boolean(isChibi.value ? props.home.settings.chibi_asset : props.home.settings.portrait_asset))
const display = ref<SceneAnchor>({ ...props.scene.locations[props.home.character.location] })
const moving = ref(false)
const dismissedSpeech = ref('')
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)')
let frame = 0
const isChibi = computed(() => props.home.settings.character_style === 'chibi')
const presentation = computed(() => currentPresentation(props.companion, props.now))
const missingArtwork = computed(() => missingPoseLabel(props.home, props.companion, props.now))
const frameName = computed(() => characterFrame(props.home, props.companion, props.now, moving.value))
const reactionClass = computed(() => !isChibi.value && !props.home.settings.portrait_asset && presentation.value && props.now < Date.parse(presentation.value.pose_until) ? 'reaction-' + presentation.value.pose : '')
const bubbleStyle = computed(() => ({ left: Math.min(.78, Math.max(.22, display.value.x)) * 100 + '%', bottom: (1 - display.value.y + display.value.height + .015) * 100 + '%' }))
const bubbleLabel = computed(() => presentation.value?.model_status === 'pending' ? '她在想怎么接话' : presentation.value?.model_status === 'model' ? props.demo ? '演示接话 · 不联网' : presentation.value.source === 'proactive' ? '她先开了口' : '她的回应' : '本地回应 · 动作已完成')
const sprite = computed(() => {
  const custom = isChibi.value ? props.home.settings.chibi_asset : props.home.settings.portrait_asset
  if (custom && props.images[custom]) return props.images[custom]
  return isChibi.value
    ? props.home.character.activity === 'eat' ? './art/scene-chibi-eat.webp' : './art/scene-chibi-neutral.webp'
    : frameName.value === 'neutral' ? './art/scene-portrait.webp' : previewArtwork[frameName.value] || './art/scene-portrait.webp'
})
const safeSprite = computed(() => isChibi.value ? './art/scene-chibi-neutral.webp' : './art/scene-portrait.webp')
const spriteImage = useCharacterSprite(() => sprite.value, () => safeSprite.value)
const displayedFrame = computed(() => isChibi.value ? 'chibi' : frameForSource(spriteImage.value.src))
watch(() => !isChibi.value && !props.home.settings.portrait_asset, enabled => {
  if (enabled) void preloadCharacterSprites()
}, { immediate: true })
const characterStyle = computed(() => {
  const height = display.value.height * (isChibi.value ? .44 : 1)
  const ratio = spriteImage.value.width / spriteImage.value.height
  return {
    left: `${display.value.x * 100}%`, top: `${display.value.y * 100}%`,
    height: `${height * 100}%`, width: `${height * ratio * props.scene.height / props.scene.width * 100}%`,
    transform: `translate(-${(isChibi.value ? .5 : spriteImage.value.anchorX) * 100}%, -100%)`,
  }
})
function region(spot: SceneSpot) {
  return { left: `${spot.rect[0] * 100}%`, top: `${spot.rect[1] * 100}%`,
    width: `${spot.rect[2] * 100}%`, height: `${spot.rect[3] * 100}%` }
}
function marker(spot: SceneSpot) {
  return { left: `${(spot.marker[0] - spot.rect[0]) / spot.rect[2] * 100}%`,
    top: `${(spot.marker[1] - spot.rect[1]) / spot.rect[3] * 100}%` }
}
function settle() {
  cancelAnimationFrame(frame)
  moving.value = false
  display.value = { ...props.scene.locations[props.home.character.location] }
}
watch(() => props.home.character.movement_id, (id) => {
  cancelAnimationFrame(frame)
  const path = props.home.character.last_path
  if (!id || path.length < 2 || reducedMotion.matches) { settle(); return }
  const anchors = [{ ...display.value }, ...path.slice(1).map(location => props.scene.locations[location])]
  const lengths = anchors.slice(1).map((point, index) => Math.hypot(point.x - anchors[index]!.x, point.y - anchors[index]!.y))
  const total = lengths.reduce((a, b) => a + b, 0)
  if (total < .001) { settle(); return }
  const duration = Math.max(650, Math.min(2600, total * 6400))
  const started = performance.now()
  moving.value = true
  const draw = (now: number) => {
    const elapsed = Math.min(1, (now - started) / duration)
    let distance = total * (elapsed * elapsed * (3 - 2 * elapsed))
    let segment = 0
    while (segment < lengths.length - 1 && distance > lengths[segment]!) distance -= lengths[segment++]!
    const a = anchors[segment]!, b = anchors[segment + 1]!
    const t = Math.min(1, distance / (lengths[segment] || 1))
    display.value = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t,
      height: a.height + (b.height - a.height) * t, light: t < .5 ? a.light : b.light }
    if (elapsed < 1) frame = requestAnimationFrame(draw)
    else settle()
  }
  frame = requestAnimationFrame(draw)
})
// Stop in-place immediately if the motion preference changes during a transition.
watch(() => props.home.character.location, () => {
  if (reducedMotion.matches) settle()
})
reducedMotion.addEventListener('change', settle)
onBeforeUnmount(() => { cancelAnimationFrame(frame); reducedMotion.removeEventListener('change', settle) })
</script>

<template>
  <div class="room-scene" data-testid="room" :style="{ aspectRatio: `${scene.width} / ${scene.height}` }">
    <img class="room-background" :src="scene.background" alt="正面平视的夜间卧室：左侧书桌与书架、中央月光窗景、右侧床与暖灯" draggable="false" fetchpriority="high" />
    <div class="window-snow" aria-hidden="true"><i v-for="flake in 9" :key="flake" :style="{ '--flake': flake }"></i></div>
    <button v-for="spot in scene.spots" :key="spot.id" class="scene-hotspot"
      :class="{ selected: selectedId === spot.id }" :style="region(spot)"
      :aria-label="`选择${spot.name}`" :aria-pressed="selectedId === spot.id"
      :data-testid="`spot-${spot.id}`" @click="emit('select', spot.id)">
      <span class="hotspot-marker" :style="marker(spot)"><Sparkles :size="15" /><span class="hotspot-label">{{ spot.name }}</span></span>
    </button>
    <button class="room-character managed-motion" :class="[{ moving, chibi: isChibi }, display.light, reactionClass]" :style="characterStyle"
      :aria-label="`和${home.settings.character_name}${isChibi ? '聊天' : '互动'}`" data-testid="character"
      :data-pose="presentation?.pose || 'neutral'" :data-location="home.character.location" :data-moving="moving" :data-frame="displayedFrame" :data-requested-frame="frameName" :data-anchor-x="isChibi ? .5 : spriteImage.anchorX" @click="emit('character')">
      <span class="character-shadow" aria-hidden="true"></span>
      <CharacterRenderer :source="spriteImage.src" :style-id="isChibi ? 'chibi' : 'portrait'" :alt="home.settings.character_name" :custom="customSprite" :event-id="(presentation?.id || home.character.movement_id || 'idle') + ':' + frameName" @status="rendererStatus" />
      <span class="character-invitation">{{ isChibi ? '和她聊聊' : '点我 · 摸摸头 / 递点东西' }}</span>
    </button>
    <div v-if="!isChibi && showBubbles && presentation && dismissedSpeech !== presentation.id && (presentation.speech || presentation.model_status === 'pending')" class="character-bubble" :style="bubbleStyle" data-testid="character-bubble" role="status" aria-live="polite">
      <header class="bubble-heading"><span class="bubble-caption">{{ bubbleLabel }}</span><button class="bubble-close" aria-label="收起这句回应" @click="dismissedSpeech = presentation.id"><X :size="14" /></button></header><p>{{ presentation.speech || '嗯……想到一个小话题。' }}</p>
      <small v-if="missingArtwork" class="artwork-fallback" data-testid="artwork-fallback">{{ missingArtwork }}</small>
      <button @click="emit('chat')">回她一句 →</button>
    </div>
    <span class="character-mode-badge" data-testid="room-renderer-status" :title="renderStatus.reason">{{ modeLabels[renderStatus.mode] }}{{ renderStatus.loading ? ' · 加载中' : renderStatus.reason ? ' · ' + renderStatus.reason : '' }}</span>
    <div class="scene-signature" aria-hidden="true">A LITTLE ROOM, A QUIET NIGHT</div>
  </div>
</template>
