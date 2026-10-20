<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpRight, MessagesSquare, Repeat } from '@lucide/vue'
import type { HostScene } from '../../../api/host'
import type { PersonaRole } from '../../../api/personas'
import { keys } from '../../../api/query'
import { settingsApi } from '../../../api/settings'
import { host, readHostState } from '../../../api/hostStore'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import IconButton from '../../../ui/IconButton.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { groupsTarget } from '../../groups/route'

const props = defineProps<{ role: PersonaRole; blocked: string | null }>()

const { t } = useI18n()
const client = useQueryClient()
const name = computed(() => props.role.name || props.role.key)
const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])
const rows = computed(() =>
  scenes.value.map((item) => ({
    scene: item.scene,
    current: item.persona.name,
    using: item.persona_path === props.role.path && props.role.running_scenes.includes(item.scene),
    // Saved for this role while the group still finishes a reply with the previous one.
    waiting: props.role.scenes.includes(item.scene) && !props.role.running_scenes.includes(item.scene),
  })),
)
const chosen = ref<string[]>([])
watch(
  () => props.role.scenes.join(),
  () => (chosen.value = chosen.value.filter((scene) => !props.role.scenes.includes(scene))),
)
const choosable = computed(() => rows.value.filter((row) => !row.using && !row.waiting).map((row) => row.scene))
function toggle(scene: string, on: boolean) {
  chosen.value = on ? [...chosen.value, scene] : chosen.value.filter((item) => item !== scene)
}

const use = useMutation({
  mutationFn: (targets: string[]) => settingsApi.useRole(props.role.key, targets),
  onSuccess: ({ results }) => {
    const failed = results.filter((item) => item.status === 'failed')
    const pending = results.filter((item) => item.status === 'pending')
    if (failed.length) {
      toast.error(t('personas.detail.scenes.failed', { names: failed.map((item) => groupLabel(item.scene)).join(t('personas.separator')) }), {
        detail: failed.map((item) => `${groupLabel(item.scene)}: ${item.error ?? ''}`).join('\n'),
      })
    }
    if (results.length > failed.length) {
      toast.success(
        pending.length
          ? t('personas.detail.scenes.pending', { names: pending.map((item) => groupLabel(item.scene)).join(t('personas.separator')), name: name.value })
          : t('personas.detail.scenes.done', { name: name.value }),
      )
    }
    if (results.some((item) => item.handover === 'failed')) toast.error(t('groups.settings.role.handoverFailed'))
    chosen.value = []
  },
  onError: (error) =>
    toast.error(t('personas.detail.scenes.failedAll'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => {
    void client.invalidateQueries({ queryKey: keys.personas.all() })
    void client.invalidateQueries({ queryKey: keys.host.settings() })
    void readHostState()
  },
})
async function apply() {
  const sure = await confirm({
    title: t('personas.detail.scenes.confirm', { n: chosen.value.length, name: name.value }),
    message: chosen.value.map(groupLabel).join(t('personas.separator')),
    confirmLabel: t('personas.detail.scenes.apply'),
    tone: 'primary',
  })
  if (sure) use.mutate([...chosen.value])
}
</script>

<template>
  <EmptyState v-if="!rows.length" :icon="MessagesSquare" :title="t('groups.empty')" />
  <div v-else class="flex max-w-3xl flex-col gap-4">
    <div class="flex flex-wrap items-center gap-3">
      <Checkbox
        :model-value="chosen.length === 0 ? false : chosen.length === choosable.length ? true : 'indeterminate'"
        :disabled="!choosable.length || Boolean(blocked)"
        @update:model-value="(on) => (chosen = on === true ? [...choosable] : [])"
      >
        <span class="text-sm text-ink-2">{{ t('personas.detail.scenes.selectAll') }}</span>
      </Checkbox>
      <Button
        variant="primary"
        size="sm"
        :icon="Repeat"
        :loading="use.isPending.value"
        :disabled="!chosen.length || Boolean(blocked)"
        class="ml-auto"
        @click="apply"
      >
        {{ chosen.length ? t('personas.detail.scenes.applyCount', { n: chosen.length }) : t('personas.detail.scenes.apply') }}
      </Button>
    </div>
    <p v-if="blocked" class="text-sm text-warning">{{ blocked }}</p>
    <ul class="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
      <li v-for="row in rows" :key="row.scene" class="flex min-h-14 items-center gap-3 px-4 py-2.5">
        <Checkbox
          v-if="!row.using && !row.waiting"
          :model-value="chosen.includes(row.scene)"
          :disabled="Boolean(blocked) || use.isPending.value"
          :aria-label="groupLabel(row.scene)"
          @update:model-value="(on) => toggle(row.scene, on === true)"
        />
        <span v-else class="size-4.5 shrink-0" aria-hidden="true" />
        <Avatar :name="groupLabel(row.scene)" shape="square" :size="32" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium text-ink">{{ groupLabel(row.scene) }}</span>
          <span class="block truncate text-xs text-muted">{{ row.current }}</span>
        </span>
        <Badge v-if="row.using" tone="brand">{{ t('personas.detail.scenes.using') }}</Badge>
        <Badge v-else-if="row.waiting" tone="warning" dot pulse>{{ t('personas.detail.scenes.waiting') }}</Badge>
        <IconButton
          :icon="ArrowUpRight"
          :label="t('personas.detail.scenes.open')"
          size="sm"
          :to="groupsTarget(row.scene, 'settings')"
        />
      </li>
    </ul>
  </div>
</template>
