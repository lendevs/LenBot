<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { mdiArrowLeft, mdiContentCopy, mdiDotsHorizontal, mdiDownload } from '@mdi/js'
import { sceneName } from '../../../api.js'
import { useAction } from '../../../composables/useResource.js'
import { useUnsavedChanges } from '../../../composables/useUnsavedChanges.js'
import { host, notify, readHostState } from '../../store.js'
import ErrorNote from '../../ui/ErrorNote.vue'
import FormDialog from '../../ui/FormDialog.vue'
import PageTabs from '../../ui/PageTabs.vue'
import SceneAvatar from '../../ui/SceneAvatar.vue'
import ProfileTab from './ProfileTab.vue'
import KnowledgeTab from './KnowledgeTab.vue'
import StickersTab from './StickersTab.vue'
import PackageTab from './PackageTab.vue'
import RoleAvatar from './RoleAvatar.vue'
import RoleScenes from './RoleScenes.vue'
import { applyRole, downloadRole, roleLabel, roleUsage } from './roles.js'

const props = defineProps({ role: { type: Object, required: true } })
const emit = defineEmits(['changed', 'create'])
const route = useRoute()
const tabs = computed(() => [['profile', '设定'], ['knowledge', '资料'], ['stickers', '表情'],
  { value: 'scenes', title: '群', count: props.role.scenes.length || undefined }, ['files', '文件']])
const tab = computed(() => tabs.value.some(item => (item.value || item[0]) === route.query.tab) ? route.query.tab : 'profile')
const dirty = reactive({})
useUnsavedChanges(computed(() => Object.values(dirty).some(Boolean)), {
  onDiscard: () => { for (const key of Object.keys(dirty)) dirty[key] = false } })
const avatarVersion = ref(0)
const trialScene = computed(() => props.role.scenes[0] || host.state?.scenes[0]?.scene || null)
const blocked = computed(() => props.role.error ? '角色文件读不了' : props.role.duplicate_id ? `ID ${props.role.id} 和别的角色重复，先改掉再用` : '')

// Switching waits for each scene's current reply; scenes still waiting stay listed here.
const switching = useAction(), pending = ref([])
watch(() => props.role.key, () => { pending.value = [] })
async function use(scenes) {
  const result = await switching.run(() => applyRole(props.role, scenes))
  if (!result) return false
  pending.value = result.results.filter(item => item.status === 'pending').map(item => item.scene)
  notify(result.message)
  readHostState()
  emit('changed')
  return true
}

const choosing = ref(false), chosen = ref([])
const choices = computed(() => (host.state?.scenes || []).filter(item => item.persona_path !== props.role.path))
function openChooser() {
  chosen.value = []
  switching.error.value = null
  choosing.value = true
}
async function applyChosen() {
  if (await use(chosen.value)) choosing.value = false
}
const exporting = useAction()
const back = computed(() => ({ name: route.name, query: {} }))
</script>

<template>
  <div class="role-detail">
    <RouterLink :to="back" class="back"><v-icon :icon="mdiArrowLeft" size="16" />全部角色</RouterLink>

    <header class="detail-head">
      <RoleAvatar :role="role" :size="56" :version="avatarVersion" />
      <div class="head-text">
        <div class="head-title">
          <h1>{{ roleLabel(role) }}</h1>
          <span v-if="role.id" class="pill mono">{{ role.id }}</span>
        </div>
        <p v-if="role.brief" class="brief">{{ role.brief }}</p>
        <div class="usage">
          <span v-if="role.scenes.length" class="stack" aria-hidden="true">
            <SceneAvatar v-for="scene in role.scenes.slice(0, 5)" :key="scene" :scene="scene" :size="22" class="stack-avatar" /></span>
          <span :title="role.scenes.map(sceneName).join('、')">{{ roleUsage(role) }}</span>
        </div>
      </div>
      <div class="head-actions">
        <v-tooltip :text="blocked" :disabled="!blocked" location="bottom">
          <template #activator="{ props: tip }">
            <span v-bind="tip"><v-btn color="primary" :disabled="Boolean(blocked) || !choices.length" @click="openChooser">用到群…</v-btn></span>
          </template>
        </v-tooltip>
        <v-menu location="bottom end">
          <template #activator="{ props: menu }"><v-btn v-bind="menu" :icon="mdiDotsHorizontal" variant="outlined" size="36" aria-label="更多操作" /></template>
          <v-list density="compact" min-width="160">
            <v-list-item :prepend-icon="mdiContentCopy" title="复制" :disabled="Boolean(role.error)" @click="emit('create', { kind: 'copy', source: role })" />
            <v-list-item :prepend-icon="mdiDownload" title="导出 ZIP" :disabled="Boolean(role.error)" @click="exporting.run(() => downloadRole(role))" />
          </v-list>
        </v-menu>
      </div>
    </header>

    <ErrorNote v-if="role.error" title="角色文件读不了" :error="role.error" />
    <v-alert v-else-if="role.duplicate_id" type="warning">还有别的角色也用 ID {{ role.id }}，在文件里改掉其中一个再用到群。</v-alert>
    <ErrorNote v-if="exporting.error.value" title="没有导出成功" :error="exporting.error.value" />
    <ErrorNote v-if="switching.error.value && !choosing" title="没有换成" :error="switching.error.value" />

    <PageTabs :tabs="tabs" :model-value="tab" :clear="[]" label="角色内容" />
    <template v-if="!role.error">
      <ProfileTab v-if="tab === 'profile'" :key="`p${role.key}`" :persona="role.key" :trial-scene="trialScene"
        @dirty="value => dirty.profile = value" @avatar="avatarVersion++; emit('changed')" @saved="emit('changed')" />
      <KnowledgeTab v-else-if="tab === 'knowledge'" :key="`k${role.key}`" :persona="role.key" @dirty="value => dirty.knowledge = value" />
      <StickersTab v-else-if="tab === 'stickers'" :key="`s${role.key}`" :persona="role.key" @dirty="value => dirty.stickers = value" />
      <RoleScenes v-else-if="tab === 'scenes'" :role="role" :busy="switching.busy.value" :pending="pending" @use="use" />
      <PackageTab v-else :key="`f${role.key}`" :persona="role.key" @dirty="value => dirty.files = value" @saved="emit('changed')" />
    </template>
  </div>

  <FormDialog v-model="choosing" :title="`把哪些群换成 ${roleLabel(role)}`" :busy="switching.busy.value">
    <div class="choice-list">
      <label v-for="item in choices" :key="item.scene" class="choice">
        <v-checkbox-btn :model-value="chosen.includes(item.scene)" density="compact" color="primary" class="choice-check"
          @update:model-value="on => chosen = on ? [...chosen, item.scene] : chosen.filter(scene => scene !== item.scene)" />
        <SceneAvatar :scene="item.scene" :size="28" />
        <span class="choice-text"><strong>{{ sceneName(item.scene) }}</strong><span class="muted small">现在是 {{ item.persona.name }}</span></span>
      </label>
    </div>
    <ErrorNote v-if="switching.error.value" title="没有换成" :error="switching.error.value" />
    <template #actions>
      <v-btn color="primary" :loading="switching.busy.value" :disabled="!chosen.length" @click="applyChosen">换成 {{ roleLabel(role) }}</v-btn>
    </template>
  </FormDialog>
</template>

<style scoped>
.role-detail{display:grid;gap:var(--sp-4);min-width:0}
.back{display:inline-flex;align-items:center;gap:4px;width:max-content;color:var(--muted);font-size:var(--fs-sm)}
.back:hover{color:var(--ink);text-decoration:none}
.detail-head{display:flex;align-items:flex-start;gap:var(--sp-4);min-width:0}
.head-text{display:grid;gap:6px;flex:1;min-width:0}
.head-title{display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap}
.head-title h1{font-size:var(--fs-2xl)}
.pill{padding:0 8px;border-radius:999px;background:var(--fill);color:var(--muted);font-size:var(--fs-xs);font-weight:600;line-height:22px}
.brief{margin:0;color:var(--muted);max-width:880px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.usage{display:flex;align-items:center;gap:var(--sp-2);font-size:var(--fs-sm);color:var(--muted);min-width:0}
.usage > span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stack{display:inline-flex;flex:none}
.stack-avatar{box-shadow:0 0 0 2px var(--page);border-radius:50%}
.stack-avatar + .stack-avatar{margin-left:-6px}
.head-actions{display:flex;align-items:center;gap:var(--sp-2);flex:none}
.choice-list{display:grid;gap:2px;max-height:420px;overflow:auto}
.choice{display:flex;align-items:center;gap:var(--sp-3);padding:6px var(--sp-2);border-radius:var(--radius);cursor:pointer}
.choice:hover{background:var(--fill)}
.choice-check{flex:none}
.choice-text{display:grid;min-width:0;line-height:1.35}
.choice-text strong{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:700px){
  .detail-head{flex-wrap:wrap}
  .head-actions{width:100%}
}
</style>
