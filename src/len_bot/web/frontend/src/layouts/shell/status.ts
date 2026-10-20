import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { HostState } from '../../api/host'
import type { Tone } from '../../ui/Badge.vue'
import { host } from '../../host/store.js'

const tones: Record<string, Tone> = {
  created: 'info',
  starting: 'info',
  waiting_connection: 'warning',
  connection_failed: 'error',
  failed: 'error',
  stopping: 'warning',
}

/** Whether the Bot is online, in words, as the top bar and the overview show it. */
export function useConnectionStatus() {
  const { t } = useI18n()
  const state = computed(() => host.state as HostState | null)
  const platform = computed(() => (state.value?.connection.mode === 'telegram' ? 'Telegram' : 'QQ'))
  const online = computed(() =>
    Boolean(state.value?.connection.connected && state.value.connection.accepting),
  )
  const status = computed<{ text: string; tone: Tone }>(() => {
    const value = state.value
    if (!value) {
      return host.stateError
        ? { text: t('shell.status.readFailed'), tone: 'error' }
        : { text: t('shell.status.reading'), tone: 'neutral' }
    }
    const connection = value.connection
    if (online.value) return { text: t('shell.status.online'), tone: 'success' }
    if (connection.status === 'running') {
      return { text: t('shell.status.platformOffline', { platform: platform.value }), tone: 'warning' }
    }
    return {
      text: t(`shell.status.runtime.${connection.status}`, { platform: platform.value }),
      tone: tones[connection.status] ?? 'neutral',
    }
  })
  return { platform, online, status }
}
