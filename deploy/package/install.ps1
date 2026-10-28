$ErrorActionPreference = 'Stop'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "缺少 uv。安装：powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`"；其他安装方式：https://docs.astral.sh/uv/getting-started/installation/"
}
& uv run --no-project --python 3.13 "$PSScriptRoot/install.py" @args
exit $LASTEXITCODE
