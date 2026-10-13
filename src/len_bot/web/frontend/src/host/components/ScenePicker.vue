<script setup>
import { computed, ref } from 'vue'
import { mdiCheck, mdiChevronDown, mdiMagnify } from '@mdi/js'
import { sceneName, sceneSubtitle } from '../../api.js'
import SceneAvatar from '../ui/SceneAvatar.vue'

const props = defineProps({
  choices: { type: Array, required: true },
  single: Boolean,
  id: { type: String, default: undefined },
})
const model = defineModel({ required: true })
const open = ref(false), search = ref('')
const picked = computed(() => props.single ? (model.value ? [model.value] : []) : model.value)
const shown = computed(() => {
  const words = search.value.trim().toLowerCase()
  return words ? props.choices.filter(scene => `${sceneName(scene)} ${scene}`.toLowerCase().includes(words)) : props.choices
})
const summary = computed(() => {
  const names = picked.value.map(sceneName)
  return names.length > 2 ? `${names.slice(0, 2).join('、')} 等 ${names.length} 个群` : names.join('、')
})
function toggle(scene) {
  if (props.single) {
    model.value = scene
    open.value = false
  } else {
    model.value = picked.value.includes(scene) ? picked.value.filter(item => item !== scene) : [...picked.value, scene]
  }
}
const pickAll = () => { model.value = [...new Set([...picked.value, ...shown.value])] }
const clear = () => { model.value = props.single ? null : [] }
</script>

<template>
  <v-menu v-model="open" :close-on-content-click="false" location="bottom start" max-height="420" @update:model-value="value => { if (!value) search = '' }">
    <template #activator="{ props: menu }">
      <button v-bind="menu" :id="id" type="button" class="scene-picker" :class="{ open }">
        <span v-if="picked.length" class="stack" aria-hidden="true">
          <SceneAvatar v-for="scene in picked.slice(0, 4)" :key="scene" :scene="scene" :size="24" class="stack-avatar" />
        </span>
        <span class="summary" :class="{ muted: !picked.length }">{{ picked.length ? summary : (single ? '选择一个群' : '选择群') }}</span>
        <v-icon :icon="mdiChevronDown" size="20" class="chevron" />
      </button>
    </template>
    <v-card class="scene-menu" min-width="320">
      <div v-if="choices.length > 6" class="menu-search">
        <v-text-field v-model="search" :prepend-inner-icon="mdiMagnify" placeholder="搜索群名或群号" density="compact" autofocus />
      </div>
      <div v-if="!single" class="menu-head">
        <span class="muted small">已选 {{ picked.length }} / {{ choices.length }}</span>
        <v-btn size="small" variant="text" :disabled="!shown.length" @click="pickAll">全选</v-btn>
        <v-btn size="small" variant="text" :disabled="!picked.length" @click="clear">清空</v-btn>
      </div>
      <div class="menu-list" role="listbox" :aria-multiselectable="!single">
        <button v-for="scene in shown" :key="scene" type="button" class="menu-item" role="option"
          :aria-selected="picked.includes(scene)" :class="{ on: picked.includes(scene) }" @click="toggle(scene)">
          <SceneAvatar :scene="scene" :size="28" />
          <span class="item-text"><strong>{{ sceneName(scene) }}</strong><span v-if="sceneSubtitle(scene)" class="muted small">{{ sceneSubtitle(scene) }}</span></span>
          <span class="check"><v-icon v-if="picked.includes(scene)" :icon="mdiCheck" size="16" /></span>
        </button>
        <p v-if="!shown.length" class="muted small empty">{{ choices.length ? '没有匹配的群' : '还没有配置群' }}</p>
      </div>
    </v-card>
  </v-menu>
</template>

<style scoped>
.scene-picker{display:flex;align-items:center;gap:var(--sp-2);width:100%;min-height:40px;padding:6px var(--sp-2) 6px var(--sp-3);border:0;border-radius:var(--radius);
  background:var(--fill);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:background-color var(--dur-1),box-shadow var(--dur-2) var(--ease-out)}
.scene-picker:hover{background:var(--hover)}
.scene-picker.open{background:var(--surface);box-shadow:0 0 0 1.5px var(--primary),0 0 0 5px rgb(180 71 106 / 12%)}
.stack{display:flex;flex:none}
.stack-avatar{box-shadow:0 0 0 2px var(--fill)}
.scene-picker:hover .stack-avatar{box-shadow:0 0 0 2px var(--hover)}
.stack-avatar+.stack-avatar{margin-left:-6px}
.summary{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chevron{color:var(--muted);transition:transform var(--dur-2) var(--ease-out)}
.scene-picker.open .chevron{transform:rotate(180deg)}
.scene-menu{display:grid;padding:var(--sp-2) 0}
.menu-search{padding:0 var(--sp-2) var(--sp-2)}
.menu-head{display:flex;align-items:center;gap:var(--sp-1);padding:0 var(--sp-2) var(--sp-1) var(--sp-4)}
.menu-head span{margin-right:auto}
.menu-list{display:grid;overflow-y:auto;padding:0 var(--sp-2)}
.menu-item{display:flex;align-items:center;gap:var(--sp-3);padding:6px var(--sp-2);border:0;border-radius:var(--radius);background:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.menu-item:hover{background:var(--hover)}
.item-text{display:grid;flex:1;min-width:0;line-height:1.35}
.item-text strong{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.check{display:grid;place-items:center;width:20px;height:20px;flex:none;border-radius:6px;border:1.5px solid var(--line-strong);color:var(--on-primary);transition:background-color var(--dur-1),border-color var(--dur-1)}
.menu-item.on .check{background:var(--primary);border-color:var(--primary)}
.empty{padding:var(--sp-3) var(--sp-2);margin:0}
</style>
