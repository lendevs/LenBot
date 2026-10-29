# Contributing

[中文](CONTRIBUTING.md)

If you are only authoring a persona package or a plugin, skip this page and start from [Plugin interface v1](developer/plugins-v1.en.md), the [plugin template](https://github.com/lendevs/lenbot-plugin-template) or the extension section of the documentation site.

## Local development

You need [uv](https://docs.astral.sh/uv/) and Node.js 22.

```sh
./scripts/install.sh       # uv sync and build the web panel
uv sync --locked           # install the dev dependency group for tests
uv run --no-sync len-bot   # start; opens the first-time setup wizard when unconfigured
```

The repository root doubles as your local instance directory: `lenbot.config.json`, databases, `state/` and `personas/` live there and are ignored by Git. Development and daily local runs share the same checkout started through `uv`.

After changing frontend files, run `npm run typecheck`, `npm run lint` and `npm run build` in `src/len_bot/web/frontend`. The build output in `src/len_bot/web/static/dist/` is not committed to Git. Use `npm run dev` during interactive frontend work; conventions are documented in the [panel frontend guide (zh)](developer/panel.md).

When `len-bot` starts from a Git checkout, the launcher checks the frontend source fingerprint: if the built panel is missing or out of date, it runs `npm ci` and `npm run build` before starting; otherwise it starts directly.

### Testing on an isolated copy

To verify changes without touching live instance data, stop the running instance first and export a test copy:

```sh
uv run --no-sync python -m len_bot.next.maintenance.test_copy . /tmp/lenbot-test --panel-port 8089
cd /tmp/lenbot-test && uv run --project /path/to/LenBot --no-sync len-bot
```

The command copies `lenbot.config.json` together with the databases, memory, personas, reference files and task directories it points to. The copy switches to simulated delivery, disconnects OneBot, listens on the specified panel port, and rewrites absolute paths inside the original instance root to point into the copy. Model providers, plugins and background task services run with their configured bindings.

## Source layout

The runtime core lives in `src/len_bot/next/`. The entry module is `len_bot.next.host`, started by the `len-bot` CLI through `launcher.py`. Module interactions are covered in the [architecture overview (zh)](developer/architecture.md).

| Path (under `src/len_bot/next/`) | Responsibility |
|---|---|
| `host.py`, `launcher.py`, `instance_lock.py` | Host assembly, launcher, single-instance lock |
| `config.py`, `configuration/` | Root configuration and domain validation models |
| `runtime/` | Platform lifecycle, scene scheduling, live settings updates, logging and retention |
| `platform/` | Unified identities and messages, OneBot v11 adapter |
| `chat/` | Scene sessions, wake and batching, context assembly, expression delivery, tool dispatch, reminders |
| `models/` | Model protocol requests, concurrency slots, token budgets and usage ledger |
| `persona/`, `learning/` | Persona package loader; group learning for phrasing, slang, stickers and reply reception |
| `memory/` | Local Markdown memory storage, hybrid index, automatic recall and background curation |
| `reference/` | Persona knowledge and group reference file extraction, full-text index and lazy vector retrieval |
| `work/`, `browser/` | Background tasks (Pi containers) and shared browser integration |
| `storage/` | SQLite schema, connection setup and strict JSON codecs |
| `plugins/` | Plugin discovery, manifest validation, inline and process-isolated execution, candidate staging and rollback |
| `tools/`, `media/` | Web search and page reading, skill catalog, MCP client, image and audio handling |
| `panel/` | Web panel backend routes and first-time setup wizard |
| `maintenance/` | Offline or read-only maintenance commands: health check, upgrades, reindexing, plugin dependencies, storage pools, test copies |
| `trials/` | Isolated test chats and persona draft trials inside the panel |

Other repository directories:

| Path | Contents |
|---|---|
| `src/len_bot/plugin.py`, `plugin_testing.py`, `text_cards.py`, `image_assets.py` | Stable public interfaces for plugins; plugins import exclusively from these modules |
| `src/len_bot/prompts/` | Framework prompt templates |
| `src/len_bot/default_personas/` | Default persona template (Xiaoran) copied during first-time setup |
| `src/len_bot/builtin_skills/` | Built-in background task skills |
| `src/len_bot/web/frontend/` | Vue 3 web panel frontend source |
| `src/len_bot/eval/` | Expression and social replay evaluation |
| `developer/` | Core design notes and Plugin interface v1 reference |
| `website/` | VitePress documentation site source; preview locally with `npm --prefix website run dev` |
| `deploy/` | Deployment package scripts, container recipes and shared updater controller `deploy/updater/` |
| `docker/next-worker/` | Background task container image and browser extension |
| `scripts/` | Installation, release packaging and evaluation scripts |
| `examples/` | Example persona, example memory plugin and public replay suites |
| `tests/` | Automated test suite |

Run maintenance modules with `uv run --no-sync python -m len_bot.next.maintenance.<module>`. Internal code imports directly from concrete modules; `__init__.py` files do not re-export symbols.

## Writing code

- Solve concrete problems only. Do not swallow exceptions to return fallback defaults, guess undeclared fields, or add runtime checks for cases already ruled out by types. When a model or external service call fails, do not silently switch models/services or mutate parameters to retry.
- Parse and validate external inputs (platform events, model and service responses, configuration files) once at the system boundary. On parse failure, raise an error containing the raw snippet.
- Catch exceptions only at the execution boundary of a single chat turn, a tool or plugin invocation, or a background task; log the original error and terminate that unit. Return tool error text verbatim to the chat model.
- Leave contextual judgment (request attribution, pronoun resolution, whom a message replies to) to the chat model; the host tracks only verified platform identities and execution state. Explain any new database table, persistent state or abstraction layer in the PR description.
- Use a module-level `logging.getLogger(__name__)` and emit structured events through `log_event(logger, 'event_name', **fields)` in `runtime/logs.py`; do not use `print`. Pass exceptions via `error=`, and store single-line `Type: message` strings (`error_text`) in database error columns. Bind correlation IDs with `log_context` at new long-running entry points.
- Read runtime configuration exclusively from `lenbot.config.json` in the instance root, updated by the panel while running. Do not add environment variable, `.env`, CLI flag or database configuration overrides.

## Tests

```sh
uv run --no-sync pytest -q
uv run --no-sync python -m compileall -q src/len_bot
uv run --no-sync ruff check src/len_bot scripts deploy/updater deploy/package tests
```

Automated tests cover three boundaries using anonymized real protocol samples:

- External protocol parsing: OneBot v11, Pi RPC, model provider protocols and search/memory service responses
- Identity and tool permission checks
- Configuration and plugin manifest validation

Do not mock internal call sequences, test private helper functions or snapshot full prompt text.

When modifying framework prompts or default persona materials, compare before and after replies with the [expression and social replay suites](examples/replay/README.md). Turn bad replies into replay cases before editing prompts rather than accumulating ad-hoc prohibitions. Commit general fictional cases to `examples/replay/` and keep cases derived from real group chats local only.

## Data format

Until the first release candidate (RC), all six format and interface numbers stay fixed at `1`. During pre-RC development, edit SQL `CREATE` statements and Pydantic configuration models directly without migration steps, and adjust or recreate local development instances manually when needed.

| Format or interface | Current value | Location |
|---|---|---|
| Plugin interface | `1` | `INTERFACE` in `src/len_bot/plugin.py` |
| Root configuration | `1` | `CONFIG_VERSION` in `src/len_bot/next/config.py` |
| Business database | `1` | `FORMAT_VERSION` in `src/len_bot/next/storage/store.py` |
| Memory job database | `1` | `FORMAT_VERSION` in `src/len_bot/next/memory/jobs.py` |
| Local memory index | `1` | `FORMAT_VERSION` in `src/len_bot/next/memory/local.py` |
| Plugin key-value store | `1` | `FORMAT_VERSION` in `src/len_bot/next/plugins/kv.py` |

The four SQLite databases above record their file type in `PRAGMA application_id` and their format version in `PRAGMA user_version`; the host opens only files matching both expected values. The reference retrieval index (`reference/library.py`) stores derived data only and rebuilds its tables automatically from source documents whenever its schema changes.

JSON payloads stored inside database columns decode strictly into dataclasses (`ChatMessage`, `Sender`, `Segment`, `Task`, `TaskFile`, `Schedule`, plus model call and memory job records) and are part of the persistent format contract.

Starting from the first RC, every persistent format change increments its version constant and adds a migration from the previous version in the `apply` step of `maintenance/upgrade.py`. The updater controller captures a full instance snapshot before running `apply`.

## Packaging and CI

```sh
uv run --no-sync python scripts/build_release.py /tmp/lenbot-release
```

The release build script compiles the frontend panel in an isolated staging tree and produces the source archive, wheel, Linux/macOS/Windows deployment bundles and release manifest.

Continuous integration ([ci.yml](.github/workflows/ci.yml) and [check.yml](.github/workflows/check.yml)) runs compilation, linting and unit tests on Python 3.13 (the minimum in `pyproject.toml`) and Python 3.14, checks workflow files with `actionlint`, and verifies the panel build and release packaging. Unit tests run on Linux; Windows and macOS are covered by the installation smoke workflow ([install-smoke.yml](.github/workflows/install-smoke.yml)).

## Submitting changes

- Use the [bug report template](.github/ISSUE_TEMPLATE/bug.md) and the [pull request template](.github/PULL_REQUEST_TEMPLATE.md).
- Run `git diff --check` before committing. Do not commit live configuration files, databases, credentials, personal personas or built frontend assets.
- State behavior changes, verified scope and unconfirmed items in commit messages.
- When user-facing behavior or developer interfaces change, update the corresponding documentation in `README.md`, `website/`, `developer/` or `deploy/`. Chinese is the primary language; update the four English mirror files (`README.en.md`, `CONTRIBUTING.en.md`, `deploy/README.en.md`, `developer/plugins-v1.en.md`) alongside their Chinese counterparts. After editing `website/`, run `npm --prefix website run build` to verify the build and internal links.
- Commit and document authorship is reserved for human contributors; do not add tool or model attribution trailers or machine email addresses.

## License

Code contributed to this repository is licensed under [AGPL-3.0-only](LICENSE); the standalone plugin template is licensed under GPL-3.0-only. Third-party code and asset notices live in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md); update that file whenever new third-party material is added.
