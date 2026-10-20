<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { capabilitiesApi, type SkillPlace } from '../../api/capabilities'
import { keys } from '../../api/query'
import { developerDetails } from '../../composables/useDeveloperMode.js'
import { formatBytes } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import Dialog from '../../ui/Dialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { confirm } from '../../ui/confirm'
import { toast } from '../../ui/toast'
import RawRecord from '../groups/tasks/RawRecord.vue'

/** A skill's real files, read page by page, with moving and deleting where its source allows. */
const props = defineProps<{ place: SkillPlace }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ changed: [] }>()

const { t } = useI18n()
const client = useQueryClient()
const key = computed(() => keys.skills.files(props.place.scene, props.place.source, props.place.name, props.place.taskId ?? null))
const listing = useQuery({
  queryKey: key,
  queryFn: ({ signal }) => capabilitiesApi.skillFiles(props.place, signal),
  enabled: open,
})

const path = ref<string | null>(null)
const text = ref('')
const next = ref<number | null>(null)
const read = useMutation({
  mutationFn: ({ file, offset }: { file: string; offset: number }) => capabilitiesApi.skillText(props.place, file, offset),
  onSuccess: (page, { file, offset }) => {
    path.value = file
    text.value = offset ? text.value + page.content : page.content
    next.value = page.next_offset
  },
})
watch(
  () => listing.data.value,
  (value) => {
    if (value && path.value === null && value.files.some((file) => file.path === 'SKILL.md'))
      read.mutate({ file: 'SKILL.md', offset: 0 })
  },
  { immediate: true },
)

const movable = computed(() => props.place.source === 'task' || props.place.source === 'scene')
const removable = computed(() => props.place.source === 'scene' || props.place.source === 'shared')
const done = (message: string) => {
  toast.success(message)
  client.removeQueries({ queryKey: key.value })
  void client.invalidateQueries({ queryKey: keys.skills.all() })
  emit('changed')
  open.value = false
}
const move = useMutation({
  mutationFn: (target: 'scene' | 'shared') => capabilitiesApi.moveSkill(props.place, target),
  onSuccess: () => done(t('capabilities.skills.moved')),
})
const remove = useMutation({
  mutationFn: () => capabilitiesApi.removeSkill(props.place),
  onSuccess: () => done(t('capabilities.skills.removed')),
})
async function moveTo(target: 'scene' | 'shared') {
  const sure = await confirm({
    title: t('capabilities.skills.moveTitle', { name: props.place.name, place: t(`capabilities.skills.places.${target}`) }),
    message: t('capabilities.skills.moveMessage'),
    confirmLabel: t('capabilities.skills.move'),
    tone: 'primary',
  })
  if (sure) move.mutate(target)
}
async function confirmRemove() {
  const sure = await confirm({
    title: t('capabilities.skills.removeTitle', { name: props.place.name }),
    message: t('capabilities.skills.removeMessage'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) remove.mutate()
}
const busy = computed(() => move.isPending.value || remove.isPending.value)
const actionError = computed(() => move.error.value ?? remove.error.value)
</script>

<template>
  <Dialog v-model:open="open" :title="place.name" size="lg" :busy="busy">
    <Skeleton v-if="listing.isPending.value" :lines="6" />
    <ErrorNote v-else-if="listing.isError.value" :title="t('capabilities.skills.readFailed')" :error="listing.error.value" :retry="listing.refetch" />
    <div v-else-if="listing.data.value" class="flex min-w-0 flex-col gap-3">
      <p v-if="listing.data.value.skill.description" class="text-sm text-ink-2">{{ listing.data.value.skill.description }}</p>
      <p class="flex flex-wrap items-center gap-2 text-xs text-muted">
        <Badge>{{ t(`capabilities.skills.sources.${place.source}`) }}</Badge>
        <Badge v-if="!listing.data.value.skill.model_invocation" tone="warning">{{ t('capabilities.skills.manualOnly') }}</Badge>
        <span v-if="listing.data.value.used_by_running.length">
          {{ t('capabilities.skills.usedBy', { groups: listing.data.value.used_by_running.map(groupLabel).join(t('personas.separator')) }) }}
        </span>
      </p>
      <div class="flex flex-wrap gap-1.5">
        <Button
          v-for="file in listing.data.value.files"
          :key="file.path"
          size="sm"
          :variant="file.path === path ? 'secondary' : 'ghost'"
          class="font-mono"
          :aria-pressed="file.path === path"
          :title="formatBytes(file.size)"
          @click="read.mutate({ file: file.path, offset: 0 })"
        >
          {{ file.path }}
        </Button>
      </div>
      <ErrorNote v-if="read.isError.value" :title="t('capabilities.skills.readFile')" :error="read.error.value" />
      <CodeBlock v-if="path" :code="text || t('capabilities.skills.emptyFile')" :label="path" wrap :max-lines="30" />
      <Button
        v-if="next !== null && path"
        size="sm"
        variant="ghost"
        class="self-start"
        :loading="read.isPending.value"
        @click="read.mutate({ file: path, offset: next })"
      >
        {{ t('capabilities.skills.continue') }}
      </Button>
      <ErrorNote v-if="actionError" :title="t('capabilities.failed')" :error="actionError" />
      <RawRecord v-if="developerDetails" :label="t('capabilities.skills.raw')" :code="listing.data.value" />
    </div>
    <template v-if="movable || removable" #footer>
      <Button v-if="removable" variant="danger-ghost" class="mr-auto" :disabled="!listing.data.value || busy" :loading="remove.isPending.value" @click="confirmRemove">
        {{ t('common.delete') }}
      </Button>
      <Button v-if="place.source === 'task'" :disabled="!listing.data.value || busy" :loading="move.isPending.value && move.variables.value === 'scene'" @click="moveTo('scene')">
        {{ t('capabilities.skills.moveScene') }}
      </Button>
      <Button v-if="movable" variant="primary" :disabled="!listing.data.value || busy" :loading="move.isPending.value && move.variables.value === 'shared'" @click="moveTo('shared')">
        {{ place.source === 'scene' ? t('capabilities.skills.share') : t('capabilities.skills.moveShared') }}
      </Button>
    </template>
  </Dialog>
</template>
