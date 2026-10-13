<script setup>
import { computed, ref, watch } from 'vue'
import { avatarTints } from '../../../styles/theme.js'
import { roleAvatarUrl, roleLabel } from './roles.js'

const props = defineProps({ role: { type: Object, required: true }, size: { type: Number, default: 40 }, version: { type: Number, default: 0 } })
const failed = ref(false)
watch(() => [props.role.key, props.role.avatar, props.version], () => { failed.value = false })
const name = computed(() => roleLabel(props.role))
const tint = computed(() => avatarTints[[...name.value].reduce((sum, char) => sum + char.codePointAt(0), 0) % avatarTints.length])
</script>

<template>
  <img v-if="role.avatar && !failed" class="role-avatar" :src="roleAvatarUrl(role, version)" alt="" :width="size" :height="size"
    :style="{ width: `${size}px`, height: `${size}px` }" @error="failed = true">
  <span v-else class="role-avatar letter" aria-hidden="true"
    :style="{ width: `${size}px`, height: `${size}px`, background: tint[0], color: tint[1], fontSize: `${Math.round(size * 0.42)}px` }">
    {{ [...name][0] }}</span>
</template>

<style scoped>
.role-avatar{flex:none;border-radius:50%;object-fit:cover;background:var(--fill)}
.letter{display:inline-grid;place-items:center;font-weight:700;line-height:1}
</style>
