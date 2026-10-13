import { createI18n } from 'vue-i18n'
import { ref } from 'vue'
import zhCN from './locales/zh-CN'

/** Message shape: Chinese is the source, and every other locale must match it key for key. */
export type Messages = typeof zhCN
export type Locale = 'zh-CN' | 'en'

export const localeOptions: { value: Locale; label: string }[] = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en', label: 'English' },
]

const KEY = 'lenbot.locale'

function savedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'zh-CN' || value === 'en' ? value : null
  } catch {
    return null
  }
}

function browserLocale(): Locale {
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en'
}

export const i18n = createI18n<[Messages], Locale, false>({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN } as Record<Locale, Messages>,
  missingWarn: import.meta.env.DEV,
  fallbackWarn: false,
})

/** The active locale, readable outside components (formatters, document title). */
export const currentLocale = ref<Locale>('zh-CN')

const loaders: Record<Locale, () => Promise<Messages>> = {
  'zh-CN': async () => zhCN,
  en: async () => (await import('./locales/en')).default,
}

export async function setLocale(locale: Locale, { remember = true } = {}): Promise<void> {
  if (!i18n.global.availableLocales.includes(locale)) {
    i18n.global.setLocaleMessage(locale, await loaders[locale]())
  }
  i18n.global.locale.value = locale
  currentLocale.value = locale
  document.documentElement.lang = locale
  if (remember) {
    try {
      localStorage.setItem(KEY, locale)
    } catch {
      // Storage refused (private mode): the choice lasts for this tab only.
    }
  }
}

/** Load the saved or browser locale before the first render. */
export function startLocale(): Promise<void> {
  const saved = savedLocale()
  return setLocale(saved ?? browserLocale(), { remember: saved !== null })
}
