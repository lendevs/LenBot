<script setup>
import { computed } from 'vue'
import { mdiAlertCircleOutline, mdiChevronDown, mdiContentCopy, mdiDotsHorizontal, mdiDownload, mdiPlus, mdiTrashCanOutline, mdiZipBoxOutline } from '@mdi/js'
import { api } from '../../../api.js'
import { useAction } from '../../../composables/useResource.js'
import { confirm } from '../../../composables/useConfirm.js'
import { notify } from '../../store.js'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import SceneAvatar from '../../ui/SceneAvatar.vue'
import RoleAvatar from './RoleAvatar.vue'
import { downloadRole, roleBase, roleLabel, roleUsage } from './roles.js'

const props = defineProps({ roles: { type: Array, required: true } })
const emit = defineEmits(['changed', 'open', 'create'])
const inUse = computed(() => props.roles.filter(role => role.scenes.length).length)

const removing = useAction()
async function remove(role) {
  if (!await confirm({ title: `删除角色 ${roleLabel(role)}？`, text: '文件夹移到 .runtime/deleted-personas，各群的记忆保留。',
    confirmLabel: '删除', danger: true })) return
  if (await removing.run(() => api(roleBase(role.key), { method: 'DELETE' }))) {
    notify('已删除')
    emit('changed')
  }
}
const exporting = useAction()
const exportRole = role => exporting.run(() => downloadRole(role))
</script>

<template>
  <div class="library">
    <div class="toolbar">
      <span class="muted">{{ roles.length }} 个角色<template v-if="roles.length"> · {{ inUse }} 个在用</template></span>
      <v-menu location="bottom end">
        <template #activator="{ props: menu }">
          <v-btn v-bind="menu" class="ml-auto" color="primary" :prepend-icon="mdiPlus" :append-icon="mdiChevronDown">新建角色</v-btn>
        </template>
        <v-list density="compact" min-width="200">
          <v-list-item :prepend-icon="mdiPlus" title="空白角色" @click="emit('create', { kind: 'create' })" />
          <v-list-item :prepend-icon="mdiZipBoxOutline" title="导入 ZIP 文件" @click="emit('create', { kind: 'import' })" />
        </v-list>
      </v-menu>
    </div>
    <ErrorNote v-if="removing.error.value" title="没有删除成功" :error="removing.error.value" />
    <ErrorNote v-if="exporting.error.value" title="没有导出成功" :error="exporting.error.value" />

    <div v-if="roles.length" class="role-grid">
      <article v-for="role in roles" :key="role.key" class="role-card" :class="{ idle: !role.scenes.length }" tabindex="0"
        :aria-label="roleLabel(role)" @click="emit('open', role.key)" @keydown.enter.self="emit('open', role.key)">
        <div class="card-head">
          <RoleAvatar :role="role" :size="44" />
          <div class="card-title">
            <strong>{{ roleLabel(role) }}</strong>
            <span class="muted small mono">{{ role.key }}</span>
          </div>
          <v-menu location="bottom end">
            <template #activator="{ props: menu }">
              <v-btn v-bind="menu" :icon="mdiDotsHorizontal" variant="text" size="32" aria-label="更多操作" @click.stop @keydown.enter.stop />
            </template>
            <v-list density="compact" min-width="160">
              <v-list-item :prepend-icon="mdiContentCopy" title="复制" :disabled="Boolean(role.error)" @click="emit('create', { kind: 'copy', source: role })" />
              <v-list-item :prepend-icon="mdiDownload" title="导出 ZIP" :disabled="Boolean(role.error)" @click="exportRole(role)" />
              <v-list-item :prepend-icon="mdiTrashCanOutline" title="删除" base-color="error"
                :disabled="Boolean(role.scenes.length || role.running_scenes.length)" @click="remove(role)" />
            </v-list>
          </v-menu>
        </div>
        <p class="card-brief">{{ role.brief || '还没有写简介' }}</p>
        <div class="card-foot">
          <span v-if="role.error || role.duplicate_id" class="problem">
            <v-icon :icon="mdiAlertCircleOutline" size="15" />{{ role.error ? '角色文件读不了' : `ID ${role.id} 和别的角色重复` }}</span>
          <span v-else-if="role.scenes.length" class="scenes">
            <span class="stack" aria-hidden="true"><SceneAvatar v-for="scene in role.scenes.slice(0, 3)" :key="scene" :scene="scene" :size="20" class="stack-avatar" /></span>
            {{ roleUsage(role) }}</span>
          <span v-else>没有群在用</span>
        </div>
      </article>
    </div>
    <EmptyState v-else text="还没有角色"><v-btn color="primary" @click="emit('create', { kind: 'create' })">新建角色</v-btn></EmptyState>
  </div>

</template>

<style scoped>
.library{display:grid;gap:var(--sp-4);min-width:0}
.toolbar{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
.role-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:var(--sp-4)}
.role-card{display:grid;grid-template-rows:auto 1fr auto;gap:var(--sp-3);padding:var(--sp-4) var(--sp-3) var(--sp-4) var(--sp-5);border:1px solid var(--line);border-radius:var(--radius-lg);
  background:var(--surface);cursor:pointer;transition:border-color var(--dur-2),box-shadow var(--dur-2) var(--ease-out),transform var(--dur-2) var(--ease-out)}
.role-card:hover,.role-card:focus-visible{border-color:var(--line-strong);box-shadow:var(--shadow-hover);transform:translateY(-1px);outline:none}
.role-card:focus-visible{box-shadow:0 0 0 2px var(--primary)}
.card-head{display:flex;align-items:center;gap:var(--sp-3);min-width:0}
.card-title{display:grid;flex:1;min-width:0;line-height:1.35}
.card-title strong{font-size:var(--fs-lg);font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-brief{align-self:start;margin:0;padding-right:var(--sp-2);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:3.2em;color:var(--muted);font-size:var(--fs-sm)}
.card-foot{display:flex;align-items:center;min-height:32px;margin-right:var(--sp-2);padding-top:var(--sp-3);border-top:1px solid var(--line);font-size:var(--fs-sm);color:var(--muted)}
.card-foot > span{display:inline-flex;align-items:center;gap:6px;min-width:0}
.card-foot .problem{color:var(--warning)}
.scenes{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stack{display:inline-flex;flex:none}
.stack-avatar{box-shadow:0 0 0 2px var(--surface);border-radius:50%}
.stack-avatar + .stack-avatar{margin-left:-6px}
.role-card.idle .card-title strong{color:var(--muted)}
</style>
