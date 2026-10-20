import tokens from './tokens.css?raw'

// Color values are defined once in tokens.css; Vuetify's theme reads them from the same text.
function colors(selector) {
  const start = tokens.indexOf(`${selector} {`)
  const body = tokens.slice(start, tokens.indexOf('}', start))
  const values = {}
  for (const [, name, value] of body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{3,8});/gi)) values[name] = value
  return values
}

export const palette = colors(':root')

export const avatarTints = [['#f8e6ec', '#a8405f'], ['#eee8f6', '#6c4f96'], ['#f8ece0', '#93552a'],
  ['#e4f1ec', '#2a7457'], ['#e6edf6', '#3d6596'], ['#f5efdc', '#7d6418']]

export const darkPalette = colors(":root[data-theme='dark']")

export function applyPalette(mode = 'light', root = document.documentElement) {
  root.dataset.theme = mode === 'dark' ? 'dark' : 'light'
}

function toVuetify(values) {
  return {
    primary: values.primary,
    brand: values.brand,
    secondary: values.muted,
    background: values.page,
    surface: values.surface,
    'surface-variant': values.track,
    'on-surface-variant': values.muted,
    success: values.success,
    warning: values.warning,
    error: values.error,
    info: values.info,
    'on-background': values.ink,
    'on-surface': values.ink,
    toast: values === darkPalette ? values['line-strong'] : values.ink,
  }
}

export const vuetifyColors = toVuetify(palette)
export const vuetifyDarkColors = toVuetify(darkPalette)
