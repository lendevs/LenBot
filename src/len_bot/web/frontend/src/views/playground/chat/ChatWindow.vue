<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { AtSign, ListTree, Pencil, Plus, Reply, SendHorizontal, X } from '@lucide/vue'
import { chatApi, type ChatMessage, type ChatSource, type MessageReceipt } from '../../../api/trials'
import { formatDateTime } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
import Textarea from '../../../ui/Textarea.vue'
import MemberDialog from './MemberDialog.vue'
import { useMembers, type Member } from './members'
import type { Chat } from './useChat'

const props = defineProps<{ source: ChatSource; chat: Chat; turnsOpen: boolean }>()
const emit = defineEmits<{ toggleTurns: []; openTurn: [message: ChatMessage] }>()

const { t } = useI18n()
const view = computed(() => props.chat.data.value!)
const scene = computed(() => props.chat.data.value?.scene)
const { members, current, speaker, nextUid, save, remove } = useMembers(scene, props.chat.isPrivate)
const roleTone = { owner: 'warning', admin: 'success' } as const

function nameOf(uid: string) {
  if (uid === 'all') return t('playground.everyone')
  if (uid === view.value.bot_id) return props.chat.botName.value
  return (
    members.value.find((member) => member.uid === uid)?.nickname ??
    props.chat.messages.value.find((message) => message.sender.uid === uid)?.sender.nickname ??
    uid
  )
}
const senderName = (message: ChatMessage) =>
  message.is_self ? props.chat.botName.value : (message.sender.nickname ?? nameOf(message.sender.uid))

const byPlatformId = computed(
  () =>
    new Map(
      props.chat.messages.value
        .filter((item) => item.platform_message_id)
        .map((item) => [item.platform_message_id!, item]),
    ),
)
function excerpt(message: ChatMessage) {
  return message.segments
    .map((segment) =>
      segment.type === 'text'
        ? String(segment.data.text)
        : segment.type === 'mention'
          ? `@${nameOf(String(segment.data.user))} `
          : segment.type === 'image'
            ? t('playground.image')
            : '',
    )
    .join('')
    .trim()
    .slice(0, 60)
}
function quoted(message: ChatMessage) {
  const id =
    (message.segments.find((segment) => segment.type === 'reply')?.data.id as string | undefined) ??
    message.reply_to
  return id ? { id, message: byPlatformId.value.get(id) ?? null } : null
}
type Piece =
  { kind: 'text' | 'mention' | 'other'; text: string } | { kind: 'image'; src: string; alt: string }
function pieces(message: ChatMessage): Piece[] {
  let image = 0
  return message.segments.flatMap((segment): Piece[] => {
    if (segment.type === 'text') return [{ kind: 'text', text: String(segment.data.text) }]
    if (segment.type === 'mention')
      return [{ kind: 'mention', text: `@${nameOf(String(segment.data.user))}` }]
    if (segment.type === 'image') {
      image++
      const stored = message.images.find((item) => item.image_index === image)
      return stored
        ? [
            {
              kind: 'image',
              src: chatApi.image(props.source, message.seq, image),
              alt: stored.description || t('playground.image'),
            },
          ]
        : [{ kind: 'other', text: t('playground.image') }]
    }
    if (segment.type === 'reply') return []
    return [{ kind: 'other', text: `[${segment.type}]` }]
  })
}

const list = ref<HTMLElement>()
function jump(message: ChatMessage) {
  const element = list.value?.querySelector<HTMLElement>(`[data-seq="${message.seq}"]`)
  element?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  element?.animate([{ backgroundColor: 'var(--selected)' }, { backgroundColor: 'transparent' }], {
    duration: 1200,
  })
}
watch(
  () => props.chat.messages.value.length,
  async () => {
    await nextTick()
    if (list.value) list.value.scrollTop = list.value.scrollHeight
  },
  { immediate: true },
)

// Composer.
const text = ref('')
const mentions = ref<string[]>([])
const replyTo = ref<ChatMessage | null>(null)
const input = ref<InstanceType<typeof Textarea>>()
const mentionItems = computed<MenuEntry[]>(() =>
  [
    { uid: view.value.bot_id, label: props.chat.botName.value },
    ...members.value
      .filter((member) => member.uid !== speaker.value?.uid)
      .map((member) => ({ uid: member.uid, label: member.nickname })),
    { uid: 'all', label: t('playground.everyone') },
  ]
    .filter((item) => !mentions.value.includes(item.uid))
    .map((item) => ({ label: item.label, select: () => (mentions.value = [...mentions.value, item.uid]) })),
)
function reply(message: ChatMessage) {
  replyTo.value = message
  input.value?.focus?.()
}
const receipt = ref<MessageReceipt | null>(null)
const send = useMutation({
  mutationFn: () =>
    chatApi.send(props.source, {
      uid: speaker.value!.uid,
      nickname: speaker.value!.nickname,
      role: speaker.value!.role,
      text: text.value,
      mentions: props.chat.isPrivate.value ? [] : mentions.value,
      reply_to: replyTo.value?.platform_message_id ?? null,
    }),
  onSuccess: (result) => {
    receipt.value = result
    if (['queued', 'stored'].includes(result.status)) {
      text.value = ''
      mentions.value = []
      replyTo.value = null
    }
    void props.chat.state.refetch()
  },
})
const ready = computed(
  () => view.value.running && Boolean(speaker.value) && Boolean(text.value.trim()) && !send.isPending.value,
)
function submit() {
  if (ready.value) send.mutate()
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}
const receiptNote = computed(() => {
  const status = receipt.value?.status
  return status === 'stored'
    ? t('playground.notWoken')
    : status === 'duplicate'
      ? t('playground.duplicate')
      : ''
})

const editing = ref<{ member: Member; adding: boolean } | null>(null)
const editOpen = computed({
  get: () => editing.value !== null,
  set: (value: boolean) => {
    if (!value) editing.value = null
  },
})
const addMember = () =>
  (editing.value = {
    member: {
      uid: nextUid(),
      nickname: t('playground.memberName', { n: members.value.length + 1 }),
      role: 'member',
    },
    adding: true,
  })
const liveTone = computed(() =>
  props.chat.live.value === 'connected'
    ? 'success'
    : props.chat.live.value === 'connecting'
      ? 'neutral'
      : 'error',
)
</script>

<template>
  <section
    class="flex h-[min(calc(100dvh-240px),820px)] min-h-[420px] min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-surface"
  >
    <header class="flex items-center gap-3 border-b border-line px-4 py-2.5">
      <div class="flex min-w-0 flex-1 flex-col">
        <strong class="truncate text-sm font-semibold text-ink">
          {{ chat.isPrivate.value ? chat.botName.value : groupLabel(view.scene) }}
        </strong>
        <span class="text-xs text-muted">
          {{
            chat.isPrivate.value
              ? t('playground.private')
              : t('playground.people', { n: members.length + 1 }, members.length + 1)
          }}
          <template v-if="!view.running">· {{ t('playground.ended') }}</template>
        </span>
      </div>
      <button
        v-if="chat.live.value !== 'connected'"
        type="button"
        class="cursor-pointer rounded-full focus-visible:focus-ring"
        :disabled="chat.live.value === 'connecting'"
        @click="chat.reconnect()"
      >
        <Badge :tone="liveTone" dot>{{ t(`playground.live.${chat.live.value}`) }}</Badge>
      </button>
      <IconButton
        :icon="ListTree"
        :label="t('playground.turns')"
        :pressed="turnsOpen"
        @click="emit('toggleTurns')"
      />
    </header>

    <ol
      ref="list"
      class="flex min-h-0 flex-1 list-none flex-col gap-3 overflow-y-auto bg-hover px-4 py-4 scrollbar-thin"
    >
      <li v-if="!chat.messages.value.length" class="self-center py-8 text-sm text-muted">
        {{ t('playground.noMessages') }}
      </li>
      <li
        v-for="message in chat.messages.value"
        :key="message.seq"
        :data-seq="message.seq"
        class="group flex max-w-[85%] items-start gap-2 rounded-lg"
        :class="message.is_self ? 'self-start' : 'flex-row-reverse self-end'"
      >
        <Avatar
          :name="senderName(message)"
          :src="message.is_self ? chatApi.avatar(source) : null"
          :size="34"
        />
        <div class="flex min-w-0 flex-col gap-1" :class="!message.is_self && 'items-end'">
          <div
            class="flex min-h-5 items-center gap-1.5 text-xs text-muted"
            :class="!message.is_self && 'flex-row-reverse'"
          >
            <Badge
              v-if="message.sender.role === 'owner' || message.sender.role === 'admin'"
              :tone="roleTone[message.sender.role]"
            >
              {{ t(`playground.roles.${message.sender.role}`) }}
            </Badge>
            <span>{{ senderName(message) }}</span>
            <span class="opacity-70 tabular">
              {{ formatDateTime(message.time, { timeZone: view.timezone }) }}
            </span>
            <Badge
              v-if="message.is_self && ['failed', 'unconfirmed'].includes(message.send_status)"
              tone="error"
            >
              {{ t(`groups.live.sendStatus.${message.send_status}`) }}
            </Badge>
            <button
              v-if="view.running && message.platform_message_id"
              type="button"
              class="inline-flex cursor-pointer items-center gap-1 rounded-sm px-1 text-muted opacity-0 group-hover:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:focus-ring"
              @click="reply(message)"
            >
              <Reply :size="12" aria-hidden="true" />
              {{ t('playground.reply') }}
            </button>
          </div>
          <component
            :is="message.is_self ? 'button' : 'div'"
            :type="message.is_self ? 'button' : undefined"
            class="max-w-full rounded-xl px-3 py-2 text-left text-sm break-words whitespace-pre-wrap text-ink"
            :class="[
              message.is_self
                ? 'cursor-pointer bg-surface hover:ring-1 hover:ring-line-strong focus-visible:focus-ring'
                : 'bg-primary-bg',
              message.recalled && 'opacity-60 line-through',
            ]"
            :title="message.is_self ? t('playground.showTurn') : undefined"
            @click="message.is_self && emit('openTurn', message)"
          >
            <span
              v-if="quoted(message)"
              role="button"
              tabindex="0"
              class="mb-1.5 block truncate rounded-sm border-l-[3px] border-line-strong bg-hover px-2 py-1 text-xs text-muted"
              @click.stop="quoted(message)!.message && jump(quoted(message)!.message!)"
              @keydown.enter.stop="quoted(message)!.message && jump(quoted(message)!.message!)"
            >
              <template v-if="quoted(message)!.message">
                <strong class="font-medium">{{ senderName(quoted(message)!.message!) }}：</strong>
                {{ excerpt(quoted(message)!.message!) }}
              </template>
              <template v-else>{{ t('playground.quoteMissing') }}</template>
            </span>
            <template v-for="(piece, index) in pieces(message)" :key="index">
              <span v-if="piece.kind === 'mention'" class="font-semibold text-primary">{{ piece.text }}</span>
              <img
                v-else-if="piece.kind === 'image'"
                class="my-1 block max-h-36 max-w-36 rounded-md"
                :src="piece.src"
                :alt="piece.alt"
                :title="piece.alt"
                loading="lazy"
              />
              <span v-else-if="piece.kind === 'other'" class="text-muted">{{ piece.text }}</span>
              <span v-else>{{ piece.text }}</span>
            </template>
          </component>
        </div>
      </li>
      <li v-if="chat.thinking.value" class="pl-11 text-xs text-muted">
        {{ t('playground.typing', { name: chat.botName.value }) }}
      </li>
    </ol>

    <form
      v-if="view.running"
      class="flex flex-col gap-2 border-t border-line px-4 py-3"
      @submit.prevent="submit"
    >
      <div
        v-if="!chat.isPrivate.value"
        class="flex flex-wrap items-center gap-1.5"
        role="radiogroup"
        :aria-label="t('playground.speakAs')"
      >
        <button
          v-for="member in members"
          :key="member.uid"
          type="button"
          role="radio"
          :aria-checked="member.uid === speaker?.uid"
          class="inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-full border py-0.5 pr-2.5 pl-0.5 text-sm transition-colors focus-visible:focus-ring"
          :class="
            member.uid === speaker?.uid
              ? 'border-primary bg-primary-bg text-ink'
              : 'border-line bg-surface text-ink-2 hover:bg-hover'
          "
          @click="current = member.uid"
        >
          <Avatar :name="member.nickname" :size="22" />
          {{ member.nickname }}
          <span v-if="member.role !== 'member'" class="text-xs text-muted">
            {{ t(`playground.roles.${member.role}`) }}
          </span>
        </button>
        <IconButton
          v-if="speaker"
          :icon="Pencil"
          :label="t('playground.editMember')"
          size="sm"
          @click="editing = { member: speaker, adding: false }"
        />
        <IconButton :icon="Plus" :label="t('playground.addMember')" size="sm" @click="addMember" />
      </div>
      <div
        v-if="replyTo"
        class="flex items-center gap-2 rounded-md bg-hover py-1 pr-1 pl-2.5 text-sm text-muted"
      >
        <span class="min-w-0 flex-1 truncate">
          <strong class="font-medium">{{ t('playground.replyTo', { name: senderName(replyTo) }) }}</strong>
          {{ excerpt(replyTo) }}
        </span>
        <IconButton :icon="X" :label="t('playground.cancelReply')" size="sm" @click="replyTo = null" />
      </div>
      <div v-if="mentions.length" class="flex flex-wrap gap-1.5">
        <span
          v-for="uid in mentions"
          :key="uid"
          class="inline-flex h-6 items-center gap-1 rounded-full bg-primary-bg pr-0.5 pl-2 text-xs text-primary"
        >
          @{{ nameOf(uid) }}
          <button
            type="button"
            class="inline-flex size-5 cursor-pointer items-center justify-center rounded-full hover:bg-hover focus-visible:focus-ring"
            :aria-label="t('playground.removeMention', { name: nameOf(uid) })"
            @click="mentions = mentions.filter((item) => item !== uid)"
          >
            <X :size="11" aria-hidden="true" />
          </button>
        </span>
      </div>
      <div class="flex items-end gap-2">
        <DropdownMenu v-if="!chat.isPrivate.value" :items="mentionItems" side="top" align="start">
          <IconButton :icon="AtSign" :label="t('playground.mention')" :disabled="!mentionItems.length" />
        </DropdownMenu>
        <Textarea
          ref="input"
          v-model="text"
          :rows="1"
          :max-rows="6"
          class="min-w-0 flex-1"
          :placeholder="speaker ? t('playground.speakAsName', { name: speaker.nickname }) : ''"
          :aria-label="t('playground.message')"
          @keydown="keydown"
        />
        <Button
          type="submit"
          variant="primary"
          :icon="SendHorizontal"
          :loading="send.isPending.value"
          :disabled="!ready"
        >
          {{ t('playground.send') }}
        </Button>
      </div>
      <ErrorNote v-if="send.isError.value" :title="t('playground.sendFailed')" :error="send.error.value" />
      <p v-if="receiptNote" class="text-xs text-muted">{{ receiptNote }}</p>
      <ErrorNote v-if="receipt?.error" :title="t('playground.handleFailed')" :error="receipt.error" />
    </form>
    <MemberDialog
      v-model:open="editOpen"
      :member="editing?.member ?? null"
      :adding="editing?.adding ?? false"
      :removable="members.length > 1"
      @save="(member) => save(member, editing?.adding ?? false)"
      @remove="remove"
    />
  </section>
</template>
