<script setup lang="ts">
import { computed } from 'vue'
import { modeLabels, motionManifest, useCharacterMotionPreference } from '../character-motion'
import type { RendererStatus } from '../character-motion'
defineProps<{ status?: RendererStatus }>()
const { mode, setMode, persistent } = useCharacterMotionPreference()
const webpCount = computed(() => Object.values(motionManifest.characters).flatMap(c => Object.values(c.frames)).filter(f => f?.webp?.reviewed).length)
</script>
<template>
  <section class="settings-section" data-testid="character-motion-settings">
    <h3>角色动画 · 仅此浏览器</h3>
    <label>显示方式<select :value="mode" data-testid="character-render-mode" @change="setMode(($event.target as HTMLSelectElement).value)"><option value="webp">透明动图（默认）</option><option value="static">静态</option></select></label>
    <p class="helper">立即生效，不需要保存，不写入个人存档。未制作动图的动作使用静态图；自定义立绘保持原图。</p>
    <p v-if="!persistent" class="helper" data-testid="character-motion-storage-warning">宿主或浏览器禁用了本地存储：当前选择仅本页面有效，刷新后恢复默认；不会改写角色存档。跨刷新保存需宿主支持浏览器偏好存储。</p>
    <p class="helper" data-testid="character-motion-readiness">已审核动图 {{ webpCount }}/15，未制作的动作保持静态。</p>
    <p v-if="status" class="helper" data-testid="character-motion-status">当前：{{ modeLabels[status.mode] }}{{ status.reason ? ' · ' + status.reason : '' }}</p>
    <p class="helper">系统开启“减少动态效果”时使用静态图；隐藏页面时暂停动画。</p>
  </section>
</template>
