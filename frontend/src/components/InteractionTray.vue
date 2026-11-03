<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { BookOpen, Coffee, Heart, MessageCircle, Moon, Package, Sparkles, Utensils, X } from '@lucide/vue'
import type { DirectInteraction, Home, Scene } from '../types'

const props = defineProps<{ home: Home; scene: Scene; pending: boolean; petBlocked: boolean }>()
const emit = defineEmits<{ interact: [value: DirectInteraction]; chat: []; items: []; close: [] }>()
const tray = ref<HTMLElement>()
const tab = ref<'items' | 'activities'>('items')
const items = computed(() => props.home.instances.flatMap(instance => {
  const definition = props.home.definitions.find(value => value.id === instance.definition_id)
  return definition && instance.quantity > 0 ? [{ instance, definition }] : []
}).sort((a, b) => {
  const order = ['eat', 'drink', 'decorate', 'read', 'play', 'rest']
  return order.indexOf(a.definition.usage) - order.indexOf(b.definition.usage)
}))
onMounted(async () => { await nextTick(); tray.value?.focus() })
</script>

<template>
  <section ref="tray" class="interaction-tray" tabindex="-1" aria-label="直接互动">
    <header><div><span class="eyebrow">A LITTLE CLOSER</span><h2>靠近一点，陪她玩</h2></div><button class="icon-button" aria-label="关闭互动" @click="emit('close')"><X :size="19" /></button></header>
    <p class="interaction-hint">不必先打字。递给她的每一件东西，都会真实记在小家里。</p>
    <div class="touch-actions">
      <button class="button primary" :disabled="pending || petBlocked" :title="petBlocked ? '轻一点，稍等一秒再摸。' : '轻轻摸摸她的头'" @click="emit('interact', { kind: 'pet' })"><Heart :size="18" />摸摸头</button>
      <button class="button outline" @click="emit('chat')"><MessageCircle :size="18" />聊两句</button>
    </div>
    <div class="tabs interaction-tabs" aria-label="互动种类"><button :class="{ active: tab === 'items' }" @click="tab = 'items'">递点东西</button><button :class="{ active: tab === 'activities' }" @click="tab = 'activities'">一起做点事</button></div>
    <div v-if="tab === 'items'" class="interaction-options">
      <p v-if="!items.length" class="helper">收纳暂时空了，先去物品库免费补充一点吧。</p>
      <button v-for="{ instance, definition } in items" :key="instance.id" class="interaction-item" :disabled="pending"
        :aria-label="'递给她：' + definition.name" @click="emit('interact', { kind: 'item', instance_id: instance.id, mode: definition.usage === 'decorate' ? 'gift' : 'use' })">
        <component :is="definition.usage === 'eat' ? Utensils : definition.usage === 'drink' ? Coffee : Package" :size="17" />
        <span><strong>{{ definition.name }}</strong><small>{{ definition.consumable ? '使用 1 份 · 剩余 ' + instance.quantity : definition.usage === 'decorate' ? '赠送心意 · 不移走纪念物' : '一起使用 · 可以反复玩' }}</small></span><span class="give-label">递给她</span>
      </button>
    </div>
    <div v-else class="interaction-options">
      <button v-for="spot in scene.spots" :key="spot.id" class="interaction-item" :disabled="pending" @click="emit('interact', { kind: 'scene', spot_id: spot.id })">
        <component :is="spot.id === 'bookshelf' ? BookOpen : spot.id === 'window' ? Moon : Sparkles" :size="17" /><span><strong>{{ spot.label }}</strong><small>{{ spot.name }} · 固定活动，不消耗库存</small></span>
      </button>
    </div>
    <footer><span>动作先完成，接话不重复消耗。</span><button class="text-button" @click="emit('items')">去收纳看看 →</button></footer>
  </section>
</template>
