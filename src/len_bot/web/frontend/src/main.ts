import { createApp } from 'vue'
import { VueQueryPlugin } from '@tanstack/vue-query'
import App from './App.vue'
import router from './router'
import { bindThemeMode } from './composables/useThemeMode'
import { i18n, startLocale } from './i18n'
import { queryClient } from './api/query'
import { captureSetupToken } from './api/setup'
import './styles/tokens.css'
import './styles/app.css'

captureSetupToken()
bindThemeMode()
void startLocale().finally(() =>
  createApp(App).use(VueQueryPlugin, { queryClient }).use(i18n).use(router).mount('#app'),
)
