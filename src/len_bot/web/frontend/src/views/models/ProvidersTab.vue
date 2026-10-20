<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { Plus, Server } from '@lucide/vue'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import { confirm } from '../../ui/confirm'
import ProviderEditor from './ProviderEditor.vue'
import { useForm } from './form'
import { useProtocolTitle } from './protocols'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const form = useForm()
const wide = useMediaQuery('(min-width: 1024px)')

const rows = computed(() => form.draft.value?.providers ?? [])
const selected = computed(() => {
  const id = typeof route.query.item === 'string' ? route.query.item : null
  return rows.value.find((row) => row.id === id) ?? (wide.value ? rows.value[0] : undefined)
})
const select = (id: string | null) => void router.replace({ query: { ...route.query, item: id ?? undefined } })
// A provider removed or renamed away from under the address falls back to the first one.
watch(
  () => [route.query.item, rows.value.length],
  () => {
    if (typeof route.query.item === 'string' && !rows.value.some((row) => row.id === route.query.item)) select(null)
  },
)

const protocolTitle = useProtocolTitle()
const apiTitle = (api: string) => {
  const protocol = form.protocol(api)
  return protocol ? protocolTitle(protocol) : api
}
const problemsOf = (id: string) => form.problems.value.filter((item) => item.provider === id)

function add() {
  select(form.addProvider())
}
async function remove(id: string) {
  const users = form.usedBy(id)
  const confirmed = await confirm({
    title: t('models.providers.remove', { name: form.nameOf(id) }),
    message: users.length ? t('models.providers.removeUsed', { names: users.join(t('personas.separator')) }) : undefined,
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (!confirmed) return
  form.removeProvider(id)
  select(null)
}
</script>

<template>
  <div class="grid min-w-0 gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
    <section v-if="wide || !selected" class="flex min-w-0 flex-col gap-3">
      <div class="flex items-center justify-between gap-2">
        <h2 class="text-base font-semibold">{{ t('models.providers.title') }}</h2>
        <Button size="sm" :icon="Plus" @click="add">{{ t('models.providers.add') }}</Button>
      </div>
      <EmptyState v-if="!rows.length" :icon="Server" :title="t('models.providers.empty')" compact />
      <ul v-else class="flex list-none flex-col gap-1">
        <li v-for="row in rows" :key="row.id">
          <button
            type="button"
            class="flex w-full min-w-0 cursor-pointer flex-col gap-1 rounded-md px-3 py-2 text-left transition-colors hover:bg-hover focus-visible:focus-ring"
            :class="selected?.id === row.id && 'bg-selected'"
            :aria-current="selected?.id === row.id || undefined"
            @click="select(row.id)"
          >
            <span class="flex min-w-0 items-center gap-2">
              <span class="min-w-0 flex-1 truncate text-sm font-medium text-ink">{{ row.alias || t('models.providers.unnamed') }}</span>
              <Badge v-if="problemsOf(row.id).length" tone="warning" dot>{{ t('models.providers.needsFix') }}</Badge>
            </span>
            <span class="truncate text-xs text-muted">
              {{ [apiTitle(row.api), ...form.usedBy(row.id)].join(' · ') }}
            </span>
          </button>
        </li>
      </ul>
    </section>

    <ProviderEditor
      v-if="selected"
      :id="selected.id"
      :key="selected.id"
      :wide="wide"
      @back="select(null)"
      @remove="remove(selected.id)"
    />
  </div>
</template>
