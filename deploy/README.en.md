# Deployment notes

[中文](README.md)

This directory holds templates, companion service configuration and maintenance notes for running LenBot. Setup and daily use are covered on the [documentation site (zh)](https://lendevs.github.io/LenBot/). LenBot currently runs from source only; see [quick start (zh)](https://lendevs.github.io/LenBot/guide/quick-start).

## The instance directory

The instance directory holds everything for one bot. When running from source, the repository root is the instance directory.

| What | Where |
|---|---|
| Runtime configuration (with secrets) | `lenbot.config.json` |
| Chat database and memory job database | `database` from the configuration, plus the matching `.memory.sqlite3` |
| Persona packages | `personas/<persona id>/` |
| Plugins and plugin data | `plugins/`, `plugins/.data/` |
| Memory, prompt overrides, task directories | `state/` and others, as configured |
| Runtime log | `logs/lenbot.jsonl` |

The runtime configuration lives in `lenbot.config.json`. Change settings in the panel while LenBot runs, and stop LenBot before editing the file by hand.

## Files

| File | Contents |
|---|---|
| [current/README.md](current/README.md) (zh) | Optional services: OneBot, models, embeddings, speech recognition, background tasks, account browsing, panel access |
| [current/operations.md](current/operations.md) (zh) | Operations: panel details, plugins, memory, logs, upgrades, data formats |
| [current/lenbot.service](current/lenbot.service) | Linux systemd template |
| [current/start.command](current/start.command) | macOS double-click launcher |
| [current/services.compose.yaml](current/services.compose.yaml) | Embedding service (Ollama) |
| [current/start-asr.sh](current/start-asr.sh), [current/asr.md](current/asr.md) (zh) | Local speech recognition (whisper.cpp) |
| [current/task-storage.md](current/task-storage.md) (zh) | Storage pool and quotas for background tasks |
| [browser/README.md](browser/README.md), [current/browserskill-files.md](current/browserskill-files.md) (zh) | Account browsing companion and file transfer |
| [current/first-setup.example.json](current/first-setup.example.json) | Example first-setup submission |

`deploy/updater/`, `deploy/package/`, `current/Dockerfile` and `current/host*.compose.yaml` serve the package and Docker releases. The release process is not settled yet and has no user guide.
