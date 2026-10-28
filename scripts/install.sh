#!/bin/sh
# Install checkout dependencies and build the panel.
set -eu
cd "$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
command -v uv >/dev/null || {
  printf '%s\n' '缺少 uv。安装：curl -LsSf https://astral.sh/uv/install.sh | sh' \
    '其他安装方式：https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
}
command -v node >/dev/null || {
  printf '%s\n' '缺少 Node.js 22 或更新版本。下载：https://nodejs.org/en/download' >&2
  exit 1
}
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error(`当前 Node.js ${process.version}，需要 22 或更新版本。下载：https://nodejs.org/en/download`); process.exit(1) }'
uv sync --locked --no-dev
(cd src/len_bot/web/frontend && npm ci && npm run build)
printf '%s\n' '安装和面板构建完成。' '启动：uv run --no-sync len-bot'
