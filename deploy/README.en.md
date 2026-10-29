# Deployment notes

[中文](README.md)

This directory contains deployment recipes, system service templates, and command-line maintenance guides for running LenBot. Operator panel documentation is on the [documentation site (zh)](https://lendevs.github.io/LenBot/): setup is in [packages (zh)](https://lendevs.github.io/LenBot/start/package), [Docker (zh)](https://lendevs.github.io/LenBot/start/docker) and [from source (zh)](https://lendevs.github.io/LenBot/start/source), CI candidate packages and images are covered in [current/installation.md](current/installation.md) (zh), and source upgrades are in [maintenance and backups (zh)](https://lendevs.github.io/LenBot/use/maintenance).

## Instance directory

An instance directory stores all runtime state for one bot. When running from a Git checkout, the repository root is the instance directory; when installed from a deployment archive, runtime data lives under `instance/`.

| Content | Path |
|---|---|
| Runtime configuration (including secrets) | `lenbot.config.json` |
| Chat database and memory job database | `database` from configuration, plus matching `<database>.memory.sqlite3` |
| Persona packages | `personas/<persona-id>/` |
| Plugins and plugin data | `plugins/`, `plugins/.data/` |
| Long-term memory, prompt overrides, reference index, runtime state | `state/` (subpaths follow configuration) |
| Runtime log | `logs/lenbot.jsonl` |

Modify settings through the web panel while LenBot is running; stop LenBot before editing `lenbot.config.json` manually or running offline maintenance commands.

## Directory layout

| File or directory | Contents |
|---|---|
| [current/installation.md](current/installation.md) (zh) | Linux, macOS, and Windows deployment packages, Docker Compose setup, unattended JSON initialization |
| [current/README.md](current/README.md) (zh) | System service templates, companion containers (Ollama embeddings, worker image), startup order |
| [current/operations.md](current/operations.md) (zh) | Maintenance CLI commands, reverse proxies, local proxy `fake-ip`, snapshot upgrades, usage accounting |
| [current/asr.md](current/asr.md) (zh), [current/start-asr.sh](current/start-asr.sh) | Local macOS speech recognition (`whisper.cpp`) build and configuration |
| [current/task-storage.md](current/task-storage.md) (zh) | Dedicated filesystem storage pools for background tasks (Linux `ext4` / macOS `APFS`) |
| [current/lenbot.service](current/lenbot.service), [current/start.command](current/start.command) | Linux `systemd` service template and macOS double-click launcher |
| [current/Dockerfile](current/Dockerfile), `current/host*.compose.yaml`, [current/services.compose.yaml](current/services.compose.yaml) | Host container image, Compose recipes, and local embedding service |
| [current/first-setup.example.json](current/first-setup.example.json) | Sample JSON payload for unattended initialization |
| `package/`, `updater/` | Cross-platform archive installers and local update controller |

CI builds candidate deployment packages for each platform; running the Release workflow with `publish=false` builds multi-architecture candidate images for the host, task worker, and updater.
