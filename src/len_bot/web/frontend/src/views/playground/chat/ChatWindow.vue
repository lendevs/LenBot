<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { useEventListener, usePreferredReducedMotion } from '@vueuse/core'
import { ToggleGroupItem, ToggleGroupRoot } from 'reka-ui'
import {
  ArrowDown,
  AtSign,
  ListTree,
  Pencil,
  Plus,
  Reply,
  SendHorizontal,
  Square,
  Users,
  X,
} from '@lucide/vue'
import { chatApi, type ChatMessage, type ChatSource, type MessageReceipt } from '../../../api/trials'
import { formatDateTime } from '../../../i18n/format'
import { groupLabel, groupSecondaryId } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import Collapsible from '../../../ui/Collapsible.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
import Textarea from '../../../ui/Textarea.vue'
import VerdictMark from '../../groups/live/VerdictMark.vue'
import MemberDialog from './MemberDialog.vue'
import { useMembers, type Member, type MemberRole } from './members'
import { SCENARIOS, useScenarios, type ScenarioKey } from './scenarios'
import type { Chat } from './useChat'

const props = withDefaults(
  defineProps<{
    source: ChatSource
    chat: Chat
    turnsOpen: boolean
    context?: string[]
    embedded?: boolean
    activeTurnId?: string | null
    messageTurnIds?: Map<number, string>
  }>(),
  { context: undefined, embedded: false, activeTurnId: null, messageTurnIds: undefined },
)
const emit = defineEmits<{ toggleTurns: []; openTurn: [message: ChatMessage] }>()

const { t } = useI18n()
const reducedMotion = usePreferredReducedMotion()
const scrollBehavior = (): ScrollBehavior => (reducedMotion.value === 'reduce' ? 'auto' : 'smooth')

const view = computed(() => props.chat.data.value!)
const scene = computed(() => props.chat.data.value?.scene)
const { members, current, speaker, platform, nextUid, save, remove } = useMembers(scene, props.chat.isPrivate)
const roleTone = { owner: 'warning', admin: 'success' } as const
const scenarios = useScenarios(props.source, props.chat, members)
const scenarioItems = computed<MenuEntry[]>(() =>
  (Object.keys(SCENARIOS) as ScenarioKey[]).map((key) => ({
    label: t(`playground.scenarios.${key}.title`),
    disabled: Boolean(scenarios.playing.value),
    select: () => void scenarios.play(key),
  })),
)

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
const BOTTOM_THRESHOLD = 48
const atBottom = ref(true)
const unreadCount = ref(0)
function onScroll() {
  const element = list.value
  if (!element) return
  atBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight <= BOTTOM_THRESHOLD
  if (atBottom.value) unreadCount.value = 0
}
async function scrollToBottom(force = false, smooth = false) {
  if (!force && !atBottom.value) return
  await nextTick()
  if (list.value) {
    if (smooth) list.value.scrollTo({ top: list.value.scrollHeight, behavior: scrollBehavior() })
    else list.value.scrollTop = list.value.scrollHeight
    atBottom.value = true
    unreadCount.value = 0
  }
}
function jump(message: ChatMessage) {
  const element = list.value?.querySelector<HTMLElement>(`[data-seq="${message.seq}"]`)
  if (!element) return
  element.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })
  if (reducedMotion.value !== 'reduce') {
    element.animate([{ backgroundColor: 'var(--selected)' }, { backgroundColor: 'transparent' }], {
      duration: 1200,
    })
  }
}
watch(
  [() => props.chat.messages.value.length, () => props.chat.thinking.value],
  ([length], prev) => {
    const prevLength = prev?.[0] ?? 0
    const initial = prev === undefined || prevLength === 0
    if (initial || atBottom.value) {
      unreadCount.value = 0
      void scrollToBottom(true)
    } else if (length > prevLength) {
      unreadCount.value += length - prevLength
    }
  },
  { immediate: true },
)

const isHighlightedMessage = (message: ChatMessage) =>
  Boolean(
    message.is_self && props.activeTurnId && props.messageTurnIds?.get(message.seq) === props.activeTurnId,
  )

// Composer.
const text = ref('')
const mentions = ref<string[]>([])
const replyTo = ref<ChatMessage | null>(null)
const input = ref<InstanceType<typeof Textarea>>()
const speakerGroup = ref<InstanceType<typeof ToggleGroupRoot>>()

interface MentionCandidate {
  uid: string
  label: string
  kind: MemberRole | 'bot' | 'all'
}
const mentionCandidates = computed<MentionCandidate[]>(() => {
  if (props.chat.isPrivate.value) return []
  return [
    { uid: view.value.bot_id, label: props.chat.botName.value, kind: 'bot' as const },
    ...members.value
      .filter((member) => member.uid !== speaker.value?.uid)
      .map((member) => ({ uid: member.uid, label: member.nickname, kind: member.role })),
    { uid: 'all', label: t('playground.everyone'), kind: 'all' as const },
  ].filter((item) => !mentions.value.includes(item.uid))
})
const mentionItems = computed<MenuEntry[]>(() =>
  mentionCandidates.value.map((item) => ({
    label: item.label,
    select: () => (mentions.value = [...mentions.value, item.uid]),
  })),
)

// Inline @ mention popup driven by typing `@` in the textarea.
const mentionTrigger = ref<{ start: number; end: number; query: string } | null>(null)
const mentionIndex = ref(0)
const filteredMentions = computed(() => {
  const trigger = mentionTrigger.value
  if (!trigger) return []
  const needle = trigger.query.trim().toLowerCase()
  if (!needle) return mentionCandidates.value
  return mentionCandidates.value.filter(
    (item) => item.label.toLowerCase().includes(needle) || item.uid.toLowerCase().includes(needle),
  )
})
const mentionMenuOpen = computed(() => mentionTrigger.value !== null && mentionCandidates.value.length > 0)

function textareaElement(): HTMLTextAreaElement | null {
  const el = input.value?.$el
  return el instanceof HTMLTextAreaElement ? el : null
}
function syncMentionTrigger() {
  if (props.chat.isPrivate.value) {
    mentionTrigger.value = null
    return
  }
  const el = textareaElement()
  if (!el) return
  const pos = el.selectionStart ?? text.value.length
  const before = text.value.slice(0, pos)
  const at = before.lastIndexOf('@')
  if (at === -1) {
    mentionTrigger.value = null
    return
  }
  if (at > 0 && /[a-zA-Z0-9._-]/.test(before[at - 1]!)) {
    mentionTrigger.value = null
    return
  }
  const query = before.slice(at + 1)
  if (/\s/.test(query)) {
    mentionTrigger.value = null
    return
  }
  mentionTrigger.value = { start: at, end: pos, query }
  mentionIndex.value = 0
}
function pickMention(candidate: MentionCandidate) {
  const trigger = mentionTrigger.value
  if (!mentions.value.includes(candidate.uid)) {
    mentions.value = [...mentions.value, candidate.uid]
  }
  mentionTrigger.value = null
  if (trigger) {
    text.value = text.value.slice(0, trigger.start) + text.value.slice(trigger.end)
    void nextTick(() => {
      const el = textareaElement()
      if (el) {
        el.focus()
        el.setSelectionRange(trigger.start, trigger.start)
      }
    })
  } else {
    input.value?.focus?.()
  }
}
function quickMentionBot() {
  if (!mentions.value.includes(view.value.bot_id)) {
    mentions.value = [...mentions.value, view.value.bot_id]
  }
  input.value?.focus?.()
}

watch(
  () => speaker.value?.uid,
  (uid) => {
    if (uid && mentions.value.includes(uid)) {
      mentions.value = mentions.value.filter((item) => item !== uid)
    }
    void nextTick(() => {
      const container = speakerGroup.value?.$el as HTMLElement | undefined
      const active = container?.querySelector<HTMLElement>('[data-state="on"]')
      active?.scrollIntoView({ behavior: scrollBehavior(), block: 'nearest', inline: 'nearest' })
    })
  },
)

// Alt+1..9 switches the speaking member quickly without leaving the keyboard.
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (event.defaultPrevented || !view.value.running || props.chat.isPrivate.value) return
  if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  const match = /^Digit([1-9])$/.exec(event.code)
  if (!match) return
  const hasDialog = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"]')).some(
    (element) => !element.hasAttribute('hidden') && element.getAttribute('data-state') !== 'closed',
  )
  if (hasDialog) return
  const target = members.value[Number(match[1]) - 1]
  if (!target) return
  event.preventDefault()
  current.value = target.uid
})

function reply(message: ChatMessage) {
  replyTo.value = message
  input.value?.focus?.()
}
// After picking a mention the next keystrokes belong to the message, not the @ button.
function focusInput(event: Event) {
  event.preventDefault()
  input.value?.focus?.()
}

const receipt = ref<MessageReceipt | null>(null)
watch(text, (value) => {
  if (value && receipt.value) receipt.value = null
})
watch(
  () => props.chat.thinking.value,
  (thinking) => {
    if (thinking && receipt.value) receipt.value = null
  },
)

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
  onMutate: () => {
    receipt.value = null
  },
  onSuccess: (result) => {
    receipt.value = result
    if (['queued', 'stored'].includes(result.status)) {
      text.value = ''
      mentions.value = []
      replyTo.value = null
      mentionTrigger.value = null
      void scrollToBottom(true)
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
function onKeyup(event: KeyboardEvent) {
  if (['ArrowUp', 'ArrowDown', 'Enter', 'Tab', 'Escape'].includes(event.key)) return
  syncMentionTrigger()
}
function keydown(event: KeyboardEvent) {
  if (mentionMenuOpen.value) {
    if (event.key === 'ArrowDown' && filteredMentions.value.length) {
      event.preventDefault()
      mentionIndex.value = (mentionIndex.value + 1) % filteredMentions.value.length
      return
    }
    if (event.key === 'ArrowUp' && filteredMentions.value.length) {
      event.preventDefault()
      mentionIndex.value =
        (mentionIndex.value - 1 + filteredMentions.value.length) % filteredMentions.value.length
      return
    }
    if ((event.key === 'Enter' || event.key === 'Tab') && !event.isComposing) {
      const candidate = filteredMentions.value[mentionIndex.value]
      if (candidate) {
        event.preventDefault()
        pickMention(candidate)
        return
      }
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      mentionTrigger.value = null
      return
    }
  }
  if (event.key === 'Escape') {
    if (replyTo.value) {
      event.preventDefault()
      replyTo.value = null
    }
    return
  }
  if (
    event.key === 'Enter' &&
    !event.isComposing &&
    ((!event.shiftKey && !event.altKey) || event.metaKey || event.ctrlKey)
  ) {
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
function saveMember(member: Member) {
  const adding = editing.value?.adding ?? false
  const prevUid = editing.value?.member.uid
  save(member, adding, prevUid)
  if (!adding && prevUid && prevUid !== member.uid) {
    mentions.value = mentions.value
      .map((uid) => (uid === prevUid ? member.uid : uid))
      .filter((uid) => uid !== speaker.value?.uid)
  }
}
function removeMember(uid: string) {
  remove(uid)
  mentions.value = mentions.value.filter((item) => item !== uid)
}

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
    class="flex min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-surface"
    :class="
      embedded
        ? 'h-[clamp(360px,calc(100dvh-300px),620px)] lg:h-[min(calc(100dvh-280px),680px)]'
        : 'h-[clamp(380px,calc(100dvh-260px),680px)] lg:h-[min(calc(100dvh-230px),780px)]'
    "
  >
    <header class="flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
      <div class="flex min-w-0 flex-1 flex-col">
        <div class="flex min-w-0 items-baseline gap-2">
          <strong
            class="truncate text-sm font-semibold text-ink"
            :class="!chat.isPrivate.value && !groupSecondaryId(view.scene) && 'tabular'"
          >
            {{ chat.isPrivate.value ? chat.botName.value : groupLabel(view.scene) }}
          </strong>
          <span
            v-if="!chat.isPrivate.value && groupSecondaryId(view.scene)"
            class="shrink-0 font-mono text-xs text-subtle tabular"
          >
            {{ groupSecondaryId(view.scene) }}
          </span>
        </div>
        <span class="text-xs text-muted tabular">
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
      <DropdownMenu v-if="view.running && scenarios.available.value" :items="scenarioItems" align="end">
        <IconButton
          :icon="Users"
          :label="t('playground.scenarios.menu')"
          :disabled="Boolean(scenarios.playing.value)"
        />
      </DropdownMenu>
      <IconButton
        :icon="ListTree"
        :label="t('playground.turns')"
        :pressed="turnsOpen"
        @click="emit('toggleTurns')"
      />
    </header>

    <div class="relative flex min-h-0 flex-1 flex-col">
      <ol
        ref="list"
        class="flex min-h-0 flex-1 list-none flex-col gap-3 overflow-y-auto bg-sidebar px-3.5 py-4 scrollbar-thin sm:px-4"
        @scroll="onScroll"
      >
        <li v-if="context?.length" class="flex flex-col gap-2">
          <div class="rounded-lg border border-line bg-surface/80 px-3 py-2 dark:bg-surface-raised/80">
            <Collapsible
              variant="inline"
              :title="t('playground.contextSummary', { n: context.length }, context.length)"
            >
              <CodeBlock :code="context.join('\n\n')" :max-lines="12" />
            </Collapsible>
          </div>
          <div class="flex items-center gap-3 py-0.5 text-2xs text-subtle" role="separator">
            <span class="h-px flex-1 bg-line" aria-hidden="true" />
            <span>{{ t('playground.sessionStart') }}</span>
            <span class="h-px flex-1 bg-line" aria-hidden="true" />
          </div>
        </li>
        <li v-if="!chat.messages.value.length" class="my-auto self-center py-8 text-sm text-muted">
          {{ context?.length ? t('playground.readyWithContext') : t('playground.noMessages') }}
        </li>
        <li
          v-for="message in chat.messages.value"
          :key="message.seq"
          :data-seq="message.seq"
          class="group flex max-w-[88%] items-start gap-2.5 rounded-lg sm:max-w-[82%]"
          :class="message.is_self ? 'self-start' : 'flex-row-reverse self-end'"
        >
          <span class="flex shrink-0 pt-0.5">
            <Avatar
              :name="senderName(message)"
              :src="message.is_self ? chat.botAvatar.value : null"
              :size="32"
            />
          </span>
          <div class="flex min-w-0 flex-col gap-1" :class="!message.is_self && 'items-end'">
            <div
              class="flex min-h-5 flex-wrap items-center gap-1.5 text-xs text-muted"
              :class="!message.is_self && 'flex-row-reverse'"
            >
              <Badge
                v-if="message.sender.role === 'owner' || message.sender.role === 'admin'"
                :tone="roleTone[message.sender.role]"
              >
                {{ t(`playground.roles.${message.sender.role}`) }}
              </Badge>
              <span class="font-medium text-ink-2">{{ senderName(message) }}</span>
              <time class="text-subtle tabular" :datetime="new Date(message.time * 1000).toISOString()">
                {{ formatDateTime(message.time, { timeZone: view.timezone }) }}
              </time>
              <VerdictMark v-if="message.verdict && !message.is_self" :verdict="message.verdict" />
              <Badge
                v-if="message.is_self && ['failed', 'unconfirmed'].includes(message.send_status)"
                tone="error"
              >
                {{ t(`groups.live.sendStatus.${message.send_status}`) }}
              </Badge>
              <button
                v-if="message.is_self && messageTurnIds?.has(message.seq)"
                type="button"
                class="inline-flex cursor-pointer items-center gap-1 rounded-sm px-1 transition-colors hover:text-ink focus-visible:focus-ring"
                :class="
                  isHighlightedMessage(message)
                    ? 'font-medium text-primary'
                    : 'text-muted opacity-80 hover:opacity-100'
                "
                :aria-pressed="isHighlightedMessage(message)"
                :title="t('playground.showTurn')"
                @click="emit('openTurn', message)"
              >
                <ListTree :size="12" aria-hidden="true" />
                {{ t('playground.viewTurn') }}
              </button>
              <button
                v-if="view.running && message.platform_message_id"
                type="button"
                class="inline-flex cursor-pointer items-center gap-1 rounded-sm px-1 text-muted opacity-0 transition-opacity group-hover:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:focus-ring pointer-coarse:opacity-100"
                @click="reply(message)"
              >
                <Reply :size="12" aria-hidden="true" />
                {{ t('playground.reply') }}
              </button>
            </div>
            <div
              class="max-w-full px-3.5 py-2 text-left text-sm break-words whitespace-pre-wrap text-ink"
              :class="[
                message.is_self
                  ? [
                      'rounded-xl rounded-tl-sm border bg-surface shadow-card transition-colors dark:bg-surface-raised',
                      isHighlightedMessage(message)
                        ? 'border-primary/60 ring-2 ring-primary/15'
                        : 'border-line',
                    ]
                  : 'rounded-xl rounded-tr-sm border border-line-strong bg-fill',
                message.recalled && 'opacity-60 line-through',
              ]"
            >
              <template v-if="quoted(message)">
                <button
                  v-if="quoted(message)!.message"
                  type="button"
                  class="mb-1.5 block w-full cursor-pointer truncate rounded-sm border-l-2 border-line-strong bg-hover/70 px-2.5 py-1 text-left text-xs text-muted hover:bg-hover focus-visible:focus-ring"
                  @click="jump(quoted(message)!.message!)"
                >
                  <strong class="font-medium text-ink-2">
                    {{ t('playground.replyTo', { name: senderName(quoted(message)!.message!) }) }}
                  </strong>
                  {{ excerpt(quoted(message)!.message!) }}
                </button>
                <span
                  v-else
                  class="mb-1.5 block truncate rounded-sm border-l-2 border-line-strong bg-hover/70 px-2.5 py-1 text-xs text-muted"
                >
                  {{ t('playground.quoteMissing') }}
                </span>
              </template>
              <div class="block w-full text-left">
                <template v-for="(piece, index) in pieces(message)" :key="index">
                  <span v-if="piece.kind === 'mention'" class="rounded-xs bg-hover px-1 font-medium text-ink">
                    {{ piece.text }}
                  </span>
                  <img
                    v-else-if="piece.kind === 'image'"
                    class="my-1 block max-h-36 max-w-36 rounded-md border border-line"
                    :src="piece.src"
                    :alt="piece.alt"
                    :title="piece.alt"
                    loading="lazy"
                  />
                  <span v-else-if="piece.kind === 'other'" class="text-muted">{{ piece.text }}</span>
                  <span v-else>{{ piece.text }}</span>
                </template>
              </div>
            </div>
          </div>
        </li>
        <li v-if="chat.thinking.value" class="flex items-center gap-2 pl-10.5 text-xs text-muted">
          <span class="size-1.5 animate-pulse-dot rounded-full bg-info" aria-hidden="true" />
          {{ t('playground.typing', { name: chat.botName.value }) }}
        </li>
      </ol>
      <Transition name="ui-rise">
        <button
          v-if="!atBottom && unreadCount > 0"
          type="button"
          class="absolute right-4 bottom-3 z-10 inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border border-line-strong bg-surface-raised px-3 text-xs font-medium text-ink shadow-float transition-colors hover:bg-hover focus-visible:focus-ring"
          @click="void scrollToBottom(true, true)"
        >
          <ArrowDown :size="14" aria-hidden="true" />
          <span>{{ t('playground.backToBottom') }}</span>
          <span class="rounded-full bg-primary-bg px-1.5 py-0.5 text-2xs font-semibold text-primary tabular">
            {{ unreadCount }}
          </span>
        </button>
      </Transition>
    </div>

    <form
      v-if="view.running"
      class="flex flex-col gap-2 border-t border-line bg-surface px-3.5 py-3 sm:px-4"
      @submit.prevent="submit"
    >
      <div v-if="!chat.isPrivate.value" class="flex min-w-0 items-center gap-1.5">
        <ToggleGroupRoot
          ref="speakerGroup"
          type="single"
          :model-value="speaker?.uid"
          :aria-label="t('playground.speakAs')"
          orientation="horizontal"
          roving-focus
          loop
          class="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto py-0.5 scrollbar-none"
          @update:model-value="(value) => typeof value === 'string' && value && (current = value)"
        >
          <ToggleGroupItem
            v-for="(member, index) in members"
            :key="member.uid"
            :value="member.uid"
            class="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full border py-0.5 pr-2.5 pl-1 text-sm whitespace-nowrap transition-colors focus-visible:focus-ring pointer-coarse:h-10"
            :class="
              member.uid === speaker?.uid
                ? 'border-line-strong bg-fill font-semibold text-ink shadow-card'
                : 'border-line bg-surface text-ink-2 hover:border-line-strong hover:bg-hover'
            "
            :title="index < 9 ? `${member.nickname} (Alt+${index + 1})` : member.nickname"
          >
            <Avatar :name="member.nickname" :size="22" />
            <span>{{ member.nickname }}</span>
            <span v-if="member.role !== 'member'" class="text-xs font-normal text-muted">
              {{ t(`playground.roles.${member.role}`) }}
            </span>
          </ToggleGroupItem>
        </ToggleGroupRoot>
        <div class="flex shrink-0 items-center gap-1">
          <IconButton
            v-if="speaker"
            :icon="Pencil"
            :label="t('playground.editMember')"
            size="sm"
            @click="editing = { member: speaker, adding: false }"
          />
          <IconButton :icon="Plus" :label="t('playground.addMember')" size="sm" @click="addMember" />
        </div>
      </div>
      <div
        v-if="replyTo"
        class="flex items-center gap-2 rounded-md border border-line bg-fill py-1 pr-1 pl-2.5 text-sm text-muted"
      >
        <span class="min-w-0 flex-1 truncate">
          <strong class="font-medium text-ink-2">
            {{ t('playground.replyTo', { name: senderName(replyTo) }) }}
          </strong>
          {{ excerpt(replyTo) }}
        </span>
        <IconButton :icon="X" :label="t('playground.cancelReply')" size="sm" @click="replyTo = null" />
      </div>
      <div v-if="!chat.isPrivate.value" class="flex flex-wrap items-center gap-1.5">
        <button
          v-if="!mentions.includes(view.bot_id)"
          type="button"
          class="inline-flex h-6 cursor-pointer items-center gap-1 rounded-full border border-dashed border-line-strong bg-surface px-2.5 text-xs font-medium text-muted transition-colors hover:border-primary/60 hover:bg-selected hover:text-ink focus-visible:focus-ring"
          :aria-label="t('playground.quickMentionBot', { name: chat.botName.value })"
          @click="quickMentionBot"
        >
          @{{ chat.botName.value }}
        </button>
        <span
          v-for="uid in mentions"
          :key="uid"
          class="inline-flex h-6 items-center gap-1 rounded-full border border-line bg-fill pr-0.5 pl-2.5 text-xs font-medium text-ink-2"
        >
          @{{ nameOf(uid) }}
          <button
            type="button"
            class="inline-flex size-5 cursor-pointer items-center justify-center rounded-full text-subtle hover:bg-hover hover:text-ink focus-visible:focus-ring"
            :aria-label="t('playground.removeMention', { name: nameOf(uid) })"
            @click="mentions = mentions.filter((item) => item !== uid)"
          >
            <X :size="11" aria-hidden="true" />
          </button>
        </span>
      </div>
      <div class="flex items-end gap-2">
        <DropdownMenu
          v-if="!chat.isPrivate.value"
          :items="mentionItems"
          side="top"
          align="start"
          @close-auto-focus="focusInput"
        >
          <IconButton :icon="AtSign" :label="t('playground.mention')" :disabled="!mentionItems.length" />
        </DropdownMenu>
        <div class="relative min-w-0 flex-1">
          <div
            v-if="mentionMenuOpen"
            role="listbox"
            :aria-label="t('playground.mentionMenu')"
            class="absolute right-0 bottom-full left-0 z-(--z-popover) mb-1.5 max-h-52 overflow-y-auto rounded-lg border border-line bg-surface-raised p-1 shadow-float scrollbar-thin"
          >
            <template v-if="filteredMentions.length">
              <button
                v-for="(candidate, index) in filteredMentions"
                :key="candidate.uid"
                type="button"
                role="option"
                :aria-selected="index === mentionIndex"
                class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors"
                :class="index === mentionIndex ? 'bg-selected text-ink' : 'text-ink-2 hover:bg-hover'"
                @mouseenter="mentionIndex = index"
                @mousedown.prevent
                @click="pickMention(candidate)"
              >
                <Avatar
                  v-if="candidate.kind !== 'all'"
                  :name="candidate.label"
                  :src="candidate.kind === 'bot' ? chat.botAvatar.value : null"
                  :size="20"
                />
                <span class="min-w-0 flex-1 truncate font-medium text-ink">{{ candidate.label }}</span>
                <span
                  v-if="candidate.kind === 'owner' || candidate.kind === 'admin'"
                  class="shrink-0 text-xs text-muted"
                >
                  {{ t(`playground.roles.${candidate.kind}`) }}
                </span>
                <span v-else-if="candidate.kind !== 'all'" class="shrink-0 font-mono text-2xs text-subtle">
                  {{ candidate.uid }}
                </span>
              </button>
            </template>
            <p v-else class="px-2.5 py-1.5 text-xs text-muted">{{ t('playground.mentionEmpty') }}</p>
          </div>
          <Textarea
            ref="input"
            v-model="text"
            :rows="1"
            :max-rows="6"
            :placeholder="speaker ? t('playground.speakAsName', { name: speaker.nickname }) : ''"
            :aria-label="t('playground.message')"
            @input="syncMentionTrigger"
            @click="syncMentionTrigger"
            @keyup="onKeyup"
            @blur="mentionTrigger = null"
            @keydown="keydown"
          />
        </div>
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
      <div v-if="scenarios.playing.value" class="flex items-center justify-between gap-2 text-xs text-muted">
        <span>{{ t('playground.scenarios.playing') }}</span>
        <Button size="xs" variant="ghost" :icon="Square" @click="scenarios.stop()">
          {{ t('playground.scenarios.stop') }}
        </Button>
      </div>
      <ErrorNote
        v-if="scenarios.error.value"
        :title="t('playground.scenarios.failed')"
        :error="scenarios.error.value"
      />
      <p v-if="receiptNote" class="text-xs text-muted">{{ receiptNote }}</p>
      <ErrorNote v-if="receipt?.error" :title="t('playground.handleFailed')" :error="receipt.error" />
    </form>
    <MemberDialog
      v-model:open="editOpen"
      :member="editing?.member ?? null"
      :adding="editing?.adding ?? false"
      :removable="members.length > 1"
      :existing-uids="members.map((item) => item.uid)"
      :bot-id="view.bot_id"
      :platform="platform"
      @save="saveMember"
      @remove="removeMember"
    />
  </section>
</template>
