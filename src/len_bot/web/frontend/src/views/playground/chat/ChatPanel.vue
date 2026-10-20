<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatMessage, ChatSource } from '../../../api/trials'
import { developerDetails } from '../../../composables/useDeveloperMode'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import RawRecord from '../../groups/tasks/RawRecord.vue'
import ChatWindow from './ChatWindow.vue'
import TurnList from './TurnList.vue'
import { useChat } from './useChat'

/** A chat-app view of one trial with its turns beside it; the turn steps are the group live tab's. */
const props = defineProps<{ source: ChatSource }>()

const { t } = useI18n()
const chat = useChat(props.source)
const showTurns = ref(true)
const openTurn = ref<string | null>(null)

/** The turn that was running when the bot sent this message. */
async function showTurnOf(message: ChatMessage) {
  const turn = chat.turns.value.find(
    (item) => item.started <= message.time && (item.ended === null || message.time <= item.ended + 1),
  )
  if (!turn) return
  showTurns.value = true
  openTurn.value = turn.id
  await nextTick()
  document.querySelector(`[data-turn="${turn.id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
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
        :class="showTurns && 'lg:grid-cols-[minmax(0,3fr)_minmax(280px,2fr)]'"
      >
        <ChatWindow
          :source="source"
          :chat="chat"
          :turns-open="showTurns"
          @toggle-turns="showTurns = !showTurns"
          @open-turn="showTurnOf"
        />
        <TurnList
          v-if="showTurns"
          v-model:open="openTurn"
          :source="source"
          :turns="chat.turns.value"
          :time-zone="chat.data.value.timezone"
        />
      </div>
      <RawRecord
        v-if="developerDetails"
        :label="t('playground.binding')"
        :code="{ scene: chat.data.value.scene, models: chat.data.value.models }"
      />
    </template>
  </div>
</template>
