import { useI18n } from 'vue-i18n'

/** Names of wake channels, tools, model roles and statuses; unknown values are shown as they are. */
export function useLiveLabels() {
  const { t, te } = useI18n()
  const known = (prefix: string, value: string) =>
    te(`${prefix}.${value}`) ? t(`${prefix}.${value}`) : value
  return {
    channel: (value: string) => known('groups.live.channels', value),
    tool: (value: string) => known('groups.live.tools', value),
    status: (value: string) => known('groups.live.statuses', value),
    role: (value: string) =>
      value.startsWith('plugin:')
        ? t('groups.live.roles.plugin', { name: value.slice(7) })
        : known('groups.live.roles', value),
  }
}
