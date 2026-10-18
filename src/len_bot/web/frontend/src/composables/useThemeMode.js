import { ref } from 'vue'
import { applyPalette } from '../styles/theme.js'

const KEY = 'lenbot.theme'
const MODES = ['system', 'light', 'dark']
const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null

function storedMode() {
  try {
    const value = localStorage.getItem(KEY)
    return MODES.includes(value) ? value : 'system'
  } catch {
    return 'system'
  }
}

/** The mode the user picked: follow the system, or force light or dark. */
export const themeMode = ref(storedMode())

function resolve(mode) {
  if (mode === 'light' || mode === 'dark') return mode
  return media?.matches ? 'dark' : 'light'
}

/** Light or dark for the first paint, before Vue mounts. */
export function initialTheme() {
  return resolve(themeMode.value)
}

let bound = null

function apply() {
  const theme = resolve(themeMode.value)
  applyPalette(theme)
  if (bound) bound.theme.global.name.value = theme
}

/** Connect the stored mode to Vuetify and the CSS palette, and follow system changes. */
export function bindThemeMode(vuetify) {
  bound = vuetify
  apply()
  media?.addEventListener?.('change', () => { if (themeMode.value === 'system') apply() })
}

export function setThemeMode(mode) {
  if (!MODES.includes(mode)) return
  themeMode.value = mode
  try { localStorage.setItem(KEY, mode) } catch { /* private mode: keep it for this tab only */ }
  apply()
}

export const themeModeOptions = [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']]
