<script setup>
import { computed, inject } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { sceneTarget, showsScene, useCurrentScene } from '../../composables/useCurrentScene.js'
import { host } from '../store.js'
import SceneSwitch from './SceneSwitch.vue'
defineProps({ title: { type: String, default: '' }, description: { type: String, default: '' }, wide: Boolean })
const route = useRoute(), router = useRouter()
const { scene } = useCurrentScene()
// Inside a tab of the group workbench the tab already names the page.
const embedded = inject('embedded-page', false)
const switching = computed(() => showsScene(route) && route.meta.sceneSwitch !== false && Boolean(scene.value)
  && (host.state?.scenes.length || 0) > 1)
</script>
<template>
  <div class="host-page" :class="{ wide }">
    <header v-if="(title && !embedded) || $slots.actions" class="host-page-header">
      <div v-if="!embedded" class="host-page-title">
        <div class="title-row">
          <h1>{{ title }}</h1>
          <SceneSwitch v-if="switching" :model-value="scene" :mode="route.meta.sceneMode || 'scene'"
            @update:model-value="value => router.push(sceneTarget(route, value))" />
        </div>
        <p v-if="description" class="muted">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="host-page-actions"><slot name="actions" /></div>
    </header>
    <slot />
  </div>
</template>
<style scoped>
.host-page{width:100%;max-width:1240px;margin-inline:auto;display:grid;gap:var(--sp-4);min-width:0;align-content:start}
.host-page.wide{max-width:1600px}
.host-page-header{display:flex;justify-content:space-between;align-items:center;gap:var(--sp-4);flex-wrap:wrap;margin-bottom:var(--sp-2)}
.host-page-title{min-width:0}
.title-row{display:flex;align-items:center;gap:var(--sp-4);flex-wrap:wrap;min-width:0}
.host-page-title p{margin:var(--sp-1) 0 0}
.host-page-actions:only-child{margin-left:auto}
.host-page-actions{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
</style>
