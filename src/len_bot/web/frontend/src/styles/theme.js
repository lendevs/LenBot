export const palette = {
  brand: '#e2809f',
  'brand-soft': '#fbeff3',
  primary: '#b4476a',
  'primary-bg': '#f8e6ec',
  'on-primary': '#ffffff',
  ink: '#1d1b20',
  muted: '#6b6870',
  line: '#e9e9ec',
  'line-strong': '#d9d8dd',
  page: '#ffffff',
  canvas: '#ffffff',
  sidebar: '#f7f7f8',
  fill: '#f6f6f8',
  surface: '#ffffff',
  hover: '#f2f2f4',
  track: '#ededf0',
  selected: '#fbeff3',
  success: '#22875a',
  'success-bg': '#e6f4ec',
  warning: '#a8630f',
  'warning-bg': '#fbf0de',
  error: '#c4323f',
  'error-bg': '#fce9ea',
  info: '#2f6db0',
  'info-bg': '#e8f0f9',
  idle: '#c8c6cc',
  'code-bg': '#f5f5f7',
}

export const avatarTints = [['#f8e6ec', '#a8405f'], ['#eee8f6', '#6c4f96'], ['#f8ece0', '#93552a'],
  ['#e4f1ec', '#2a7457'], ['#e6edf6', '#3d6596'], ['#f5efdc', '#7d6418']]

// Dark values keep the same names so every component that reads var(--name) follows the mode.
export const darkPalette = {
  brand: '#e891ad',
  'brand-soft': '#3a2530',
  primary: '#ec8fae',
  'primary-bg': '#3a2530',
  'on-primary': '#1d1b20',
  ink: '#ecebef',
  muted: '#a19ea8',
  line: '#2e2d33',
  'line-strong': '#3d3c43',
  page: '#141317',
  canvas: '#141317',
  sidebar: '#1a191e',
  fill: '#232228',
  surface: '#1c1b20',
  hover: '#2a2930',
  track: '#2a2930',
  selected: '#3a2530',
  success: '#5cc792',
  'success-bg': '#183528',
  warning: '#e3a650',
  'warning-bg': '#3a2c17',
  error: '#f07a84',
  'error-bg': '#3d1d21',
  info: '#79aee6',
  'info-bg': '#1b2b3d',
  idle: '#55535b',
  'code-bg': '#232228',
}

export const palettes = { light: palette, dark: darkPalette }

export function applyPalette(mode = 'light', root = document.documentElement) {
  const values = palettes[mode] || palette
  for (const [name, value] of Object.entries(values)) root.style.setProperty(`--${name}`, value)
  root.dataset.theme = mode
  root.style.colorScheme = mode
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
    info: values.primary,
    'on-background': values.ink,
    'on-surface': values.ink,
    toast: values === darkPalette ? '#3d3c43' : '#1d1b20',
  }
}

export const vuetifyColors = toVuetify(palette)
export const vuetifyDarkColors = toVuetify(darkPalette)
