import { computed, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { chatApi, type ChatSource } from '../../../api/trials'
import type { Member } from './members'
import type { Chat } from './useChat'

/** Who speaks in a step: the first or second simulated member. */
type Speaker = 0 | 1
interface Step {
  speaker: Speaker
  /** Text key under `playground.scenarios.<scenario>`. */
  text: string
  mention?: 'bot' | 'other'
  /** Wait for the Bot to reply before the next step. */
  awaitBot?: boolean
}

/** Multi-person situations that show when the Bot speaks: a call, an open question, others talking, a follow-up. */
export const SCENARIOS = {
  call: [{ speaker: 0, text: 'call1', mention: 'bot' }],
  open: [
    { speaker: 0, text: 'open1' },
    { speaker: 1, text: 'open2' },
  ],
  others: [
    { speaker: 0, text: 'others1', mention: 'other' },
    { speaker: 1, text: 'others2' },
    { speaker: 0, text: 'others3' },
  ],
  followUp: [
    { speaker: 0, text: 'followUp1', mention: 'bot', awaitBot: true },
    { speaker: 0, text: 'followUp2' },
  ],
} satisfies Record<string, Step[]>
export type ScenarioKey = keyof typeof SCENARIOS

/** Messages in one situation are this far apart, close enough to read as one exchange. */
const STEP_GAP_MS = 1200
const BOT_REPLY_TIMEOUT_MS = 90_000

export function useScenarios(source: ChatSource, chat: Chat, members: Ref<Member[]>) {
  const { t } = useI18n()
  const playing = ref<ScenarioKey | null>(null)
  const error = ref<string | null>(null)
  const available = computed(() => !chat.isPrivate.value && members.value.length >= 2)

  const lastBotSeq = () =>
    Math.max(0, ...chat.messages.value.filter((message) => message.is_self).map((message) => message.seq))
  function botReplyAfter(seq: number): Promise<boolean> {
    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        stop()
        resolve(false)
      }, BOT_REPLY_TIMEOUT_MS)
      const stop = watch(
        () => lastBotSeq(),
        (latest) => {
          if (latest <= seq) return
          window.clearTimeout(timer)
          stop()
          resolve(true)
        },
        { immediate: true },
      )
    })
  }

  async function play(key: ScenarioKey) {
    if (playing.value || !available.value) return
    playing.value = key
    error.value = null
    const people = members.value.slice(0, 2)
    try {
      for (const [index, step] of (SCENARIOS[key] as Step[]).entries()) {
        if (index) await new Promise((resolve) => window.setTimeout(resolve, STEP_GAP_MS))
        const member = people[step.speaker]!
        const before = lastBotSeq()
        await chatApi.send(source, {
          uid: member.uid,
          nickname: member.nickname,
          role: member.role,
          text: t(`playground.scenarios.${key}.${step.text}`),
          mentions:
            step.mention === 'bot'
              ? [chat.data.value!.bot_id]
              : step.mention === 'other'
                ? [people[1 - step.speaker]!.uid]
                : [],
          reply_to: null,
        })
        if (step.awaitBot && !(await botReplyAfter(before))) {
          error.value = t('playground.scenarios.noReply')
          return
        }
      }
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    } finally {
      playing.value = null
    }
  }
  return { playing, error, available, play }
}
