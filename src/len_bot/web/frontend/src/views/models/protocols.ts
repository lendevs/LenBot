import { useI18n } from 'vue-i18n'
import type { Protocol } from '../../api/models'

/** Display name of a native protocol: from the panel's own words, else the name the host sends. */
export function useProtocolTitle() {
  const { t, te } = useI18n()
  return (protocol: Pick<Protocol, 'api' | 'title'>): string => {
    const key = `models.protocols.${protocol.api}`
    return te(key) ? t(key) : protocol.title
  }
}
