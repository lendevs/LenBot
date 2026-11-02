# Starts LenBot from this unpacked deployment package; current.json names the selected release.
$ErrorActionPreference = 'Stop'
$Version = '@VERSION@'
$Current = Join-Path $PSScriptRoot 'current.json'
if (Test-Path $Current) { $Version = (Get-Content -Raw -Encoding UTF8 $Current | ConvertFrom-Json).version }
$Release = Join-Path $PSScriptRoot "releases\$Version"
& (Join-Path $Release 'python\python.exe') -X utf8 -m len_bot.next.launcher $PSScriptRoot
exit $LASTEXITCODE
