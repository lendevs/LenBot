<script setup>
import { computed } from 'vue'
import { avatarTints } from '../../../styles/theme.js'
const props = defineProps({ name: { type: String, required: true }, size: { type: Number, default: 40 }, muted: Boolean })
const tint = computed(() => avatarTints[[...props.name].reduce((sum, char) => sum + char.codePointAt(0), 0) % avatarTints.length])
</script>
<template>
  <span class="plugin-mark" :class="{ muted }" aria-hidden="true"
    :style="{ width: `${size}px`, height: `${size}px`, background: tint[0], color: tint[1], fontSize: `${Math.round(size * 0.42)}px` }">
    {{ name.slice(0, 1).toUpperCase() }}</span>
</template>
<style scoped>
.plugin-mark{display:inline-grid;place-items:center;flex:none;border-radius:28%;font-weight:700;line-height:1;transition:filter var(--dur-2)}
.plugin-mark.muted{filter:grayscale(1);opacity:.6}
</style>
