<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../../api.js'
import { useResource } from '../../../composables/useResource.js'
import { host } from '../../store.js'
import HostPage from '../../ui/HostPage.vue'
import ResourceState from '../../ui/ResourceState.vue'
import EmptyState from '../../ui/EmptyState.vue'
import PersonaLibrary from './PersonaLibrary.vue'
import PersonaDetail from './PersonaDetail.vue'
import RoleCreateDialog from './RoleCreateDialog.vue'

const route = useRoute(), router = useRouter()
const library = useResource(() => api('/api/host/personas'))
const roles = computed(() => library.data.value?.roles || [])
const key = computed(() => typeof route.query.persona === 'string' ? route.query.persona : '')
const role = computed(() => roles.value.find(item => item.key === key.value) || null)
// A switch from the group command or another tab changes which scenes use a role.
watch(() => (host.state?.scenes || []).map(item => `${item.scene}=${item.persona_path}`).join(), (now, before) => {
  if (before !== undefined && now !== before) library.reload()
})

const request = ref(null)
async function created(folder) {
  request.value = null
  await library.reload()
  router.push({ name: route.name, query: { persona: folder } })
}
const open = value => router.push({ name: route.name, query: { persona: value } })
</script>

<template>
  <HostPage :title="key ? '' : '角色'">
    <ResourceState :resource="library" error-title="读取角色失败">
      <PersonaDetail v-if="role" :role="role" @changed="library.reload()" @create="value => request = value" />
      <EmptyState v-else-if="key" text="角色库里没有这个角色">
        <v-btn variant="outlined" :to="{ name: route.name, query: {} }">全部角色</v-btn>
      </EmptyState>
      <PersonaLibrary v-else :roles="roles" @open="open" @changed="library.reload()" @create="value => request = value" />
    </ResourceState>
    <RoleCreateDialog :request="request" @close="request = null" @done="created" />
  </HostPage>
</template>
