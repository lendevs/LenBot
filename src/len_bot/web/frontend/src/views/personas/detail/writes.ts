import type { Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import type { Applied } from '../../../api/personas'
import { readHostState } from '../../../host/store.js'
import { toast } from '../../../ui/toast'

type Part = Parameters<typeof keys.personas.part>[1]

/** What every saved role change does next: say whether the groups took it and read what it touched again. */
export function useRoleWrites(key: Ref<string>) {
  const { t } = useI18n()
  const client = useQueryClient()

  function done(result: Partial<Applied>, refresh: Part[] = [], message = t('common.saved')) {
    if (result.apply_error) toast.error(t('personas.detail.applyFailed'), { detail: result.apply_error })
    else if (result.applied === false) toast.success(t('personas.detail.savedPending'))
    else toast.success(message)
    void client.invalidateQueries({ queryKey: keys.personas.all() })
    for (const part of refresh) void client.invalidateQueries({ queryKey: keys.personas.part(key.value, part) })
    if (result.affected_scenes?.length) void readHostState()
  }

  return { done }
}
