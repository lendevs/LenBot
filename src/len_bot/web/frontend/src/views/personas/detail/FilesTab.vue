<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import { personaFiles, personasApi, type PersonaFile } from '../../../api/personas'
import { developerDetails } from '../../../composables/useDeveloperMode.js'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { useRoleWrites } from './writes'

const props = defineProps<{ persona: string }>()
const emit = defineEmits<{ dirty: [value: boolean]; saved: [] }>()

const { t } = useI18n()
const client = useQueryClient()
const writes = useRoleWrites(computed(() => props.persona))
const filesKey = computed(() => keys.personas.part(props.persona, 'files'))
const files = useQuery({ queryKey: filesKey, queryFn: ({ signal }) => personasApi.files(props.persona, signal) })

const file = ref<PersonaFile>('persona.yaml')
const text = ref('')
const saved = computed(() => files.data.value?.saved[file.value] ?? '')
// Saved text read again (after a save elsewhere) replaces the editor only when it holds no edits.
watch(saved, (value, previous) => {
  if (previous === undefined || text.value === previous) text.value = value
}, { immediate: true })
const dirty = computed(() => Boolean(files.data.value) && text.value !== saved.value)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const options = computed(() => personaFiles.map((value) => ({ value, label: t(`personas.detail.files.names.${value.replace('.', '_')}`) })))
const selected = computed({
  get: () => file.value,
  set: (value: PersonaFile) => void pick(value),
})
async function pick(value: PersonaFile) {
  if (value === file.value) return
  if (dirty.value) {
    const sure = await confirm({ title: t('personas.detail.files.discard'), confirmLabel: t('common.discard'), tone: 'danger' })
    if (!sure) return
  }
  file.value = value
  text.value = files.data.value?.saved[value] ?? ''
}

const save = useMutation({
  mutationFn: () => personasApi.saveFile(props.persona, files.data.value!.saved_path, file.value, text.value),
  onSuccess: (result) => {
    client.setQueryData(filesKey.value, result)
    writes.done(result, ['profile', 'knowledge', 'stickers', 'abilities'])
    emit('saved')
  },
})
</script>

<template>
  <Skeleton v-if="files.isPending.value" :lines="10" />
  <ErrorNote
    v-else-if="files.isError.value"
    :title="t('personas.detail.files.readFailed')"
    :error="files.error.value"
    :retry="files.refetch"
  />
  <form v-else class="flex max-w-4xl flex-col gap-4" @submit.prevent="save.mutate()">
    <div class="flex flex-wrap items-center gap-3">
      <SegmentedControl v-model="selected" :options="options" size="sm" :label="t('personas.detail.files.label')" />
      <code class="font-mono text-xs text-subtle">{{ file }}</code>
    </div>
    <Textarea v-model="text" mono :rows="18" :max-rows="48" spellcheck="false" :aria-label="file" />
    <p v-if="developerDetails" class="truncate font-mono text-xs text-subtle" :title="files.data.value?.saved_path">
      {{ files.data.value?.saved_path }}
    </p>
    <SaveBar
      :dirty="dirty"
      :saving="save.isPending.value"
      :error="save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null"
      @save="save.mutate()"
      @discard="text = saved"
    />
  </form>
</template>
