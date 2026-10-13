<script setup>
import { computed } from 'vue'
import { sceneName, sceneSubtitle } from '../../../api.js'
import { host } from '../../store.js'
import EmptyState from '../../ui/EmptyState.vue'
import SceneAvatar from '../../ui/SceneAvatar.vue'

const props = defineProps({ role: { type: Object, required: true }, busy: Boolean, pending: { type: Array, default: () => [] } })
const emit = defineEmits(['use'])
const rows = computed(() => (host.state?.scenes || []).map(item => ({
  scene: item.scene, current: item.persona.name, using: item.persona_path === props.role.path,
})))
</script>

<template>
  <div v-if="rows.length" class="scene-grid">
    <div v-for="row in rows" :key="row.scene" class="scene-row" :class="{ on: row.using }">
      <SceneAvatar :scene="row.scene" :size="32" />
      <span class="scene-text">
        <strong>{{ sceneName(row.scene) }}</strong>
        <span class="muted small">{{ [sceneSubtitle(row.scene), row.current].filter(Boolean).join(' · ') }}</span>
      </span>
      <span v-if="row.using" class="using">正在用</span>
      <span v-else-if="pending.includes(row.scene)" class="muted small">等这轮回复结束</span>
      <v-btn v-else size="small" variant="outlined" :disabled="busy || Boolean(role.error) || role.duplicate_id" @click="emit('use', [row.scene])">换成这个角色</v-btn>
    </div>
  </div>
  <EmptyState v-else text="还没有群聊" />
</template>

<style scoped>
.scene-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:var(--sp-2)}
.scene-row{display:flex;align-items:center;gap:var(--sp-3);min-width:0;min-height:56px;padding:var(--sp-2) var(--sp-3);border:1px solid var(--line);border-radius:var(--radius);background:var(--surface)}
.scene-row.on{border-color:color-mix(in srgb,var(--brand) 45%,var(--line))}
.scene-text{display:grid;flex:1;min-width:0;line-height:1.35}
.scene-text strong{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.scene-text span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.using{flex:none;padding:0 8px;border-radius:999px;background:var(--brand-soft);color:var(--primary);font-size:var(--fs-xs);font-weight:600;line-height:22px}
</style>
