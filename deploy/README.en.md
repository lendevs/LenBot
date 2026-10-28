# Deployment notes

[中文](README.md)

This directory holds templates, companion service configuration and maintenance notes for running LenBot. Setup and daily use are covered on the [documentation site (zh)](https://lendevs.github.io/LenBot/). For source installation, see [quick start (zh)](https://lendevs.github.io/LenBot/guide/quick-start). Candidate packages and Docker images are covered in [deployment installation (zh)](current/installation.md).

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
| [current/README.md](current/README.md) (zh) | Optional services: OneBot, models, embeddings, speech recognition, background tasks, public browser, panel access |
| [current/operations.md](current/operations.md) (zh) | Operations: panel details, plugins, memory, logs, upgrades, data formats |
| [current/lenbot.service](current/lenbot.service) | Linux systemd template |
| [current/start.command](current/start.command) | macOS double-click launcher |
| [current/services.compose.yaml](current/services.compose.yaml) | Embedding service (Ollama) |
| [current/start-asr.sh](current/start-asr.sh), [current/asr.md](current/asr.md) (zh) | Local speech recognition (whisper.cpp) |
| [current/task-storage.md](current/task-storage.md) (zh) | Storage pool and quotas for background tasks |
| [current/first-setup.example.json](current/first-setup.example.json) | Example first-setup submission |

`deploy/updater/` and `deploy/package/` provide the installer and updater; `current/Dockerfile` and `current/host*.compose.yaml` provide Docker recipes. CI produces candidate deployment packages. The Release workflow with `publish=false` builds candidate images for each architecture.

To update a source installation, follow the Chinese guide [更新与备份](../website/guide/maintenance.md).
