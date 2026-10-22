import { shallowRef } from 'vue'

export interface ConfirmRequest {
  title: string
  message?: string
  confirmLabel?: string
  tone?: 'danger' | 'primary'
}

interface Pending extends ConfirmRequest {
  resolve: (confirmed: boolean) => void
}

/** The question ConfirmHost is showing; one at a time, a new one answers the previous with false. */
export const pendingConfirm = shallowRef<Pending | null>(null)

/** Ask before an action that cannot be undone. Resolves true only when the user confirms. */
export function confirm(request: ConfirmRequest): Promise<boolean> {
  pendingConfirm.value?.resolve(false)
  return new Promise((resolve) => {
    pendingConfirm.value = { ...request, resolve }
  })
}

export function answerConfirm(confirmed: boolean): void {
  const pending = pendingConfirm.value
  if (!pending) return
  pendingConfirm.value = null
  pending.resolve(confirmed)
}
