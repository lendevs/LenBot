import { i18n } from '../../../i18n'
import { confirm } from '../../../ui/confirm'

/** Asked before a group's memory implementation changes. */
export function confirmMemorySwitch(): Promise<boolean> {
  const t = i18n.global.t
  return confirm({
    title: t('groups.settings.plugins.switchTitle'),
    message: t('groups.settings.plugins.switchMessage'),
    confirmLabel: t('groups.settings.plugins.switchConfirm'),
  })
}
