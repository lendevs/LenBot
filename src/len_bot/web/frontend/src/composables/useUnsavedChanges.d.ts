import type { Ref } from 'vue'

export function useUnsavedChanges(
  dirty: Ref<boolean> | boolean,
  options?: { onDiscard?: () => void; keep?: string[] },
): { confirmLeave: () => Promise<boolean> }
