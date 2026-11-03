<script setup lang="ts">
import { computed } from 'vue'
import { Package } from '@lucide/vue'
import type { Definition } from '../types'
import { itemIcons } from '../icons'

const props = defineProps<{ definition: Definition; images: Record<string, string> }>()
const src = computed(() => props.definition.asset_id
  ? props.images[props.definition.asset_id]
  : props.definition.builtin ? `./art/items/${props.definition.id}.svg` : null)
</script>

<template>
  <img v-if="src" class="item-art" :src="src" :alt="definition.name" draggable="false" />
  <component v-else :is="itemIcons[definition.icon] || Package" class="item-art fallback-art" :aria-label="definition.name" />
</template>

