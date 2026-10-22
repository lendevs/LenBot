#!/bin/sh
# Install checkout dependencies and build the panel.
set -eu
cd "$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
command -v uv >/dev/null || { printf '%s\n' '请先安装 uv。'; exit 1; }
command -v node >/dev/null || { printf '%s\n' '请先安装 Node.js 22 或更新版本。'; exit 1; }
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error("需要 Node.js 22 或更新版本"); process.exit(1) }'
uv sync --locked --no-dev
(cd src/len_bot/web/frontend && npm ci && npm run build)
printf '%s\n' '安装和面板构建完成。' '启动：uv run --no-sync len-bot'
