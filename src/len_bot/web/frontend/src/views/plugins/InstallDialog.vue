<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Paperclip } from '@lucide/vue'
import { pluginsApi, type PluginsSnapshot } from '../../api/plugins'
import { formatBytes } from '../../i18n/format'
import Button from '../../ui/Button.vue'
import Checkbox from '../../ui/Checkbox.vue'
import Dialog from '../../ui/Dialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import { usePluginsState } from './state'

export type InstallRequest =
  | { kind: 'git'; url?: string; ref?: string | null }
  | { kind: 'zip' }
  | { kind: 'update'; name: string; ref?: string | null }

const props = defineProps<{ request: InstallRequest }>()
const emit = defineEmits<{ done: [snapshot: PluginsSnapshot]; close: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const url = ref(props.request.kind === 'git' ? (props.request.url ?? '') : '')
const version = ref(props.request.kind === 'zip' ? '' : (props.request.ref ?? ''))
const switchSource = ref(false)
const file = ref<File | null>(null)
const picker = useTemplateRef<HTMLInputElement>('picker')
const error = ref<unknown>(null)
const part = computed(() => (props.request.kind === 'update' ? props.request.name : 'install'))
const saving = computed(() => state.busy.value === part.value)
const ready = computed(() =>
  props.request.kind === 'git'
    ? Boolean(url.value.trim())
    : props.request.kind === 'zip'
      ? Boolean(file.value)
      : true,
)
const title = computed(() =>
  props.request.kind === 'update'
    ? t('plugins.install.updateTitle', { name: props.request.name })
    : t(`plugins.install.${props.request.kind}Title`),
)

const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})
function chosen(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
async function submit() {
  if (!ready.value || saving.value) return
  error.value = null
  const request = props.request
  const ref = version.value.trim() || null
  try {
    const result = await state.run(
      part.value,
      () =>
        request.kind === 'git'
          ? pluginsApi.install(url.value.trim(), ref, switchSource.value)
          : request.kind === 'zip'
            ? pluginsApi.importZip(file.value!, switchSource.value)
            : pluginsApi.update(request.name, ref),
      { quiet: true },
    )
    if (result) emit('done', result)
  } catch (problem) {
    error.value = problem
  }
}
</script>

<template>
  <Dialog v-model:open="open" :title="title" size="sm" :busy="saving">
    <form id="plugin-install" class="flex flex-col gap-4" @submit.prevent="submit">
      <Field v-if="request.kind === 'git'" :label="t('plugins.install.url')" required>
        <Input v-model="url" type="url" mono placeholder="https://github.com/author/plugin.git" autofocus />
      </Field>
      <Field v-if="request.kind !== 'zip'" :label="t('plugins.install.ref')">
        <Input v-model="version" mono :placeholder="t('plugins.install.refPlaceholder')" />
      </Field>
      <template v-if="request.kind === 'zip'">
        <input
          ref="picker"
          type="file"
          accept=".zip,application/zip"
          class="sr-only"
          tabindex="-1"
          aria-hidden="true"
          @change="chosen"
        />
        <div class="flex min-w-0 items-center gap-3">
          <Button size="sm" :icon="Paperclip" :disabled="saving" @click="picker?.click()">
            {{ t('plugins.install.choose') }}
          </Button>
          <span v-if="file" class="min-w-0 truncate text-sm text-ink-2">
            {{ file.name }} ·
            <span class="tabular">{{ formatBytes(file.size) }}</span>
          </span>
        </div>
      </template>
      <Checkbox
        v-if="request.kind !== 'update'"
        :model-value="switchSource"
        @update:model-value="(value) => (switchSource = value === true)"
      >
        {{ t('plugins.install.switchSource') }}
      </Checkbox>
      <ErrorNote v-if="error" :title="t('plugins.install.failed')" :error="error" />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</Button>
      <Button variant="primary" type="submit" form="plugin-install" :loading="saving" :disabled="!ready">
        {{ t('plugins.install.prepare') }}
      </Button>
    </template>
  </Dialog>
</template>
