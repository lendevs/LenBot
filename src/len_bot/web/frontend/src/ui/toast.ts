import { ref } from 'vue'

export type ToastTone = 'success' | 'error' | 'info' | 'warning'

export interface ToastOptions {
  /** Second line, such as the error text returned by LenBot. */
  detail?: string
  /** Milliseconds; errors stay longer because their text is usually longer. */
  duration?: number
  action?: { label: string; run: () => void }
}

export interface ToastItem extends ToastOptions {
  id: number
  tone: ToastTone
  title: string
  open: boolean
}

export const toasts = ref<ToastItem[]>([])
const MAX_OPEN = 5
let next = 1

function show(tone: ToastTone, title: string, options: ToastOptions = {}): number {
  const id = next++
  const duration = options.duration ?? (tone === 'error' ? 8000 : 4000)
  const openItems = toasts.value.filter((entry) => entry.open)
  let overflow = openItems.length - (MAX_OPEN - 1)
  if (overflow > 0) {
    for (const entry of openItems) {
      if (overflow <= 0) break
      entry.open = false
      overflow--
    }
  }
  toasts.value = [...toasts.value, { id, tone, title, open: true, ...options, duration }]
  return id
}

/** Called by Toaster after the exit animation. */
export function removeToast(id: number): void {
  toasts.value = toasts.value.filter((entry) => entry.id !== id)
}

export const toast = {
  success: (title: string, options?: ToastOptions) => show('success', title, options),
  error: (title: string, options?: ToastOptions) => show('error', title, options),
  info: (title: string, options?: ToastOptions) => show('info', title, options),
  warning: (title: string, options?: ToastOptions) => show('warning', title, options),
}
