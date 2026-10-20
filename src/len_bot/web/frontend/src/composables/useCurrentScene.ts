import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { host } from '../api/hostStore'

const last = ref('')

/** A scene that exists on the host: the one asked for, else the last one shown, else the first. */
export function resolveScene(value: unknown): string {
  const scenes = host.state?.scenes ?? []
  const valid = (name: unknown): name is string =>
    typeof name === 'string' && scenes.some((item) => item.scene === name)
  if (valid(value)) return value
  return valid(last.value) ? last.value : (scenes[0]?.scene ?? '')
}

export function useCurrentScene() {
  const route = useRoute()
  const scene = computed(() => {
    // The workbench names the group in the path (/groups/:scene/:tab); other pages use ?scene=.
    const param = route.params.scene
    const value = resolveScene(typeof param === 'string' && param.includes(':') ? param : route.query.scene)
    if (value) last.value = value
    return value
  })
  const current = computed(() => host.state?.scenes.find((item) => item.scene === scene.value) ?? null)
  return { scene, current }
}
