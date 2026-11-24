<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { FileArchive, Upload } from '@lucide/vue'
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

const MAX_ZIP_BYTES = 200 * 1024 * 1024

function parseGitTreeUrl(raw: string): { repoUrl: string; branch: string } | null {
  let parsed: URL
  try {
    parsed = new URL(raw.trim())
  } catch {
    return null
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null
  const match =
    parsed.pathname.match(/^(\/.+?)\/-\/tree\/(.+?)\/?$/) ??
    parsed.pathname.match(/^(\/[^/]+\/[^/]+?)\/tree\/(.+?)\/?$/)
  if (!match) return null
  const repoPath = match[1].replace(/\.git$/, '')
  let branch: string
  try {
    branch = decodeURIComponent(match[2]).replace(/\/+$/, '')
  } catch {
    branch = match[2].replace(/\/+$/, '')
  }
  if (!branch) return null
  return { repoUrl: `${parsed.origin}${repoPath}`, branch }
}

const props = defineProps<{ request: InstallRequest }>()
const emit = defineEmits<{ done: [snapshot: PluginsSnapshot]; close: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const url = ref(props.request.kind === 'git' ? (props.request.url ?? '') : '')
const version = ref(props.request.kind === 'zip' ? '' : (props.request.ref ?? ''))
const switchSource = ref(false)
const file = ref<File | null>(null)
const fileError = ref<string | null>(null)
const dragging = ref(false)
let dragDepth = 0
const picker = useTemplateRef<HTMLInputElement>('picker')
const error = ref<unknown>(null)

const part = computed(() =>
  props.request.kind === 'update' ? `update:${props.request.name}` : `install:${props.request.kind}`,
)
const saving = computed(() => state.isBusy(part.value))
const ready = computed(() =>
  props.request.kind === 'git'
    ? Boolean(url.value.trim())
    : props.request.kind === 'zip'
      ? Boolean(file.value) && !fileError.value
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

function splitTreeUrl() {
  if (props.request.kind !== 'git' || version.value.trim()) return
  const parsed = parseGitTreeUrl(url.value)
  if (!parsed) return
  url.value = parsed.repoUrl
  version.value = parsed.branch
}

function onUrlPaste(event: ClipboardEvent) {
  if (props.request.kind !== 'git' || version.value.trim()) return
  const pasted = event.clipboardData?.getData('text') ?? ''
  const parsed = parseGitTreeUrl(pasted)
  if (!parsed) return
  event.preventDefault()
  url.value = parsed.repoUrl
  version.value = parsed.branch
}

function selectFile(picked: File | null) {
  error.value = null
  fileError.value = null
  if (!picked) {
    file.value = null
    return
  }
  if (!picked.name.toLowerCase().endsWith('.zip')) {
    file.value = null
    fileError.value = t('plugins.install.zipOnly')
    return
  }
  file.value = picked
  if (picked.size > MAX_ZIP_BYTES) {
    fileError.value = t('plugins.install.zipTooLarge', { max: '200 MiB' })
  }
}

function chosen(event: Event) {
  const input = event.target as HTMLInputElement
  selectFile(input.files?.[0] ?? null)
  input.value = ''
}

function onDragEnter(event: DragEvent) {
  if (saving.value) return
  event.preventDefault()
  dragDepth += 1
  dragging.value = true
}
function onDragOver(event: DragEvent) {
  if (saving.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  dragging.value = true
}
function onDragLeave(event: DragEvent) {
  if (saving.value) return
  event.preventDefault()
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragging.value = false
  }
}
function onDrop(event: DragEvent) {
  if (saving.value) return
  event.preventDefault()
  dragDepth = 0
  dragging.value = false
  const dropped = event.dataTransfer?.files?.[0] ?? null
  if (dropped) selectFile(dropped)
}

async function submit() {
  splitTreeUrl()
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
        <Input
          v-model="url"
          type="url"
          mono
          placeholder="https://github.com/author/plugin.git"
          autofocus
          @paste="onUrlPaste"
          @blur="splitTreeUrl"
        />
      </Field>
      <Field v-if="request.kind !== 'zip'" :label="t('plugins.install.ref')">
        <Input v-model="version" mono :placeholder="t('plugins.install.refPlaceholder')" />
      </Field>
      <Field v-if="request.kind === 'zip'" :label="t('plugins.install.zipFile')" :error="fileError" required>
        <input
          ref="picker"
          type="file"
          accept=".zip,application/zip"
          class="sr-only"
          tabindex="-1"
          aria-hidden="true"
          @change="chosen"
        />
        <button
          type="button"
          :disabled="saving"
          class="flex w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed px-4 py-5 text-center transition-colors focus-visible:focus-ring disabled:pointer-events-none disabled:opacity-50"
          :class="
            dragging
              ? 'border-primary bg-selected/40 text-ink'
              : fileError
                ? 'border-error bg-error-bg/40 text-ink'
                : 'border-line-strong bg-fill/40 text-muted hover:border-subtle hover:bg-hover/50 hover:text-ink'
          "
          @click="picker?.click()"
          @dragenter="onDragEnter"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
        >
          <FileArchive v-if="file" :size="20" class="shrink-0 text-primary" aria-hidden="true" />
          <Upload v-else :size="20" class="shrink-0" aria-hidden="true" />
          <template v-if="file">
            <span class="max-w-full truncate text-sm font-medium text-ink">{{ file.name }}</span>
            <span class="text-xs text-muted tabular">
              {{ formatBytes(file.size) }} · {{ t('plugins.install.replaceFile') }}
            </span>
          </template>
          <span v-else class="text-sm">{{ t('plugins.install.dropHint') }}</span>
        </button>
      </Field>
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
