import { computed } from 'vue'
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
  text: string
  /** Error text kept as reported, shown on request. */
  error?: string | null
  to?: RouteLocationRaw
  action?: string
  tone: 'error' | 'warning' | 'info'
  /** The same trouble in several groups, one row per group. */
  children?: Attention[]
}

/** Statuses of a turn that ended without finishing its reply. */
const FAILED_TURNS = new Set(['error', 'timeout', 'interrupted', 'step_limit'])
/** From this many groups on, the same kind of trouble reads as one item. */
const MERGE_FROM = 3

/** What needs the operator, as the overview lists it and the top bar counts it. */
export function useAttention() {
  const { t } = useI18n()
  const { online, status } = useConnectionStatus()

  // Each group stays one click away inside the merged item.
  function perScene(
    items: Attention[],
    kind: string,
    rows: Attention[],
    summary: (groups: number) => string,
  ) {
    if (rows.length < MERGE_FROM) items.push(...rows)
    else items.push({ key: kind, text: summary(rows.length), tone: rows[0]!.tone, children: rows })
  }

  const items = computed<Attention[]>(() => {
    const state = host.state as HostState | null
    const day = host.overview as Overview | null
    const items: Attention[] = []
    if (state && !online.value) {
      items.push({
        key: 'connection',
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
            text: t(`overview.todo.${kind}Errors`, { name: item.name, n: item.error_count }, item.error_count),
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
        text: t('overview.todo.undelivered', { group: groupLabel(scene), n }, n),
        tone: 'error',
        to: groupsTarget(scene, 'live'),
        action: view,
      })),
      (groups) => t('overview.todo.undeliveredMany', { groups }),
    )
    const failures: Record<string, number> = {}
    for (const turn of day.recent_errors) {
      if (turn.started >= day.since && FAILED_TURNS.has(turn.status)) failures[turn.scene] = (failures[turn.scene] ?? 0) + 1
    }
    perScene(
      items,
      'turn',
      Object.entries(failures).map(([scene, n]) => ({
        key: `turn:${scene}`,
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
        text: t('overview.todo.review', {
          group: groupLabel(scene),
          what: [
            reviews.expressions ? t('overview.todo.expressions', { n: reviews.expressions }, reviews.expressions) : '',
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

  /** Counted only once today's overview is read, so the number does not jump. */
  const count = computed(() => (host.overview || host.overviewError ? items.value.length : 0))
  return { items, count }
}
