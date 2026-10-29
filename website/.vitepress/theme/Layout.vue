<script setup lang="ts">
import DefaultTheme from 'vitepress/theme'
import { useData, useRoute } from 'vitepress'
import { nextTick, onBeforeUnmount, onMounted, provide, watch } from 'vue'

const { isDark } = useData()
const route = useRoute()

// Appearance switch: the new theme grows as a circle from the pointer.
provide('toggle-appearance', async (event: MouseEvent) => {
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!('startViewTransition' in document) || still) {
    isDark.value = !isDark.value
    return
  }
  const x = event.clientX || innerWidth - 40
  const y = event.clientY || 32
  const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y))
  const clipPath = [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`]
  await document.startViewTransition(async () => {
    isDark.value = !isDark.value
    await nextTick()
  }).ready
  document.documentElement.animate(
    { clipPath: isDark.value ? clipPath.reverse() : clipPath },
    { duration: 480, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', pseudoElement: `::view-transition-${isDark.value ? 'old' : 'new'}(root)` },
  )
})

// Elements with .reveal fade in once they scroll into view.
let observer: IntersectionObserver | undefined
function observe() {
  observer ??= new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      entry.target.classList.add('is-visible')
      observer?.unobserve(entry.target)
    }
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.08 })
  document.querySelectorAll('.reveal:not(.is-visible)').forEach((element) => observer?.observe(element))
}
onMounted(() => {
  document.documentElement.classList.add('reveal-ready')
  observe()
})
watch(() => route.path, () => nextTick(observe))
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <DefaultTheme.Layout />
</template>
