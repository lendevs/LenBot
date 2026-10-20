<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowLeft, ChevronDown, FileArchive, Plus, Search, UserRound } from '@lucide/vue'
import { keys } from '../../api/query'
import { personasApi, type PersonaRole } from '../../api/personas'
import { host } from '../../host/store.js'
import { groupLabel } from '../../layouts/shell/scenes'
import Button from '../../ui/Button.vue'
import DropdownMenu from '../../ui/DropdownMenu.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Input from '../../ui/Input.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import CreatePersonaDialog, { type CreateRequest } from './CreatePersonaDialog.vue'
import PersonaCard from './PersonaCard.vue'
import PersonaDetail from './detail/PersonaDetail.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const library = useQuery({ queryKey: keys.personas.all(), queryFn: ({ signal }) => personasApi.library(signal) })
const roles = computed(() => library.data.value?.roles ?? [])
const refresh = () => void client.invalidateQueries({ queryKey: keys.personas.all() })
// A switch from the group command or another page changes which groups use a role.
watch(
  () => (host.state?.scenes ?? []).map((item: { scene: string; persona_path: string }) => `${item.scene}=${item.persona_path}`).join(),
  (now, before) => {
    if (before !== undefined && now !== before) refresh()
  },
)

const key = computed(() => (typeof route.query.persona === 'string' ? route.query.persona : ''))
const opened = computed(() => roles.value.find((role) => role.key === key.value) ?? null)
const open = (value: string | null) =>
  router.push({ name: 'host-persona', query: value === null ? {} : { persona: value } })

const query = ref('')
const shown = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return roles.value
  return roles.value.filter((role) => {
    const text = [role.name, role.key, role.brief, ...role.aliases, ...role.scenes.map(groupLabel)]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return words.every((word) => text.includes(word))
  })
})
const inUse = computed(() => roles.value.filter((role) => role.scenes.length).length)

const request = ref<CreateRequest | null>(null)
const menu = computed(() => [
  { label: t('personas.blank'), icon: Plus, select: () => (request.value = { kind: 'create' }) },
  { label: t('personas.importZip'), icon: FileArchive, select: () => (request.value = { kind: 'import' }) },
])
function created(folder: string) {
  request.value = null
  refresh()
  void open(folder)
}

const removal = useMutation({
  mutationFn: (role: PersonaRole) => personasApi.remove(role.key),
  onSuccess: () => toast.success(t('personas.removed')),
  onError: (error) => toast.error(t('personas.removeFailed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: refresh,
})
async function remove(role: PersonaRole) {
  const sure = await confirm({
    title: t('personas.removeTitle', { name: role.name || role.key }),
    message: t('personas.removeMessage'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) removal.mutate(role)
}
const exporting = useMutation({
  mutationFn: (role: PersonaRole) => personasApi.package(role.key),
  onSuccess: (blob, role) => {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `persona-${role.key}.zip`
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
  onError: (error) => toast.error(t('personas.exportFailed'), { detail: describeError(error, t('ui.error.network')).message }),
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <Skeleton v-if="library.isPending.value" :lines="6" />
    <ErrorNote
      v-else-if="library.isError.value"
      :title="t('personas.readFailed')"
      :error="library.error.value"
      :retry="library.refetch"
    />
    <template v-else-if="key">
      <PersonaDetail
        v-if="opened"
        :key="opened.key"
        :role="opened"
        :exporting="exporting.isPending.value"
        @copy="request = { kind: 'copy', source: opened }"
        @export="exporting.mutate(opened)"
      />
      <EmptyState v-else :icon="UserRound" :title="t('personas.missing')">
        <Button :icon="ArrowLeft" @click="open(null)">{{ t('personas.all') }}</Button>
      </EmptyState>
    </template>
    <template v-else>
      <div class="flex flex-wrap items-center gap-2">
        <Input
          v-model="query"
          type="search"
          size="sm"
          :icon="Search"
          :placeholder="t('personas.search')"
          :aria-label="t('personas.search')"
          clearable
          class="w-full sm:w-64"
        />
        <span class="text-sm text-muted">
          {{ t('personas.count', { n: roles.length }) }}<template v-if="roles.length">
            · {{ t('personas.inUse', { n: inUse }) }}</template
          >
        </span>
        <DropdownMenu :items="menu">
          <Button variant="primary" size="sm" :icon="Plus" class="ml-auto">
            {{ t('personas.create.createTitle') }}<ChevronDown :size="14" aria-hidden="true" />
          </Button>
        </DropdownMenu>
      </div>
      <EmptyState v-if="!roles.length" :icon="UserRound" :title="t('personas.empty')">
        <Button variant="primary" :icon="Plus" @click="request = { kind: 'create' }">
          {{ t('personas.create.createTitle') }}
        </Button>
      </EmptyState>
      <EmptyState v-else-if="!shown.length" :icon="Search" :title="t('common.noResults')" compact />
      <div v-else class="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
        <PersonaCard
          v-for="role in shown"
          :key="role.key"
          :role="role"
          :busy="(removal.isPending.value && removal.variables.value === role) || (exporting.isPending.value && exporting.variables.value === role)"
          @open="open(role.key)"
          @copy="request = { kind: 'copy', source: role }"
          @export="exporting.mutate(role)"
          @remove="remove(role)"
        />
      </div>
    </template>
    <CreatePersonaDialog v-if="request" :request="request" @done="created" @close="request = null" />
  </div>
</template>
