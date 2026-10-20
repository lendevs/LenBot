import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import type { PersonaSummary } from '../../api/host'
import { personasApi } from '../../api/personas'
import { keys } from '../../api/query'
import { settingsApi } from '../../api/settings'
import { readHostState } from '../../api/hostStore'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

export const roleLabel = (role: Pick<PersonaSummary, 'name' | 'key'>) => role.name || role.key

/** The role library, as the places that switch a group's role list it. */
export function useRoles() {
  const library = useQuery({
    queryKey: keys.personas.all(),
    queryFn: ({ signal }) => personasApi.library(signal),
  })
  const roles = computed(() => library.data.value?.roles ?? [])
  /** Roles a group can switch to: readable and with an id no other role uses. */
  const usable = computed(() => roles.value.filter((role) => !role.error && !role.duplicate_id))
  return { library, roles, usable }
}

/**
 * Switches one group to a role right away. A group in the middle of a reply switches when that turn
 * ends; the host state then shows the waiting role (`persona_switch`) until it does.
 */
export function useRoleSwitch() {
  const { t } = useI18n()
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ scene, role }: { scene: string; role: PersonaSummary }) => settingsApi.useRole(role.key, [scene]),
    onSuccess: ({ results }, { role }) => {
      const result = results[0]
      if (result?.status === 'failed') {
        toast.error(t('groups.settings.role.failed'), { detail: result.error })
        return
      }
      if (result?.status === 'pending') toast.success(t('groups.settings.role.pending', { name: roleLabel(role) }))
      else toast.success(t('groups.settings.role.done', { name: roleLabel(role) }))
      if (result?.handover === 'failed') toast.error(t('groups.settings.role.handoverFailed'))
    },
    onError: (error) =>
      toast.error(t('groups.settings.role.failed'), { detail: describeError(error, t('ui.error.network')).message }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.personas.all() })
      void client.invalidateQueries({ queryKey: keys.host.settings() })
      void readHostState()
    },
  })
  return {
    switchRole: (scene: string, role: PersonaSummary) => mutation.mutate({ scene, role }),
    /** True while the request for this group is out; the wait for its turn shows in the host state. */
    sending: (scene: string) => mutation.isPending.value && mutation.variables.value?.scene === scene,
  }
}
