import type { ComputedRef } from 'vue'

export function useHostEvents(
  read: () => unknown,
  options?: { types?: string[] | null; minInterval?: number },
): { status: ComputedRef<'connecting' | 'connected' | 'disconnected'>; reconnect: () => void }
