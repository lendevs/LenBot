import { computed, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import { sessionApi } from '../../../api/session'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'

/** Compact the recap and start a new session, each after a confirmation; shared by the header and the tab. */
export function useSessionActions(scene: Ref<string>) {
  const { t } = useI18n()
  const client = useQueryClient()
  const failed = (title: string) => (error: unknown) =>
    toast.error(title, { detail: describeError(error, t('ui.error.network')).message })
  const settled = () => client.invalidateQueries({ queryKey: keys.scene.all(scene.value) })

  const fresh = useMutation({
    mutationFn: () => sessionApi.newContext(scene.value),
    onSuccess: () => toast.success(t('groups.newSession.done')),
    onError: failed(t('groups.newSession.failed')),
    onSettled: settled,
  })
  const compact = useMutation({
    mutationFn: () => sessionApi.compact(scene.value),
    onSuccess: () => toast.success(t('groups.session.compacted')),
    onError: failed(t('groups.session.compactFailed')),
    onSettled: settled,
  })

  async function startSession() {
    const confirmed = await confirm({
      title: t('groups.newSession.title'),
      message: t('groups.newSession.message'),
      confirmLabel: t('groups.newSession.action'),
    })
    if (confirmed) fresh.mutate()
  }
  async function compactRecap() {
    const confirmed = await confirm({
      title: t('groups.session.compactTitle'),
      message: t('groups.session.compactMessage'),
      confirmLabel: t('groups.session.compact'),
      tone: 'primary',
    })
    if (confirmed) compact.mutate()
  }
  return {
    starting: computed(() => fresh.isPending.value),
    compacting: computed(() => compact.isPending.value),
    startSession,
    compactRecap,
  }
}
