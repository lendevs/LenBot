<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RotateCcw } from '@lucide/vue'
import { keys } from '../../../api/query'
import {
  expressionFiles,
  personaFiles,
  personasApi,
  type ExpressionFile,
  type PersonaFile,
} from '../../../api/personas'
import { developerDetails } from '../../../composables/useDeveloperMode'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useRoleWrites } from './writes'

const props = defineProps<{ persona: string }>()
const emit = defineEmits<{ dirty: [value: boolean]; saved: [] }>()

const { t } = useI18n()
const isWide = useMediaQuery('(min-width: 640px)')
const client = useQueryClient()
const writes = useRoleWrites(computed(() => props.persona))
const filesKey = computed(() => keys.personas.part(props.persona, 'files'))
const files = useQuery({
  queryKey: filesKey,
  queryFn: ({ signal }) => personasApi.files(props.persona, signal),
})

type FileName = PersonaFile | ExpressionFile
const allFiles: FileName[] = [...personaFiles, ...expressionFiles]
const isExpression = (value: FileName): value is ExpressionFile =>
  (expressionFiles as readonly string[]).includes(value)
const isCustomized = (value: FileName) =>
  isExpression(value) && Boolean(files.data.value?.saved[value]?.trim())

const file = ref<FileName>('persona.yaml')
const text = ref('')
const baseText = ref<string | null>(null)
const remoteUpdated = ref(false)
const saved = computed(() => files.data.value?.saved[file.value] ?? '')

watch(
  saved,
  (next) => {
    if (!files.data.value) return
    if (baseText.value === null) {
      baseText.value = next
      text.value = next
      remoteUpdated.value = false
      return
    }
    if (next === baseText.value) {
      remoteUpdated.value = false
      return
    }
    if (text.value === baseText.value || text.value === next) {
      baseText.value = next
      text.value = next
      remoteUpdated.value = false
      return
    }
    remoteUpdated.value = true
  },
  { immediate: true },
)

const dirty = computed(() => Boolean(files.data.value) && text.value !== saved.value)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const fileLabel = (value: FileName) => t(`personas.detail.files.names.${value.replace('.', '_')}`)
const segmentOptions = computed(() =>
  allFiles.map((value) => ({
    value,
    label: isCustomized(value) ? `${fileLabel(value)} •` : fileLabel(value),
  })),
)
const selectOptions = computed(() =>
  allFiles.map((value) => ({
    value,
    label: fileLabel(value),
    meta: isExpression(value)
      ? isCustomized(value)
        ? t('personas.detail.preview.own')
        : t('personas.detail.preview.framework')
      : value,
  })),
)
const expression = computed(() => isExpression(file.value))
const currentCustom = computed(() => isCustomized(file.value))
/** A blank expression file uses the framework's text, shown in its place until one is written. */
const fallback = computed(() =>
  expression.value ? (files.data.value?.defaults[file.value as ExpressionFile] ?? '') : undefined,
)
const selected = computed({
  get: () => file.value,
  set: (value: FileName | undefined) => {
    if (value) void pick(value)
  },
})

function reloadRemote() {
  const next = saved.value
  baseText.value = next
  text.value = next
  remoteUpdated.value = false
  save.reset()
}

async function pick(value: FileName) {
  if (value === file.value) return
  if (dirty.value) {
    const sure = await confirm({
      title: t('personas.detail.files.discard'),
      confirmLabel: t('common.discard'),
      tone: 'danger',
    })
    if (!sure) return
  }
  file.value = value
  const next = files.data.value?.saved[value] ?? ''
  baseText.value = next
  text.value = next
  remoteUpdated.value = false
  save.reset()
}

const save = useMutation({
  mutationFn: () => personasApi.saveFile(props.persona, files.data.value!.saved_path, file.value, text.value),
  onSuccess: (result) => {
    const next = result.saved[file.value] ?? ''
    baseText.value = next
    text.value = next
    remoteUpdated.value = false
    client.setQueryData(filesKey.value, result)
    writes.done(result, ['profile', 'knowledge', 'stickers', 'abilities'])
    emit('saved')
  },
})

const restore = useMutation({
  mutationFn: () => personasApi.saveFile(props.persona, files.data.value!.saved_path, file.value, ''),
  onSuccess: (result) => {
    const next = result.saved[file.value] ?? ''
    baseText.value = next
    text.value = next
    remoteUpdated.value = false
    save.reset()
    client.setQueryData(filesKey.value, result)
    writes.done(
      result,
      ['profile', 'knowledge', 'stickers', 'abilities'],
      t('personas.detail.files.restored'),
    )
    emit('saved')
  },
  onError: (error) =>
    toast.error(t('ui.error.title'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})

async function restoreDefault() {
  if (!expression.value) return
  if (!saved.value.trim()) {
    text.value = ''
    return
  }
  const sure = await confirm({
    title: t('personas.detail.files.restoreTitle'),
    message: t('personas.detail.files.restoreMessage'),
    confirmLabel: t('personas.detail.files.restoreDefault'),
    tone: 'danger',
  })
  if (sure) restore.mutate()
}
</script>

<template>
  <Skeleton v-if="files.isPending.value" :lines="10" />
  <ErrorNote
    v-else-if="files.isError.value"
    :title="t('personas.detail.files.readFailed')"
    :error="files.error.value"
    :retry="files.refetch"
  />
  <form v-else class="flex max-w-4xl flex-col gap-4 pb-6" @submit.prevent="save.mutate()">
    <div class="flex min-w-0 flex-wrap items-center gap-3">
      <div v-if="isWide" class="min-w-0 max-w-full">
        <SegmentedControl
          v-model="selected"
          :options="segmentOptions"
          size="sm"
          :label="t('personas.detail.files.label')"
        />
      </div>
      <div v-else class="w-full">
        <Select
          v-model="selected"
          :options="selectOptions"
          size="sm"
          :aria-label="t('personas.detail.files.label')"
        />
      </div>
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <code class="font-mono text-xs text-subtle">{{ file }}</code>
        <Badge v-if="expression" :tone="currentCustom ? 'info' : 'neutral'">
          {{ currentCustom ? t('personas.detail.preview.own') : t('personas.detail.preview.framework') }}
        </Badge>
      </div>
    </div>

    <div
      v-if="remoteUpdated"
      role="status"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
    >
      <span class="min-w-0 flex-1">{{ t('ui.draft.remoteUpdated') }}</span>
      <Button size="sm" variant="ghost" @click="reloadRemote">
        {{ t('ui.draft.reloadRemote') }}
      </Button>
    </div>

    <Textarea
      v-model="text"
      mono
      :rows="18"
      :max-rows="48"
      spellcheck="false"
      :aria-label="file"
      :placeholder="fallback"
    />
    <div v-if="expression" class="flex flex-wrap items-center gap-2">
      <Button v-if="!text.trim()" size="sm" variant="secondary" @click="text = fallback ?? ''">
        {{ t('personas.detail.files.fillDefault') }}
      </Button>
      <Button
        v-if="saved.trim() || text.trim()"
        size="sm"
        variant="ghost"
        :icon="RotateCcw"
        :loading="restore.isPending.value"
        :disabled="save.isPending.value"
        @click="restoreDefault"
      >
        {{ t('personas.detail.files.restoreDefault') }}
      </Button>
    </div>
    <p
      v-if="developerDetails"
      class="truncate font-mono text-xs text-subtle"
      :title="files.data.value?.saved_path"
    >
      {{ files.data.value?.saved_path }}
    </p>
    <SaveBar
      :dirty="dirty"
      :saving="save.isPending.value"
      :error="save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null"
      :raw-error="save.isError.value ? describeError(save.error.value, t('ui.error.network')).raw : null"
      @save="save.mutate()"
      @discard="reloadRemote"
    />
  </form>
</template>
