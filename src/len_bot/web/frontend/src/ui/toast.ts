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
let next = 1

function show(tone: ToastTone, title: string, options: ToastOptions = {}): number {
  const id = next++
  const duration = options.duration ?? (tone === 'error' ? 8000 : 4000)
  toasts.value = [...toasts.value.slice(-4), { id, tone, title, open: true, ...options, duration }]
  return id
}

export function dismissToast(id: number): void {
  const item = toasts.value.find((entry) => entry.id === id)
  if (item) item.open = false
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
