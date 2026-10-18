import { createApp } from 'vue'
import App from './App.vue'
import router from './router/index.js'
import vuetify from './plugins/vuetify.js'
import { bindThemeMode } from './composables/useThemeMode.js'
import './styles/tokens.css'
import './styles/app.css'
import './styles/base.css'
import './styles/shell.css'

bindThemeMode(vuetify)
createApp(App).use(vuetify).use(router).mount('#app')
