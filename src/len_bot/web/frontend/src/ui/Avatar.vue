<script setup lang="ts">
import { computed } from 'vue'
import { AvatarFallback, AvatarImage, AvatarRoot } from 'reka-ui'

const props = withDefaults(
  defineProps<{
    name: string
    src?: string | null
    size?: number
    /** Groups and plugins are square, people and personas round. */
    shape?: 'circle' | 'square'
  }>(),
  { src: null, size: 32, shape: 'circle' },
)

/** First visible character, so names starting with an emoji or a surrogate pair stay whole. */
const initial = computed(() => {
  const [first] = new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(props.name.trim())
  return first?.segment.toUpperCase() ?? '?'
})
/** Without an image the initial is drawn directly; Reka's fallback only appears after an image fails. */
const frame = computed(() => [
  'relative inline-flex shrink-0 items-center justify-center overflow-hidden align-middle select-none',
  props.shape === 'circle' ? 'rounded-full' : 'rounded-[28%]',
])
const fallback =
  'flex size-full items-center justify-center bg-[hsl(var(--avatar-h)_62%_92%)] font-semibold text-[hsl(var(--avatar-h)_42%_34%)] dark:bg-[hsl(var(--avatar-h)_24%_24%)] dark:text-[hsl(var(--avatar-h)_62%_80%)]'
const hue = computed(() => {
  let hash = 0
  for (const char of props.name) hash = (hash * 31 + (char.codePointAt(0) ?? 0)) % 360
  return hash
})
</script>

<template>
  <AvatarRoot
    v-if="src"
    :class="frame"
    :style="{ width: `${size}px`, height: `${size}px`, '--avatar-h': hue }"
  >
    <AvatarImage :src="src" :alt="name" class="size-full object-cover" />
    <AvatarFallback :delay-ms="300" :class="fallback" :style="{ fontSize: `${Math.round(size * 0.42)}px` }">
      {{ initial }}
    </AvatarFallback>
  </AvatarRoot>
  <span
    v-else
    role="img"
    :aria-label="name"
    :class="[frame, fallback]"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      '--avatar-h': hue,
      fontSize: `${Math.round(size * 0.42)}px`,
    }"
  >
    {{ initial }}
  </span>
</template>
