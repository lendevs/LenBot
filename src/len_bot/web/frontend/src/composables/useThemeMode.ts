import { ref } from 'vue'

export type ThemeMode = 'system' | 'light' | 'dark'

const KEY = 'lenbot.theme'
const MODES: ThemeMode[] = ['system', 'light', 'dark']
const media =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null

function storedMode(): ThemeMode {
  try {
    const value = localStorage.getItem(KEY)
    return MODES.includes(value as ThemeMode) ? (value as ThemeMode) : 'system'
  } catch {
    return 'system'
  }
}

/** The mode the user picked: follow the system, or force light or dark. */
export const themeMode = ref<ThemeMode>(storedMode())

function apply() {
  const dark = themeMode.value === 'dark' || (themeMode.value === 'system' && Boolean(media?.matches))
  // tokens.css switches the palette on this attribute; index.html sets it before the first paint.
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

/** Apply the stored mode and follow system changes while the mode is `system`. */
export function bindThemeMode(): void {
  apply()
  media?.addEventListener?.('change', () => {
    if (themeMode.value === 'system') apply()
  })
}

export function setThemeMode(mode: string): void {
  if (!MODES.includes(mode as ThemeMode)) return
  themeMode.value = mode as ThemeMode
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    // Storage refused (private mode): the choice lasts for this tab only.
  }
  apply()
}
