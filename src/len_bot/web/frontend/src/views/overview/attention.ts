import { computed, watch } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import type { RouteLocationRaw } from 'vue-router'
import type { HostState, ItemHealth } from '../../api/host'
import type { Overview } from '../../api/overview'
import { host } from '../../api/hostStore'
import { formatDateTime } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
import { useConnectionStatus } from '../../layouts/shell/status'
import { groupsTarget } from '../groups/route'

export interface Attention {
  key: string
  revision?: string | number
  text: string
  /** Error text kept as reported, shown on request. */
  error?: string | null
  to?: RouteLocationRaw
  action?: string
  tone: 'error' | 'warning' | 'info'
  /** The same trouble in several groups, one row per group. */
  children?: Attention[]
  summary?: (groups: number) => string
}

const dismissed = useLocalStorage<{ scope: string; items: Record<string, string> }>(
  'lenbot.overview.dismissed',
  { scope: '', items: {} },
)
const revisionOf = (item: Attention) => JSON.stringify([item.revision ?? null, item.error ?? null])

/** Statuses of a turn that ended without finishing its reply. */
const FAILED_TURNS = new Set(['error', 'timeout', 'interrupted', 'step_limit', 'send_failed'])
/** From this many groups on, the same kind of trouble reads as one item. */
const MERGE_FROM = 3

/** What needs the operator, as the overview lists it and the top bar counts it. */
export function useAttention() {
  const { t } = useI18n()
  const { online, status } = useConnectionStatus()
  const scope = computed(() => `${host.state?.bot_id}:${(host.overview as Overview | null)?.since}`)

  // Each group stays one click away inside the merged item.
  function perScene(
    items: Attention[],
    kind: string,
    rows: Attention[],
    summary: (groups: number) => string,
  ) {
    if (rows.length < MERGE_FROM) items.push(...rows)
    else items.push({ key: kind, text: summary(rows.length), tone: rows[0]!.tone, children: rows, summary })
  }

  const allItems = computed<Attention[]>(() => {
    const state = host.state as HostState | null
    const day = host.overview as Overview | null
    const items: Attention[] = []
    if (state && !online.value) {
      items.push({
        key: 'connection',
        revision: `${state.connection.status}:${state.connection.last_error}`,
        text: status.value.text,
        tone: status.value.tone === 'error' ? 'error' : 'warning',
        to: { name: 'host-system', query: { tab: 'connection' } },
        action: t('overview.todo.connectionSettings'),
      })
    }
    const health = (kind: 'plugin' | 'mcp', list: ItemHealth[]) => {
      for (const item of list) {
        const to: RouteLocationRaw =
          kind === 'plugin'
            ? { name: 'host-plugins', query: { item: item.name } }
            : { name: 'host-capabilities', query: { tab: 'mcp', item: item.name } }
        if (item.status === 'failed') {
          items.push({
            key: `${kind}:${item.name}`,
            revision: JSON.stringify([item.status, item.error_count, item.latest_error]),
            text: t(`overview.todo.${kind}Failed`, { name: item.name }),
            error: item.error,
            tone: 'error',
            to,
            action: t('overview.todo.view'),
          })
        } else if (item.latest_error) {
          const latest = item.latest_error as { error?: string }
          items.push({
            key: `${kind}:${item.name}`,
            revision: JSON.stringify([item.error_count, item.latest_error]),
            text: t(
              `overview.todo.${kind}Errors`,
              { name: item.name, n: item.error_count },
              item.error_count,
            ),
            error: latest.error ?? null,
            tone: 'warning',
            to,
            action: t('overview.todo.view'),
          })
        }
      }
    }
    health('plugin', state?.plugins ?? [])
    health('mcp', state?.mcp ?? [])
    if (!day) return items

    const view = t('overview.todo.view')
    perScene(
      items,
      'send',
      Object.entries(day.undelivered).map(([scene, n]) => ({
        key: `send:${scene}`,
        revision: n,
        text: t('overview.todo.undelivered', { group: groupLabel(scene), n }, n),
        tone: 'error',
        to: groupsTarget(scene, 'live'),
        action: view,
      })),
      (groups) => t('overview.todo.undeliveredMany', { groups }),
    )
    for (const call of day.model_errors) {
      items.push({
        key: `model:${call.id}`,
        revision: call.count,
        text: t('overview.todo.modelErrors', { n: call.count }, call.count),
        error: call.error,
        tone: 'error',
        to: {
          name: 'host-logs',
          query: { scene: call.scene, call: call.id, turn: call.turn_id ?? undefined },
        },
        action: view,
      })
    }
    const failures: Record<string, number> = {}
    for (const turn of day.recent_errors) {
      if (turn.started >= day.since && !turn.model_error && FAILED_TURNS.has(turn.status))
        failures[turn.scene] = (failures[turn.scene] ?? 0) + 1
    }
    perScene(
      items,
      'turn',
      Object.entries(failures).map(([scene, n]) => ({
        key: `turn:${scene}`,
        revision: n,
        text: t('overview.todo.turnErrors', { group: groupLabel(scene), n }, n),
        tone: 'error',
        to: { name: 'host-logs', query: { scene } },
        action: view,
      })),
      (groups) => t('overview.todo.turnErrorsMany', { groups }),
    )
    perScene(
      items,
      'task',
      Object.entries(day.failed_tasks).map(([scene, n]) => ({
        key: `task:${scene}`,
        revision: n,
        text: t('overview.todo.taskFailed', { group: groupLabel(scene), n }, n),
        tone: 'warning',
        to: groupsTarget(scene, 'tasks'),
        action: view,
      })),
      (groups) => t('overview.todo.taskFailedMany', { groups }),
    )
    perScene(
      items,
      'memory',
      day.memory_stuck.map((job) => ({
        key: `memory:${job.scene}`,
        revision: `${job.status}:${job.ended}`,
        text: t(`overview.todo.memory.${job.status}`, { group: groupLabel(job.scene) }),
        error: job.error,
        tone: 'warning',
        to: groupsTarget(job.scene, 'memory', { tab: 'ingest' }),
        action: t('overview.todo.retry'),
      })),
      (groups) => t('overview.todo.memoryMany', { groups }),
    )
    if (day.memory_index?.needs_rebuild) {
      items.push({
        key: 'memory-index',
        text: t('overview.todo.index'),
        error: day.memory_index.reason,
        tone: 'warning',
        to: groupsTarget(undefined, 'memory', { tab: 'index' }),
        action: view,
      })
    }
    perScene(
      items,
      'speech',
      Object.entries(day.speech_held).map(([scene, until]) => ({
        key: `speech:${scene}`,
        revision: until,
        text: t('overview.todo.speech', {
          group: groupLabel(scene),
          time: formatDateTime(until, { timeZone: day.timezone }),
        }),
        tone: 'info',
        to: groupsTarget(scene, 'settings'),
        action: view,
      })),
      (groups) => t('overview.todo.speechMany', { groups }),
    )
    perScene(
      items,
      'review',
      Object.entries(day.pending_reviews).map(([scene, reviews]) => ({
        key: `review:${scene}`,
        revision: JSON.stringify(reviews),
        text: t('overview.todo.review', {
          group: groupLabel(scene),
          what: [
            reviews.expressions
              ? t('overview.todo.expressions', { n: reviews.expressions }, reviews.expressions)
              : '',
            reviews.stickers ? t('overview.todo.stickers', { n: reviews.stickers }, reviews.stickers) : '',
          ]
            .filter(Boolean)
            .join(t('personas.separator')),
        }),
        tone: 'info',
        to: groupsTarget(scene, 'learning'),
        action: t('overview.todo.toReview'),
      })),
      (groups) => t('overview.todo.reviewMany', { groups }),
    )
    return items
  })

  function visible(item: Attention) {
    return dismissed.value.scope !== scope.value || dismissed.value.items[item.key] !== revisionOf(item)
  }
  const items = computed<Attention[]>(() =>
    allItems.value.flatMap((item) => {
      if (!item.children) return visible(item) ? [item] : []
      const children = item.children.filter(visible)
      return children.length ? [{ ...item, children, text: item.summary!(children.length) }] : []
    }),
  )

  function dismiss(item: Attention) {
    const saved = dismissed.value.scope === scope.value ? dismissed.value.items : {}
    dismissed.value = {
      scope: scope.value,
      items: {
        ...saved,
        ...Object.fromEntries((item.children ?? [item]).map((row) => [row.key, revisionOf(row)])),
      },
    }
  }

  // Resolved items can appear again if the same problem returns later.
  watch(allItems, (rows) => {
    if (!host.state || !host.overview || dismissed.value.scope !== scope.value) return
    const active = new Set(rows.flatMap((row) => (row.children ?? [row]).map((item) => item.key)))
    const saved = Object.entries(dismissed.value.items).filter(([key]) => active.has(key))
    if (saved.length !== Object.keys(dismissed.value.items).length)
      dismissed.value = { scope: scope.value, items: Object.fromEntries(saved) }
  })

  /** Counted only once today's overview is read, so the number does not jump. */
  const count = computed(() => (host.overview || host.overviewError ? items.value.length : 0))
  return { items, count, dismiss }
}
