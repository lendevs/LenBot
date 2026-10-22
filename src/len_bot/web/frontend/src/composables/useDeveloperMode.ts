import { computed, ref } from 'vue'
import { useAuth } from './useAuth'

/** Raw records and request details; always on outside the host panel, a switch inside it. */
export const developerMode = ref(false)
export const developerDetails = computed(
  () => useAuth().panelContext?.mode !== 'isolated-multi' || developerMode.value,
)
