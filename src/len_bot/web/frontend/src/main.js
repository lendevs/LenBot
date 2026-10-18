import { createApp } from 'vue'
import { VueQueryPlugin } from '@tanstack/vue-query'
import App from './App.vue'
import router from './router/index.js'
import vuetify from './plugins/vuetify.js'
import { bindThemeMode } from './composables/useThemeMode.js'
import { i18n, startLocale } from './i18n'
import { queryClient } from './api/query'
import './styles/tokens.css'
import './styles/app.css'
import './styles/base.css'
import './styles/shell.css'

bindThemeMode(vuetify)
startLocale().finally(() => createApp(App).use(VueQueryPlugin, { queryClient }).use(i18n).use(vuetify).use(router).mount('#app'))
