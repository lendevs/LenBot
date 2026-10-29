import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import Layout from './Layout.vue'
import CardImage from './components/CardImage.vue'
import DeployPicker from './components/DeployPicker.vue'
import HomePage from './components/HomePage.vue'
import StepRail from './components/StepRail.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }) {
    app.component('CardImage', CardImage)
    app.component('DeployPicker', DeployPicker)
    app.component('HomePage', HomePage)
    app.component('StepRail', StepRail)
  },
} satisfies Theme
