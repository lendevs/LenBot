<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import type { ChatMessage, ChatSource, ChatTurn } from '../../../api/trials'
import { developerDetails } from '../../../composables/useDeveloperMode'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Sheet from '../../../ui/Sheet.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import RawRecord from '../../groups/tasks/RawRecord.vue'
import ChatWindow from './ChatWindow.vue'
import TurnList from './TurnList.vue'
import { useChat } from './useChat'

/** A chat-app view of one trial with its turns beside it; the turn steps are the group live tab's. */
const props = withDefaults(
  defineProps<{
    source: ChatSource
    context?: string[]
    embedded?: boolean
  }>(),
  { context: undefined, embedded: false },
)

const { t } = useI18n()
const chat = useChat(props.source)
const isDesktop = useMediaQuery('(min-width: 1024px)')
const desktopTurnsOpen = ref(true)
const drawerTurnsOpen = ref(false)
const openTurn = ref<string | null>(null)
const turnListRef = ref<InstanceType<typeof TurnList>>()
const drawerTurnListRef = ref<InstanceType<typeof TurnList>>()

const turnsOpen = computed(() => (isDesktop.value ? desktopTurnsOpen.value : drawerTurnsOpen.value))
function toggleTurns() {
  if (isDesktop.value) desktopTurnsOpen.value = !desktopTurnsOpen.value
  else drawerTurnsOpen.value = !drawerTurnsOpen.value
}

function findTurnForMessage(message: ChatMessage, turns: ChatTurn[]): ChatTurn | undefined {
  if (!message.is_self) return undefined
  return (
    turns.find(
      (turn) => turn.started <= message.time && (turn.ended === null || message.time <= turn.ended),
    ) ??
    turns.find(
      (turn) => turn.started - 0.5 <= message.time && (turn.ended === null || message.time <= turn.ended + 1),
    )
  )
}

const messageTurnIds = computed(() => {
  const map = new Map<number, string>()
  const turns = chat.turns.value
  for (const message of chat.messages.value) {
    const turn = findTurnForMessage(message, turns)
    if (turn) map.set(message.seq, turn.id)
  }
  return map
})

const turnSpeechCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const turnId of messageTurnIds.value.values()) {
    counts.set(turnId, (counts.get(turnId) ?? 0) + 1)
  }
  return counts
})

/** The turn that was running when the bot sent this message. */
async function showTurnOf(message: ChatMessage) {
  const turnId = messageTurnIds.value.get(message.seq)
  if (!turnId) return
  if (isDesktop.value) desktopTurnsOpen.value = true
  else drawerTurnsOpen.value = true
  openTurn.value = turnId
  await nextTick()
  if (!isDesktop.value && !drawerTurnListRef.value) await nextTick()
  const list = isDesktop.value ? turnListRef.value : drawerTurnListRef.value
  await list?.focusTurn(turnId)
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <Skeleton v-if="chat.state.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="chat.state.isError.value"
      :title="t('playground.readFailed')"
      :error="chat.state.error.value"
      :retry="chat.state.refetch"
    />
    <template v-else-if="chat.data.value">
      <ErrorNote
        v-if="chat.data.value.error"
        :title="t('playground.runFailed')"
        :error="chat.data.value.error"
      />
      <div
        class="grid min-w-0 items-start gap-4"
        :class="isDesktop && desktopTurnsOpen && 'lg:grid-cols-[minmax(0,3fr)_minmax(300px,2fr)]'"
      >
        <ChatWindow
          :source="source"
          :chat="chat"
          :turns-open="turnsOpen"
          :context="context"
          :embedded="embedded"
          :active-turn-id="openTurn"
          :message-turn-ids="messageTurnIds"
          @toggle-turns="toggleTurns"
          @open-turn="showTurnOf"
        />
        <TurnList
          v-if="isDesktop && desktopTurnsOpen"
          ref="turnListRef"
          v-model:open="openTurn"
          :source="source"
          :turns="chat.turns.value"
          :time-zone="chat.data.value.timezone"
          :speech-counts="turnSpeechCounts"
          :embedded="embedded"
        />
      </div>
      <Sheet
        v-if="!isDesktop"
        v-model:open="drawerTurnsOpen"
        :title="t('playground.turns')"
        side="right"
        size="md"
      >
        <TurnList
          ref="drawerTurnListRef"
          v-model:open="openTurn"
          :source="source"
          :turns="chat.turns.value"
          :time-zone="chat.data.value.timezone"
          :speech-counts="turnSpeechCounts"
          bare
        />
      </Sheet>
      <RawRecord
        v-if="developerDetails"
        :label="t('playground.binding')"
        :code="{ scene: chat.data.value.scene, models: chat.data.value.models }"
      />
    </template>
  </div>
</template>
