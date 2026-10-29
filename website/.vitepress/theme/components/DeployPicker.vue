<script setup lang="ts">
import { computed, ref } from 'vue'
import { useData, withBase } from 'vitepress'
import Icon from './Icon.vue'

const { theme } = useData()
const version = computed(() => theme.value.version as string)

type Line = { text: string; note?: boolean }
type Variant = { label: string; lang: string; lines: Line[] }
type Method = { key: string; icon: string; title: string; page: string; needs: string; link: string; variants: Variant[] }

const methods = computed<Method[]>(() => [
  {
    key: 'docker', icon: 'container', title: 'Docker', page: 'Docker 部署', needs: 'Docker Engine 或 Desktop，Compose v2', link: '/start/docker',
    variants: [{ label: 'Linux / macOS', lang: 'sh', lines: [
      { text: 'mkdir lenbot && cd lenbot' },
      { text: 'docker run --rm --entrypoint python \\' },
      { text: '  -v "$PWD:/deployment" -v /var/run/docker.sock:/var/run/docker.sock \\' },
      { text: `  ghcr.io/lendevs/lenbot-updater:${version.value} /opt/lenbot-updater/init.py --version ${version.value}` },
      { text: 'docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \\' },
      { text: '  -f host.updater.compose.yaml up -d' },
      { text: 'docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \\' },
      { text: '  -f host.updater.compose.yaml logs lenbot' },
    ] }],
  },
  {
    key: 'package', icon: 'package', title: '部署包', page: '部署包', needs: 'Linux、macOS、Windows，uv', link: '/start/package',
    variants: [
      { label: 'Linux / macOS', lang: 'sh', lines: [
        { text: `# 从 Releases 下载 lenbot-${version.value}-macos.tar.gz 或 -linux.tar.gz`, note: true },
        { text: `tar -xzf lenbot-${version.value}-macos.tar.gz` },
        { text: `cd lenbot-${version.value}-macos` },
        { text: './install.sh install "$HOME/lenbot"' },
        { text: '"$HOME/lenbot/run"' },
      ] },
      { label: 'Windows', lang: 'powershell', lines: [
        { text: `# 解压 lenbot-${version.value}-windows.zip，在解压目录中执行`, note: true },
        { text: 'powershell -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1 install "$env:USERPROFILE\\lenbot"' },
        { text: '& "$env:USERPROFILE\\lenbot\\run.cmd"' },
      ] },
    ],
  },
  {
    key: 'source', icon: 'terminal', title: '源码', page: '源码运行', needs: 'uv、Node.js 22，跟随 master', link: '/start/source',
    variants: [{ label: 'Linux / macOS', lang: 'sh', lines: [
      { text: 'git clone https://github.com/lendevs/LenBot.git' },
      { text: 'cd LenBot' },
      { text: './scripts/install.sh' },
      { text: 'uv run --no-sync len-bot' },
    ] }],
  },
])

const active = ref(0)
const variant = ref(0)
const copied = ref(false)
const method = computed(() => methods.value[active.value])
const current = computed(() => method.value.variants[Math.min(variant.value, method.value.variants.length - 1)])

function pick(index: number) {
  active.value = index
  variant.value = 0
}

async function copy() {
  const text = current.value.lines.filter((line) => !line.note).map((line) => line.text).join('\n')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    copied.value = false
  }
}
</script>

<template>
  <div class="deploy-picker">
    <div class="methods" role="tablist" aria-label="部署方式">
      <button
        v-for="(item, index) in methods"
        :key="item.key"
        class="method"
        :class="{ active: index === active }"
        role="tab"
        :aria-selected="index === active"
        @click="pick(index)"
      >
        <span class="badge"><Icon :name="item.icon" :size="20" /></span>
        <span class="body">
          <strong>{{ item.title }}</strong>
          <span>{{ item.needs }}</span>
        </span>
      </button>
    </div>
    <div class="terminal" role="tabpanel">
      <div class="bar">
        <span class="lights"><i /><i /><i /></span>
        <span class="variants">
          <button
            v-for="(item, index) in method.variants"
            :key="item.label"
            :class="{ on: current === item }"
            @click="variant = index"
          >{{ item.label }}</button>
        </span>
        <button class="copy" :aria-label="copied ? '已复制' : '复制命令'" @click="copy">
          <Icon :name="copied ? 'check' : 'copy'" :size="15" />
        </button>
      </div>
      <Transition name="swap" mode="out-in">
        <pre :key="method.key + current.label"><code><span
          v-for="(line, index) in current.lines"
          :key="index"
          class="line"
          :class="{ note: line.note }"
          :style="{ '--d': `${index * 45}ms` }"
        ><span v-if="!line.note && !line.text.startsWith('  ')" class="prompt">$ </span>{{ line.text }}</span></code></pre>
      </Transition>
      <a class="more" :href="withBase(method.link)">{{ method.page }} <Icon name="arrow-right" :size="15" /></a>
    </div>
  </div>
</template>

<style scoped>
.deploy-picker { display: grid; gap: 16px; margin: 16px 0 8px; }
.methods { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.method {
  display: flex; align-items: center; gap: 12px; padding: 14px 16px; text-align: left; border-radius: 16px;
  border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg); cursor: pointer; position: relative; overflow: hidden;
  transition: border-color 0.25s, transform 0.25s var(--lb-ease), box-shadow 0.25s;
}
.method::before {
  content: ''; position: absolute; inset: 0; opacity: 0; transition: opacity 0.3s;
  background: radial-gradient(120% 140% at 0% 0%, var(--lb-soft), transparent 60%);
}
.method:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--lb-primary) 35%, var(--vp-c-divider)); }
.method.active { border-color: var(--lb-primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--lb-primary) 14%, transparent); }
.method.active::before { opacity: 1; }
.badge {
  position: relative; flex: none; width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center;
  background: var(--vp-c-bg-soft); color: var(--vp-c-text-2); transition: background-color 0.25s, color 0.25s;
}
.method.active .badge { background: var(--lb-primary); color: var(--lb-on-primary); }
.body { position: relative; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.body strong { font-size: 15px; color: var(--vp-c-text-1); }
.body span { font-size: 12.5px; color: var(--vp-c-text-2); line-height: 1.5; }

.terminal {
  border-radius: 16px; overflow: hidden; background: var(--lb-term-bg); color: var(--lb-term-ink);
  border: 1px solid var(--lb-term-line); box-shadow: 0 24px 48px -28px rgb(20 10 20 / 0.45);
}
.bar { display: flex; align-items: center; gap: 12px; padding: 10px 12px 10px 16px; border-bottom: 1px solid var(--lb-term-line); }
.lights { display: flex; gap: 6px; }
.lights i { width: 10px; height: 10px; border-radius: 50%; background: #ff5f57; }
.lights i:nth-child(2) { background: #febc2e; }
.lights i:nth-child(3) { background: #28c840; }
.variants { display: flex; gap: 4px; flex: 1; }
.variants button {
  font-size: 12px; padding: 3px 10px; border-radius: 999px; color: var(--lb-term-muted); transition: background-color 0.2s, color 0.2s;
}
.variants button.on { background: rgb(255 255 255 / 0.1); color: var(--lb-term-ink); }
.copy { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; color: var(--lb-term-muted); transition: background-color 0.2s, color 0.2s; }
.copy:hover { background: rgb(255 255 255 / 0.08); color: var(--lb-term-ink); }
pre { margin: 0; padding: 16px 18px 6px; overflow-x: auto; font: 13px/1.75 var(--vp-font-family-mono); }
code { font: inherit; color: inherit; background: none; padding: 0; }
.line { display: block; white-space: pre; animation: line-in 0.45s var(--lb-ease) both; animation-delay: var(--d); }
.line.note { color: var(--lb-term-muted); }
.prompt { color: var(--lb-brand); user-select: none; }
.more {
  display: inline-flex; align-items: center; gap: 6px; margin: 4px 18px 16px; font-size: 13.5px; font-weight: 600;
  color: var(--lb-brand); text-decoration: none;
}
.more:hover .lb-icon { transform: translateX(3px); }
.more .lb-icon { transition: transform 0.2s; }
.swap-enter-active, .swap-leave-active { transition: opacity 0.18s; }
.swap-enter-from, .swap-leave-to { opacity: 0; }
@keyframes line-in { from { opacity: 0; transform: translateX(-6px); } to { opacity: 1; transform: none; } }
@media (max-width: 720px) {
  .methods { gap: 8px; }
  .method { flex-direction: column; justify-content: center; gap: 8px; padding: 12px 6px; text-align: center; }
  .body span { display: none; }
}
@media (prefers-reduced-motion: reduce) { .line { animation: none; } }
</style>
