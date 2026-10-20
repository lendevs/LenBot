<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import { storageApi, type CleanupOperation } from '../../../api/resources'
import { formatBytes } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import FileBrowser from './FileBrowser.vue'

/** Cleans the temporary files of finished tasks, or releases their whole environment. */
const props = defineProps<{ scene: string; ids: number[]; operation: CleanupOperation; timeZone: string }>()
const emit = defineEmits<{ done: []; close: [] }>()

const { t } = useI18n()
const client = useQueryClient()
/** Fixed when the dialog opens; the caller clears its selection once the cleanup is done. */
const targets = [...props.ids]
const viewing = ref(targets[0])
const choices = computed(() => targets.map((id) => ({ value: id, label: `#${id}` })))
const storage = useQuery({
  queryKey: computed(() => keys.tasks.storage(props.scene, viewing.value)),
  queryFn: ({ signal }) => storageApi.task(props.scene, viewing.value, signal),
})
const temporary = computed(() => storage.data.value?.temporary.filter((item) => item.exists) ?? [])

const clean = useMutation({
  mutationFn: () => storageApi.cleanup(props.scene, targets, props.operation),
  onSuccess: () => emit('done'),
  onSettled: () => client.invalidateQueries({ queryKey: keys.tasks.space() }),
})
const results = computed(() => clean.data.value?.items ?? null)
const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})
</script>

<template>
  <Dialog
    v-model:open="open"
    :title="t(`groups.tasks.space.cleanup.${operation}Title`, { n: targets.length })"
    size="lg"
    :busy="clean.isPending.value"
  >
    <div class="flex flex-col gap-4">
      <p class="text-sm text-ink-2">{{ t(`groups.tasks.space.cleanup.${operation}Effect`) }}</p>
      <template v-if="!results">
        <div v-if="targets.length > 1" class="w-32"><Select v-model="viewing" :options="choices" size="sm" /></div>
        <Skeleton v-if="storage.isPending.value" :lines="3" />
        <ErrorNote
          v-else-if="storage.isError.value"
          :title="t('groups.tasks.space.storageFailed')"
          :error="storage.error.value"
        />
        <template v-else-if="storage.data.value">
          <p class="text-sm text-ink">
            #{{ viewing }} {{ storage.data.value.task.goal }}
            <span v-if="!storage.data.value.cleanable" class="text-warning">
              · {{ t('groups.tasks.space.notCleanable') }}
            </span>
          </p>
          <template v-if="operation === 'temporary'">
            <ul
              v-if="temporary.length"
              class="flex list-none flex-col divide-y divide-line rounded-lg border border-line font-mono text-xs"
            >
              <li v-for="item in temporary" :key="item.path" class="flex gap-3 px-3 py-1.5">
                <span class="min-w-0 flex-1 break-all text-ink-2">{{ item.path }}</span>
                <span class="tabular text-muted">{{ formatBytes(item.file_bytes) }}</span>
              </li>
            </ul>
            <p v-else class="text-sm text-muted">{{ t('groups.tasks.space.cleanup.nothing') }}</p>
          </template>
          <!-- Last chance to keep products before the workspace goes. -->
          <FileBrowser
            v-else
            :key="viewing"
            :scene="scene"
            :task-id="viewing"
            :time-zone="timeZone"
            initial-path="out"
          />
        </template>
      </template>
      <ErrorNote v-if="clean.isError.value" :title="t('groups.tasks.space.cleanup.failed')" :error="clean.error.value" />
      <ul v-if="results" class="flex list-none flex-col divide-y divide-line rounded-lg border border-line">
        <li v-for="item in results" :key="item.task_id" class="flex flex-col gap-1.5 px-3 py-2">
          <div class="flex items-center gap-3">
            <span class="tabular text-sm text-ink">#{{ item.task_id }}</span>
            <span v-if="item.removal" class="min-w-0 flex-1 text-xs text-muted">
              {{
                t('groups.tasks.space.cleanup.removal', {
                  removed: item.removal.removed.length,
                  absent: item.removal.absent.length,
                })
              }}
            </span>
            <Badge :tone="item.status === 'complete' ? 'success' : 'error'" size="sm" class="ml-auto">
              {{ t(`groups.tasks.space.cleanup.${item.status}`) }}
            </Badge>
          </div>
          <ErrorNote v-if="item.error" :title="t('groups.tasks.space.cleanup.itemFailed')" :error="item.error" />
        </li>
      </ul>
    </div>
    <template #footer>
      <Button variant="ghost" :disabled="clean.isPending.value" @click="emit('close')">
        {{ t(results ? 'common.close' : 'common.cancel') }}
      </Button>
      <Button v-if="!results" variant="danger" :loading="clean.isPending.value" @click="clean.mutate()">
        {{ t(`groups.tasks.space.cleanup.${operation}`) }}
      </Button>
    </template>
  </Dialog>
</template>
