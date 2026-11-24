<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ChevronRight } from '@lucide/vue'
import { memoryApi } from '../../../api/memory'
import { keys } from '../../../api/query'
import { formatDateTime } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'

interface DiffLine {
  kind: 'same' | 'add' | 'del'
  text: string
  oldLine: number | null
  newLine: number | null
}

type DiffChunk = { kind: 'lines'; lines: DiffLine[] } | { kind: 'collapsed'; id: string; lines: DiffLine[] }

interface ChangeDiff {
  chunks: DiffChunk[]
  added: number
  removed: number
}

const props = defineProps<{ scene: string; path: string; timeZone: string }>()
const open = defineModel<boolean>('open', { default: false })

const { t, te } = useI18n()
const history = useQuery({
  queryKey: computed(() => keys.memory.history(props.scene, props.path)),
  queryFn: ({ signal }) => memoryApi.history(props.scene, props.path, signal),
  enabled: open,
})
const action = (value: string) =>
  te(`groups.memory.history.actions.${value}`) ? t(`groups.memory.history.actions.${value}`) : value
const tones: Record<string, Tone> = { write: 'neutral', delete: 'warning', forget: 'error' }

type ViewMode = 'diff' | 'raw'
const modes = computed(() => [
  { value: 'diff' as const, label: t('groups.memory.history.modes.diff') },
  { value: 'raw' as const, label: t('groups.memory.history.modes.raw') },
])
const viewModes = ref<Record<number, ViewMode>>({})
const expandedChunks = ref<Record<string, boolean>>({})

watch([open, () => props.path], ([isOpen]) => {
  if (!isOpen) return
  viewModes.value = {}
  expandedChunks.value = {}
})

function modeOf(index: number): ViewMode {
  return viewModes.value[index] ?? 'diff'
}
function setMode(index: number, mode: ViewMode) {
  viewModes.value = { ...viewModes.value, [index]: mode }
}
function toggleChunk(id: string) {
  expandedChunks.value = { ...expandedChunks.value, [id]: !expandedChunks.value[id] }
}

const splitLines = (value: string | null): string[] =>
  value === null || value === '' ? [] : value.replace(/\r\n/g, '\n').split('\n')

function diffLines(before: string | null, after: string | null): DiffLine[] {
  const a = splitLines(before)
  const b = splitLines(after)
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1
    endB -= 1
  }

  const lines: DiffLine[] = []
  for (let i = 0; i < start; i++) {
    lines.push({ kind: 'same', text: a[i]!, oldLine: i + 1, newLine: i + 1 })
  }

  const midA = a.slice(start, endA)
  const midB = b.slice(start, endB)
  const m = midA.length
  const n = midB.length

  if (m > 0 && n > 0 && m * n <= 250_000) {
    const width = n + 1
    const dp = new Int32Array((m + 1) * width)
    for (let i = m - 1; i >= 0; i--) {
      const row = i * width
      const nextRow = (i + 1) * width
      for (let j = n - 1; j >= 0; j--) {
        if (midA[i] === midB[j]) dp[row + j] = dp[nextRow + j + 1]! + 1
        else dp[row + j] = Math.max(dp[nextRow + j]!, dp[row + j + 1]!)
      }
    }
    let i = 0
    let j = 0
    while (i < m && j < n) {
      if (midA[i] === midB[j]) {
        lines.push({ kind: 'same', text: midA[i]!, oldLine: start + i + 1, newLine: start + j + 1 })
        i += 1
        j += 1
      } else if (dp[(i + 1) * width + j]! >= dp[i * width + (j + 1)]!) {
        lines.push({ kind: 'del', text: midA[i]!, oldLine: start + i + 1, newLine: null })
        i += 1
      } else {
        lines.push({ kind: 'add', text: midB[j]!, oldLine: null, newLine: start + j + 1 })
        j += 1
      }
    }
    while (i < m) {
      lines.push({ kind: 'del', text: midA[i]!, oldLine: start + i + 1, newLine: null })
      i += 1
    }
    while (j < n) {
      lines.push({ kind: 'add', text: midB[j]!, oldLine: null, newLine: start + j + 1 })
      j += 1
    }
  } else {
    for (let i = 0; i < m; i++) {
      lines.push({ kind: 'del', text: midA[i]!, oldLine: start + i + 1, newLine: null })
    }
    for (let j = 0; j < n; j++) {
      lines.push({ kind: 'add', text: midB[j]!, oldLine: null, newLine: start + j + 1 })
    }
  }

  for (let k = 0; k < a.length - endA; k++) {
    lines.push({ kind: 'same', text: a[endA + k]!, oldLine: endA + k + 1, newLine: endB + k + 1 })
  }
  return lines
}

function buildDiff(changeIndex: number, before: string | null, after: string | null): ChangeDiff {
  const lines = diffLines(before, after)
  let added = 0
  let removed = 0
  for (const line of lines) {
    if (line.kind === 'add') added += 1
    else if (line.kind === 'del') removed += 1
  }

  const chunks: DiffChunk[] = []
  let cursor = 0
  let blockId = 0
  while (cursor < lines.length) {
    const isSame = lines[cursor]!.kind === 'same'
    let end = cursor + 1
    while (end < lines.length && (lines[end]!.kind === 'same') === isSame) end += 1
    const run = lines.slice(cursor, end)
    if (!isSame || run.length <= 3) {
      chunks.push({ kind: 'lines', lines: run })
    } else {
      const keepStart = cursor > 0 ? 1 : 0
      const keepEnd = end < lines.length ? 1 : 0
      if (keepStart > 0) chunks.push({ kind: 'lines', lines: run.slice(0, keepStart) })
      const hidden = run.slice(keepStart, run.length - keepEnd)
      if (hidden.length > 0) {
        chunks.push({ kind: 'collapsed', id: `${changeIndex}:${blockId}`, lines: hidden })
        blockId += 1
      }
      if (keepEnd > 0) chunks.push({ kind: 'lines', lines: run.slice(run.length - keepEnd) })
    }
    cursor = end
  }
  return { chunks, added, removed }
}

const diffs = computed(() =>
  (history.data.value?.changes ?? []).map((change, index) => buildDiff(index, change.before, change.after)),
)
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.memory.history.title', { path })" size="lg">
    <Skeleton v-if="history.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="history.isError.value"
      :title="t('groups.memory.readFailed')"
      :error="history.error.value"
      :retry="history.refetch"
    />
    <p v-else-if="!history.data.value?.changes.length" class="text-sm text-muted">
      {{ t('groups.memory.history.none') }}
    </p>
    <ol v-else class="flex list-none flex-col divide-y divide-line">
      <li
        v-for="(change, index) in history.data.value.changes"
        :key="index"
        class="flex flex-col gap-1.5 py-3.5 first:pt-0 last:pb-0"
      >
        <div class="flex flex-wrap items-center gap-2">
          <Badge :tone="tones[change.action] ?? 'neutral'">{{ action(change.action) }}</Badge>
          <span class="text-xs text-subtle tabular">
            {{ formatDateTime(change.changed_at, { timeZone }) }}
          </span>
          <span
            v-if="diffs[index]!.added || diffs[index]!.removed"
            class="flex items-center gap-1.5 text-xs tabular"
          >
            <span v-if="diffs[index]!.added" class="text-success">+{{ diffs[index]!.added }}</span>
            <span v-if="diffs[index]!.removed" class="text-error">-{{ diffs[index]!.removed }}</span>
          </span>
        </div>
        <p class="text-sm break-words text-ink-2">{{ change.reason }}</p>
        <details class="group">
          <summary
            class="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
          >
            <ChevronRight
              :size="13"
              class="shrink-0 transition-transform duration-150 group-open:rotate-90"
              aria-hidden="true"
            />
            {{ t('groups.memory.history.diff') }}
          </summary>
          <div class="mt-2 flex flex-col gap-2">
            <div class="flex items-center justify-end">
              <SegmentedControl
                :model-value="modeOf(index)"
                :options="modes"
                size="sm"
                :label="t('groups.memory.history.diff')"
                @update:model-value="(value: ViewMode) => setMode(index, value)"
              />
            </div>
            <div v-if="modeOf(index) === 'raw'" class="grid gap-2 sm:grid-cols-2">
              <CodeBlock
                :code="change.before ?? t('common.none')"
                :max-lines="12"
                :label="t('groups.memory.history.before')"
              />
              <CodeBlock
                :code="change.after ?? t('common.none')"
                :max-lines="12"
                :label="t('groups.memory.history.after')"
              />
            </div>
            <p
              v-else-if="!diffs[index]!.added && !diffs[index]!.removed"
              class="rounded-md border border-line bg-fill px-3 py-2 text-xs text-muted"
            >
              {{ t('groups.memory.history.noChanges') }}
            </p>
            <div
              v-else
              class="overflow-x-auto rounded-md border border-line bg-code font-mono text-xs leading-5 scrollbar-thin"
            >
              <template v-for="(chunk, chunkIndex) in diffs[index]!.chunks" :key="chunkIndex">
                <template v-if="chunk.kind === 'lines'">
                  <div
                    v-for="(line, lineIndex) in chunk.lines"
                    :key="lineIndex"
                    class="flex gap-2 px-2.5 py-0.5"
                    :class="
                      line.kind === 'add'
                        ? 'bg-success-bg text-success'
                        : line.kind === 'del'
                          ? 'bg-error-bg text-error'
                          : 'text-ink-2'
                    "
                  >
                    <span class="w-3 shrink-0 text-center select-none" aria-hidden="true">
                      {{ line.kind === 'add' ? '+' : line.kind === 'del' ? '-' : ' ' }}
                    </span>
                    <span class="min-w-0 flex-1 break-words whitespace-pre-wrap">{{ line.text || ' ' }}</span>
                  </div>
                </template>
                <template v-else>
                  <button
                    v-if="!expandedChunks[chunk.id]"
                    type="button"
                    class="flex w-full cursor-pointer items-center justify-center border-y border-line bg-fill/70 px-2.5 py-1 font-sans text-xs text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
                    @click="toggleChunk(chunk.id)"
                  >
                    {{ t('groups.memory.history.unchanged', { n: chunk.lines.length }, chunk.lines.length) }}
                  </button>
                  <template v-else>
                    <div
                      v-for="(line, lineIndex) in chunk.lines"
                      :key="lineIndex"
                      class="flex gap-2 px-2.5 py-0.5 text-ink-2"
                    >
                      <span class="w-3 shrink-0 text-center select-none" aria-hidden="true">&nbsp;</span>
                      <span class="min-w-0 flex-1 break-words whitespace-pre-wrap">
                        {{ line.text || ' ' }}
                      </span>
                    </div>
                    <button
                      type="button"
                      class="flex w-full cursor-pointer items-center justify-center border-y border-line bg-fill/70 px-2.5 py-1 font-sans text-xs text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
                      @click="toggleChunk(chunk.id)"
                    >
                      {{ t('groups.memory.history.collapseUnchanged') }}
                    </button>
                  </template>
                </template>
              </template>
            </div>
          </div>
        </details>
      </li>
    </ol>
  </Dialog>
</template>
