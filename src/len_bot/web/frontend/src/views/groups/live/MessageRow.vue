<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ExternalLink, ImageOff } from '@lucide/vue'
import type { Sender, TimelineMessage } from '../../../api/timeline'
import { formatDateTime } from '../../../i18n/format'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import VerdictMark from './VerdictMark.vue'

const props = defineProps<{
  message: TimelineMessage
  timeZone: string
  persona: string
  personaAvatar?: string | null
  /** Display name of a platform account (onebot:70001), for mentions. */
  nameOf: (uid: string) => string
}>()

const { t } = useI18n()
const senderName = (sender: Sender) =>
  sender.card || sender.nickname || sender.uid.split(':').pop() || sender.uid
const name = computed(() => (props.message.is_self ? props.persona : senderName(props.message.sender)))

const broken = ref(new Set<number>())
const preview = ref<TimelineMessage['images'][number] | null>(null)
watch(
  () => props.message.message_seq,
  () => {
    broken.value = new Set()
    preview.value = null
  },
)
function markBroken(index: number) {
  if (broken.value.has(index)) return
  const next = new Set(broken.value)
  next.add(index)
  broken.value = next
}

/**
 * The stored text is what the model reads: mentions are [提及 <platform>:<id>] (e.g. onebot:70001,
 * telegram:12345, feishu:ou_xxx) or [提及全体成员], and images are [图片1：摘要]. Here mentions highlight as
 * @name and image markers are dropped, since the images are shown below the text.
 */
interface Segment {
  kind: 'text' | 'mention'
  text: string
}

const segments = computed<Segment[]>(() => {
  const cleaned = props.message.text.replace(/\[图片[0-9]+(?:：(?:\[[^\]]*\]|[^\]])*)?\]/g, '').trim()
  if (!cleaned) return []
  const parts: Segment[] = []
  const pattern = /\[提及全体成员\]|\[提及 ([^\]]+)\]/g
  let last = 0
  for (const match of cleaned.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > last) parts.push({ kind: 'text', text: cleaned.slice(last, index) })
    const target = match[1]?.trim()
    parts.push({
      kind: 'mention',
      text: target ? `@${props.nameOf(target)}` : `@${t('groups.live.everyone')}`,
    })
    last = index + match[0].length
    if (last < cleaned.length && !/^\s/.test(cleaned.slice(last))) {
      parts.push({ kind: 'text', text: ' ' })
    }
  }
  if (last < cleaned.length) parts.push({ kind: 'text', text: cleaned.slice(last) })
  return parts
})

const replyText = computed(() => {
  const raw = props.message.reply?.text
  if (!raw) return ''
  return raw
    .replace(/\[图片[0-9]+(?:：((?:\[[^\]]*\]|[^\]])*))?\]/g, (_, summary: string | undefined) => {
      const text = summary?.trim()
      return text ? `[${t('groups.live.image')}] ${text}` : `[${t('groups.live.image')}]`
    })
    .replace(/\[提及全体成员\]|\[提及 ([^\]]+)\]/g, (_, target: string | undefined) =>
      target ? `@${props.nameOf(target.trim())}` : `@${t('groups.live.everyone')}`,
    )
    .replace(/\s+/g, ' ')
    .trim()
})

const status = computed(() =>
  props.message.is_self && ['failed', 'unconfirmed'].includes(props.message.status)
    ? props.message.status
    : null,
)
</script>

<template>
  <div class="flex gap-2.5 py-1.5" :class="message.is_self && 'flex-row-reverse'">
    <span class="flex shrink-0 pt-0.5" aria-hidden="true">
      <Avatar :name="name" :src="message.is_self ? personaAvatar : null" :size="30" />
    </span>
    <div
      class="flex min-w-0 max-w-[min(640px,calc(100%-40px))] flex-col gap-1 sm:max-w-[min(640px,82%)]"
      :class="message.is_self && 'items-end'"
    >
      <div
        class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted"
        :class="message.is_self && 'justify-end'"
      >
        <strong class="font-medium text-ink-2" :title="message.sender.uid">{{ name }}</strong>
        <time class="tabular" :datetime="new Date(message.time * 1000).toISOString()">
          {{ formatDateTime(message.time, { timeZone }) }}
        </time>
        <VerdictMark v-if="message.verdict && !message.is_self" :verdict="message.verdict" />
        <Badge v-if="message.recalled">{{ t('groups.live.recalled') }}</Badge>
        <Badge v-if="status" :tone="status === 'failed' ? 'error' : 'warning'">
          {{ t(`groups.live.sendStatus.${status}`) }}
        </Badge>
      </div>
      <div
        v-if="segments.length || message.reply"
        class="min-w-0 rounded-xl px-3.5 py-2 text-base break-words text-ink"
        :class="[
          message.is_self
            ? 'rounded-tr-sm border border-line-strong bg-surface-raised'
            : 'rounded-tl-sm bg-fill',
          message.recalled && 'opacity-60',
        ]"
      >
        <p
          v-if="message.reply"
          class="mb-1.5 line-clamp-2 border-l-2 border-line-strong pl-2 text-sm text-muted"
        >
          {{ t('groups.live.reply', { name: senderName(message.reply.sender) }) }}{{ replyText }}
        </p>
        <span class="whitespace-pre-wrap">
          <template v-for="(part, index) in segments" :key="index">
            <span v-if="part.kind === 'mention'" class="font-medium text-primary">{{ part.text }}</span>
            <template v-else>{{ part.text }}</template>
          </template>
        </span>
      </div>
      <div
        v-if="message.images.length"
        class="flex flex-wrap gap-1.5"
        :class="message.is_self && 'justify-end'"
      >
        <template v-for="image in message.images" :key="image.index">
          <button
            v-if="image.url && !broken.has(image.index)"
            type="button"
            class="block cursor-zoom-in overflow-hidden rounded-lg border border-line bg-fill transition-colors hover:border-line-strong focus-visible:focus-ring"
            :aria-label="image.summary || t('groups.live.image')"
            @click="preview = image"
          >
            <img
              :src="image.url"
              :alt="image.summary || t('groups.live.image')"
              loading="lazy"
              referrerpolicy="no-referrer"
              class="block max-h-44 max-w-44 object-cover"
              @error="markBroken(image.index)"
            />
          </button>
          <span
            v-else
            class="inline-flex items-center gap-1.5 rounded-lg border border-line bg-fill px-2.5 py-1.5 text-xs text-muted"
          >
            <ImageOff :size="14" aria-hidden="true" />
            {{ image.summary || t('groups.live.image') }}
          </span>
        </template>
      </div>
    </div>
    <Dialog
      v-if="preview"
      :open="true"
      :title="preview.summary || t('groups.live.image')"
      size="xl"
      @update:open="(value: boolean) => !value && (preview = null)"
    >
      <div class="flex flex-col items-center gap-3">
        <img
          v-if="preview.url && !broken.has(preview.index)"
          :src="preview.url"
          :alt="preview.summary || t('groups.live.image')"
          referrerpolicy="no-referrer"
          class="max-h-[72dvh] max-w-full rounded-md object-contain"
          @error="markBroken(preview.index)"
        />
        <span
          v-else
          class="inline-flex items-center gap-1.5 rounded-lg border border-line bg-fill px-3 py-2 text-sm text-muted"
        >
          <ImageOff :size="16" aria-hidden="true" />
          {{ preview.summary || t('groups.live.image') }}
        </span>
      </div>
      <template v-if="preview.url" #footer>
        <Button
          size="sm"
          variant="ghost"
          :icon-right="ExternalLink"
          :href="preview.url"
          target="_blank"
          rel="noopener noreferrer"
        >
          {{ t('groups.live.openImage') }}
        </Button>
      </template>
    </Dialog>
  </div>
</template>
