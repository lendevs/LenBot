<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RefreshCw } from '@lucide/vue'
import { tasksApi, type LiveSnapshot } from '../../../api/tasks'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'

const props = defineProps<{ scene: string; id: number }>()

const { t } = useI18n()
const live = ref<LiveSnapshot | null>(null)
const state = ref<'connecting' | 'open' | 'closed'>('connecting')
const unreadable = ref<string | null>(null)
let socket: WebSocket | null = null

function connect() {
  const connection = new WebSocket(tasksApi.liveUrl(props.scene, props.id))
  socket = connection
  state.value = 'connecting'
  unreadable.value = null
  connection.onopen = () => {
    if (socket === connection) state.value = 'open'
  }
  connection.onmessage = (event: MessageEvent<string>) => {
    if (socket !== connection) return
    try {
      live.value = JSON.parse(event.data) as LiveSnapshot
    } catch (error) {
      unreadable.value = `${(error as Error).message}: ${String(event.data).slice(0, 300)}`
      connection.close()
    }
  }
  connection.onclose = () => {
    if (socket === connection) state.value = 'closed'
  }
}
function disconnect() {
  const connection = socket
  socket = null
  connection?.close()
}
onMounted(connect)
onBeforeUnmount(disconnect)
</script>

<template>
  <section
    v-if="live?.preview || unreadable || state === 'closed'"
    class="flex flex-col gap-2"
    :aria-label="t('groups.tasks.live.title')"
  >
    <div class="flex items-center gap-2">
      <h3 class="text-sm font-medium text-ink">{{ t('groups.tasks.live.title') }}</h3>
      <span v-if="state === 'closed'" class="text-xs text-muted">{{ t('groups.tasks.live.closed') }}</span>
      <Button v-if="state === 'closed'" size="sm" variant="ghost" :icon="RefreshCw" class="ml-auto" @click="connect">
        {{ t('groups.tasks.live.reconnect') }}
      </Button>
    </div>
    <pre
      v-if="live?.preview"
      class="max-h-96 overflow-y-auto rounded-lg border border-line bg-code px-3 py-2 font-mono text-xs leading-5 break-words whitespace-pre-wrap text-ink-2 scrollbar-thin"
      aria-live="polite"
      >{{ live.preview.text }}</pre
    >
    <p v-if="live?.preview?.truncated" class="text-xs text-muted">{{ t('groups.tasks.live.truncated') }}</p>
    <ErrorNote v-if="unreadable" :title="t('groups.tasks.live.unreadable')" :error="unreadable" />
  </section>
</template>
