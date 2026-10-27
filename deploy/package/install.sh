#!/bin/sh
set -eu
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
command -v uv >/dev/null || {
  printf '%s\n' '缺少 uv。安装：curl -LsSf https://astral.sh/uv/install.sh | sh' \
    '其他安装方式：https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
}
exec uv run --no-project --python 3.13 "$HERE/install.py" "$@"
