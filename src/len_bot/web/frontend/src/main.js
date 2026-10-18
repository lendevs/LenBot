import { createApp } from 'vue'
import App from './App.vue'
import router from './router/index.js'
import vuetify from './plugins/vuetify.js'
import { bindThemeMode } from './composables/useThemeMode.js'
import { i18n, startLocale } from './i18n'
import './styles/tokens.css'
import './styles/app.css'
import './styles/base.css'
import './styles/shell.css'

bindThemeMode(vuetify)
startLocale().finally(() => createApp(App).use(i18n).use(vuetify).use(router).mount('#app'))
