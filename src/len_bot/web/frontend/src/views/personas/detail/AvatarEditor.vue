<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ImageUp, Trash2 } from '@lucide/vue'
import { avatarChanged, personaAvatar } from '../../../api/host'
import { personasApi, type PersonaRole } from '../../../api/personas'
import Avatar from '../../../ui/Avatar.vue'
import Button from '../../../ui/Button.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useRoleWrites } from './writes'

const MAX_AVATAR_BYTES = 10_000_000
const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]

const props = defineProps<{ role: PersonaRole; name: string }>()

const { t } = useI18n()
const writes = useRoleWrites(computed(() => props.role.key))
const picker = ref<HTMLInputElement | null>(null)

async function isPngBytes(file: File): Promise<boolean> {
  if (file.size < PNG_SIGNATURE.length) return false
  const head = new Uint8Array(await file.slice(0, PNG_SIGNATURE.length).arrayBuffer())
  return PNG_SIGNATURE.every((byte, index) => head[index] === byte)
}

function canvasToPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error(t('personas.detail.avatar.invalidImage')))
    }, 'image/png')
  })
}

async function decodeImage(file: File): Promise<{
  width: number
  height: number
  draw: (ctx: CanvasRenderingContext2D, width: number, height: number) => void
  release: () => void
}> {
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file)
      return {
        width: bitmap.width,
        height: bitmap.height,
        draw: (ctx, width, height) => ctx.drawImage(bitmap, 0, 0, width, height),
        release: () => bitmap.close(),
      }
    } catch {
      // Fall through to HTMLImageElement decoding.
    }
  }
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new Error(t('personas.detail.avatar.invalidImage')))
      element.src = url
    })
    return {
      width: img.naturalWidth,
      height: img.naturalHeight,
      draw: (ctx, width, height) => ctx.drawImage(img, 0, 0, width, height),
      release: () => URL.revokeObjectURL(url),
    }
  } catch (error) {
    URL.revokeObjectURL(url)
    throw error
  }
}

/** Backend stores avatar.png; convert JPG/WebP losslessly via offscreen canvas before upload. */
async function ensurePng(file: File): Promise<File> {
  if (await isPngBytes(file)) return file
  const decoded = await decodeImage(file)
  try {
    let { width, height } = decoded
    if (!width || !height) throw new Error(t('personas.detail.avatar.invalidImage'))
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error(t('personas.detail.avatar.invalidImage'))
    decoded.draw(ctx, width, height)
    let blob = await canvasToPng(canvas)
    while (blob.size > MAX_AVATAR_BYTES && Math.max(width, height) > 256) {
      const scale = Math.min(0.75, Math.sqrt((MAX_AVATAR_BYTES * 0.85) / blob.size))
      width = Math.max(1, Math.round(width * scale))
      height = Math.max(1, Math.round(height * scale))
      canvas.width = width
      canvas.height = height
      ctx.clearRect(0, 0, width, height)
      decoded.draw(ctx, width, height)
      blob = await canvasToPng(canvas)
    }
    const stem = file.name.replace(/\.[^.]+$/, '') || 'avatar'
    return new File([blob], `${stem}.png`, { type: 'image/png' })
  } finally {
    decoded.release()
  }
}

const change = useMutation({
  mutationFn: async (file: File | null) =>
    file
      ? personasApi.uploadAvatar(props.role.key, props.role.path, await ensurePng(file))
      : personasApi.removeAvatar(props.role.key, props.role.path),
  onSuccess: (result, file) => {
    avatarChanged(props.role.key)
    writes.done(result, [], file ? t('personas.detail.avatar.changed') : t('personas.detail.avatar.removed'))
  },
  onError: (error) =>
    toast.error(t('personas.detail.avatar.failed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
function chosen(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) change.mutate(file)
}
async function remove() {
  const sure = await confirm({
    title: t('personas.detail.avatar.removeTitle'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) change.mutate(null)
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-3">
    <span class="inline-flex shrink-0 rounded-full ring-1 ring-line">
      <Avatar :name="name || role.key" :src="personaAvatar(role)" :size="40" />
    </span>
    <input
      ref="picker"
      type="file"
      accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
      class="sr-only"
      tabindex="-1"
      aria-hidden="true"
      @change="chosen"
    />
    <div class="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        :icon="ImageUp"
        :loading="change.isPending.value && change.variables.value !== null"
        :disabled="change.isPending.value"
        @click="picker?.click()"
      >
        {{ role.avatar ? t('personas.detail.avatar.replace') : t('personas.detail.avatar.upload') }}
      </Button>
      <Button
        v-if="role.avatar"
        size="sm"
        variant="danger-ghost"
        :icon="Trash2"
        :disabled="change.isPending.value"
        @click="remove"
      >
        {{ t('common.delete') }}
      </Button>
    </div>
  </div>
</template>
