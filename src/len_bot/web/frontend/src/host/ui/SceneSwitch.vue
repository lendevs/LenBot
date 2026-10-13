<script setup>
import { computed, ref } from 'vue'
import { mdiCheck, mdiChevronDown, mdiMagnify } from '@mdi/js'
import { sceneName, sceneSubtitle } from '../../api.js'
import { host } from '../store.js'
import SceneAvatar from './SceneAvatar.vue'
const props = defineProps({ modelValue: { type: String, required: true }, mode: { type: String, default: 'scene' } })
const emit = defineEmits(['update:modelValue'])
const search = ref('')
const scenes = computed(() => host.state?.scenes || [])
const current = computed(() => scenes.value.find(item => item.scene === props.modelValue))
const roles = computed(() => {
  const groups = new Map()
  for (const item of scenes.value) {
    if (!groups.has(item.persona_path)) groups.set(item.persona_path, { path: item.persona_path, name: item.persona.name, scenes: [] })
    groups.get(item.persona_path).scenes.push(item.scene)
  }
  return [...groups.values()]
})
const role = computed(() => roles.value.find(item => item.path === current.value?.persona_path))
const visible = computed(() => props.mode !== 'role' || roles.value.length > 1)
const shown = computed(() => {
  const words = search.value.trim().toLowerCase()
  return words ? scenes.value.filter(item => `${sceneName(item.scene)} ${item.scene}`.toLowerCase().includes(words)) : scenes.value
})
function pickRole(item) {
  if (!item.scenes.includes(props.modelValue)) emit('update:modelValue', item.scenes[0])
}
</script>
<template>
  <v-menu v-if="visible" location="bottom start" max-height="460" @update:model-value="value => { if (!value) search = '' }">
    <template #activator="{ props: menu, isActive }">
      <button v-bind="menu" type="button" class="switch-button" :class="{ open: isActive }" :aria-label="mode === 'role' ? '选择角色' : '选择群聊'">
        <template v-if="mode === 'role'">
          <span class="role-mark" aria-hidden="true">{{ [...(role?.name || '?')][0] }}</span>
          <strong>{{ role?.name }}</strong><span class="muted small">{{ role?.scenes.length }} 个群</span>
        </template>
        <template v-else>
          <SceneAvatar :scene="modelValue" :size="24" /><strong>{{ sceneName(modelValue) }}</strong>
        </template>
        <v-icon :icon="mdiChevronDown" size="18" class="chevron" />
      </button>
    </template>
    <v-card class="switch-menu" min-width="300" max-width="420">
      <template v-if="mode === 'role'">
        <button v-for="item in roles" :key="item.path" type="button" class="switch-item" :class="{ on: item.path === role?.path }" @click="pickRole(item)">
          <span class="role-mark" aria-hidden="true">{{ [...item.name][0] }}</span>
          <span class="item-text"><strong>{{ item.name }}</strong><span class="muted small">{{ item.scenes.map(sceneName).join('、') }}</span></span>
          <v-icon v-if="item.path === role?.path" :icon="mdiCheck" size="18" class="check" />
        </button>
      </template>
      <template v-else>
        <div v-if="scenes.length > 8" class="switch-search" @click.stop>
          <v-text-field v-model="search" :prepend-inner-icon="mdiMagnify" placeholder="搜索群名或群号" density="compact" autofocus />
        </div>
        <button v-for="item in shown" :key="item.scene" type="button" class="switch-item" :class="{ on: item.scene === modelValue }"
          @click="emit('update:modelValue', item.scene)">
          <SceneAvatar :scene="item.scene" :size="28" />
          <span class="item-text"><strong>{{ sceneName(item.scene) }}</strong><span v-if="sceneSubtitle(item.scene)" class="muted small">{{ sceneSubtitle(item.scene) }}</span></span>
          <v-icon v-if="item.scene === modelValue" :icon="mdiCheck" size="18" class="check" />
        </button>
        <p v-if="!shown.length" class="muted small empty">没有匹配的群</p>
      </template>
    </v-card>
  </v-menu>
</template>
<style scoped>
.switch-button{display:inline-flex;align-items:center;gap:var(--sp-2);max-width:min(420px,100%);height:36px;padding:0 var(--sp-2) 0 6px;border:1px solid var(--line);border-radius:999px;
  background:var(--surface);color:inherit;font:inherit;cursor:pointer;transition:border-color var(--dur-1),box-shadow var(--dur-2) var(--ease-out)}
.switch-button:hover{border-color:var(--line-strong)}
.switch-button.open{border-color:var(--primary);box-shadow:0 0 0 3px rgb(180 71 106 / 12%)}
.switch-button strong{font-weight:600;font-size:var(--fs-md);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.switch-button .small{white-space:nowrap}
.chevron{color:var(--muted);flex:none;transition:transform var(--dur-2) var(--ease-out)}
.switch-button.open .chevron{transform:rotate(180deg)}
.role-mark{display:inline-grid;place-items:center;flex:none;width:24px;height:24px;border-radius:50%;background:var(--brand-soft);color:var(--primary);font-size:var(--fs-sm);font-weight:700}
.switch-item .role-mark{width:28px;height:28px}
.switch-menu{display:grid;padding:var(--sp-2)}
.switch-search{padding:0 0 var(--sp-2)}
.switch-item{display:flex;align-items:center;gap:var(--sp-3);padding:6px var(--sp-2);border:0;border-radius:var(--radius);background:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.switch-item:hover{background:var(--hover)}
.switch-item.on{background:var(--selected)}
.item-text{display:grid;flex:1;min-width:0;line-height:1.35}
.item-text strong{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item-text span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.check{color:var(--primary);flex:none}
.empty{margin:0;padding:var(--sp-2)}
</style>
