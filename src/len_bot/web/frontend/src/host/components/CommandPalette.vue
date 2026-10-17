<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { mdiMagnify, mdiFileDocumentOutline, mdiForumOutline, mdiLightningBolt } from '@mdi/js'
import { host } from '../store.js'
import { sceneName } from '../../api.js'
import { filterCommands, pageCommands } from '../commands.js'
import { setThemeMode, themeModeOptions } from '../../composables/useThemeMode.js'
import { openRestart } from '../restart.js'

const props = defineProps({ scene: { type: String, default: '' } })
const open = defineModel({ type: Boolean, default: false })
const router = useRouter()
const query = ref(''), cursor = ref(0), input = ref(null)
const pages = pageCommands()
const kindIcon = { 页面: mdiFileDocumentOutline, 群聊: mdiForumOutline, 操作: mdiLightningBolt }

const commands = computed(() => {
  const scenes = (host.state?.scenes || []).map(item => ({ id: `scene:${item.scene}`, kind: '群聊', title: sceneName(item.scene),
    hint: item.persona?.name || '', keywords: item.scene, to: { name: 'host-scenes', query: { scene: item.scene } } }))
  const actions = [
    ...themeModeOptions.map(([value, label]) => ({ id: `theme:${value}`, kind: '操作', title: `外观：${label}`, keywords: 'theme dark light zhuti waiguan wg shense ss qianse qs',
      run: () => setThemeMode(value) })),
    { id: 'restart', kind: '操作', title: '重启 LenBot', keywords: 'restart chongqi cq', run: openRestart },
  ]
  // Pages that work per scene keep the scene the user is looking at.
  const scoped = pages.map(item => props.scene && item.to.name !== 'host-system'
    ? { ...item, to: { ...item.to, query: { ...(item.to.query || {}), scene: props.scene } } } : item)
  return [...scoped, ...scenes, ...actions]
})
const results = computed(() => filterCommands(commands.value, query.value))
watch(results, () => { cursor.value = 0 })
watch(open, value => { if (value) { query.value = ''; nextTick(() => input.value?.focus()) } })

function choose(item) {
  if (!item) return
  open.value = false
  if (item.run) item.run()
  else router.push(item.to)
}
function onKey(event) {
  const n = results.value.length
  if (event.key === 'ArrowDown') { event.preventDefault(); cursor.value = n ? (cursor.value + 1) % n : 0 }
  else if (event.key === 'ArrowUp') { event.preventDefault(); cursor.value = n ? (cursor.value - 1 + n) % n : 0 }
  else if (event.key === 'Enter') { event.preventDefault(); choose(results.value[cursor.value]) }
}
function onGlobalKey(event) {
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    open.value = !open.value
  }
}
onMounted(() => window.addEventListener('keydown', onGlobalKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))
</script>

<template>
  <v-dialog v-model="open" max-width="560" location="top" class="palette-dialog" scrim="rgba(0,0,0,.32)">
    <div class="palette" role="dialog" aria-label="快速跳转">
      <label class="palette-search">
        <v-icon :icon="mdiMagnify" size="20" />
        <input ref="input" v-model="query" placeholder="跳转到页面、群聊或执行操作…" aria-label="搜索"
          role="combobox" aria-controls="palette-list" :aria-activedescendant="results[cursor] ? `pal-${cursor}` : undefined" @keydown="onKey" />
        <kbd>Esc</kbd>
      </label>
      <ul id="palette-list" class="palette-list" role="listbox">
        <li v-for="(item, index) in results" :id="`pal-${index}`" :key="item.id" role="option" :aria-selected="index === cursor"
          :class="{ active: index === cursor }" @mouseenter="cursor = index" @click="choose(item)">
          <v-icon :icon="kindIcon[item.kind]" size="18" />
          <span class="palette-title">{{ item.title }}</span>
          <span class="palette-hint">{{ item.hint }}</span>
          <span class="palette-kind">{{ item.kind }}</span>
        </li>
        <li v-if="!results.length" class="palette-empty">没有找到“{{ query }}”</li>
      </ul>
      <footer class="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>Enter</kbd> 打开</span><span><kbd>Ctrl</kbd><kbd>K</kbd> 随时唤起</span></footer>
    </div>
  </v-dialog>
</template>

<style scoped>
.palette-dialog :deep(.v-overlay__content){margin-top:12vh !important}
.palette{background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow-float);overflow:hidden}
.palette-search{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line);color:var(--muted)}
.palette-search input{flex:1;border:0;outline:0;background:transparent;color:var(--ink);font:inherit;font-size:15px}
.palette-list{list-style:none;margin:0;padding:6px;max-height:min(420px,60vh);overflow:auto}
.palette-list li{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:9px;cursor:pointer;color:var(--muted)}
.palette-list li.active{background:var(--hover);color:var(--ink)}
.palette-title{color:var(--ink);flex:none}
.palette-hint{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.palette-kind{font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid var(--line)}
.palette-empty{justify-content:center;cursor:default !important}
.palette-foot{display:flex;gap:16px;padding:8px 14px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
kbd{font:inherit;font-size:11px;padding:0 5px;margin-right:3px;border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;background:var(--fill)}
</style>
