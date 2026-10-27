# Contributing

[中文](CONTRIBUTING.md)

Plugin authors do not need this page; start from the [plugin guide](developer/plugins-v1.en.md) or the [plugin template](https://github.com/lendevs/lenbot-plugin-template).

## Local development

You need [uv](https://docs.astral.sh/uv/) and Node.js 22.

```sh
./scripts/install.sh       # uv sync and build the panel
uv sync --locked           # add the dev group when you want to run tests
uv run --no-sync len-bot   # start; opens the setup wizard if there is no configuration
```

The repository root is your local instance: `lenbot.config.json`, the database, `state/` and `personas/` live there and are ignored by Git. Development and local use share one checkout started with `uv`; there is no separate install.

After changing the frontend, run `npm run typecheck`, `npm run lint` and `npm run build` in `src/len_bot/web/frontend`. The output in `web/static/dist/` is not committed. `npm run dev` works for frontend work too. Frontend conventions are in the [panel frontend guide (zh)](developer/panel.md).

When `len-bot` starts from a Git checkout, the launcher checks whether the frontend content has changed. A missing or outdated panel is rebuilt with `npm ci` and `npm run build`; unchanged content starts directly.

### Testing on a copy

To keep the data in use untouched, stop the bot and make a test instance:

```sh
uv run --no-sync python -m len_bot.next.maintenance.test_copy . /tmp/lenbot-test --panel-port 8089
cd /tmp/lenbot-test && uv run --project /path/to/LenBot --no-sync len-bot
```

The command copies the configuration and the instance files it references (database, memory, personas, task directories and so on). The copy uses simulated delivery, does not connect to OneBot and listens on the given panel port; absolute paths pointing into the original instance are moved into the copy. Models, plugins and task services run normally in the copy, and model calls use tokens as usual.

## Source layout

The runtime core is in `src/len_bot/next/`. The entry point is `len_bot.next.host`; the `len-bot` command starts it through `launcher.py`. See the [architecture overview (zh)](developer/architecture.md).

| Path (under `src/len_bot/next/`) | Responsibility |
|---|---|
| `host.py`, `launcher.py`, `instance_lock.py` | Host assembly, launcher, instance lock |
| `config.py`, `configuration/` | Root configuration and per-domain settings |
| `runtime/` | Platform and scene runtime, lifecycle, logging, retention |
| `platform/` | Platform identities, unified messages and the OneBot adapter |
| `chat/` | Scene sessions, attention, context, expression, tool dispatch, reminders |
| `models/` | Model requests, budgets and usage |
| `persona/`, `learning/` | Persona packages; learning phrasing, slang, stickers and reply effects |
| `memory/` | Local memory text, index, recall and background curation |
| `work/`, `browser/` | Background tasks (Pi containers) and browser cooperation |
| `storage/` | Database schema and codecs |
| `plugins/` | Plugin runtime and installation; business plugins live in separate repositories |
| `tools/`, `media/` | Web, skills, MCP and other tools; image and voice handling |
| `panel/` | Panel backend and the first-run wizard |
| `maintenance/` | Commands run while stopped: update steps, reindexing, plugin dependencies, storage pools, test copies |
| `trials/` | Isolated trial chats in the panel |

Other directories:

| Path | Contents |
|---|---|
| `src/len_bot/plugin.py`, `plugin_testing.py`, `text_cards.py`, `image_assets.py` | Public interfaces for plugins; plugins import only from these |
| `src/len_bot/prompts/` | Prompts |
| `src/len_bot/builtin_skills/` | Task skills |
| `src/len_bot/web/frontend/` | The Vue panel |
| `src/len_bot/eval/` | Expression replay |
| `tests/` | Tests |
| `docker/next-worker/` | The task image |
| `deploy/` | Deployment material. `deploy/updater/` is the updater shared by packages and Docker |
| `website/` | Documentation site (VitePress); preview with `cd website && npm ci && npm run dev` |
| `scripts/` | Install and packaging scripts |
| `examples/` | The example persona and public replay cases |

Maintenance commands are run as `python -m len_bot.next.maintenance.<module>`. Import from concrete modules; `__init__.py` files do not re-export.

## Writing code

- Solve the problem at hand. Do not swallow exceptions and return defaults, guess field names, or check for cases the types already rule out. When a model or service call fails, do not automatically retry with another model, service or parameters.
- Parse external data (platform messages, model and service responses, configuration files) once at the entry point. If parsing fails, raise an error that includes the raw snippet.
- Catch exceptions only at the boundary of one chat turn, one tool or plugin call, or one task; log the original error and end that unit. Tool errors go back to the model verbatim.
- Leave contextual judgement (who a request belongs to, what a reference points to, who is replying to whom) to the model. The host keeps only real identities and the state needed to execute. When you add a table, a state or a layer, explain in the PR what problem it solves.
- Log through a module `logging.getLogger(__name__)` and record events with `log_event(logger, 'event', **fields)` from `runtime/logs.py`; do not `print`. Pass exceptions as `error=`; database error columns keep one line `Type: message` (`error_text`). New long-running entry points (background jobs, external callbacks) bind correlation IDs with `log_context`.
- Runtime settings come only from `lenbot.config.json` in the repository root and are saved by the panel while running. Do not add overrides through environment variables, dotenv, command-line flags or the database.

## Tests

```sh
uv run --no-sync pytest -q
uv run --no-sync python -m compileall -q src/len_bot
uv run --no-sync ruff check src/len_bot scripts deploy/updater deploy/package tests
```

Tests cover only the following. Test samples are anonymized real data.

- External protocol boundaries: parsing of OneBot, Pi RPC, and model and memory service responses
- Permissions
- Configuration validation

Do not mock call sequences, test private functions or snapshot prompts.

When changing prompts or persona expression, compare replies before and after with the [expression replay](examples/replay/). When you find a bad reply, write the situation down as a replay case before changing prompts, rather than piling prohibitions into the prompt. General situations go in `examples/replay/`; cases taken from real group chats stay on your machine and are not committed.

## Data format

LenBot has not been released yet. Until the first RC, all four format numbers stay at 1. Change the schema by editing the create statements and the configuration by editing its models, without upgrade steps; adjust or recreate a local instance by hand when needed.

| Number | Value | Where |
|---|---|---|
| Plugin interface | 1 | `INTERFACE` in `plugin.py` |
| Root configuration | 1 | `CONFIG_VERSION` in `config.py` |
| Business database | 1 | `FORMAT_VERSION` in `storage/store.py` |
| Memory job database | 1 | `FORMAT_VERSION` in `memory/jobs.py` |
| Local memory index | 1 | `FORMAT_VERSION` in `memory/local.py` |

The three databases name their file type in `application_id` and their format in `user_version`. LenBot opens only files whose number matches the current one.

JSON bodies stored in the databases decode strictly into dataclasses (`ChatMessage`, `Sender`, `Segment`, `Task`, `TaskFile`, `Schedule`, and the records inside model calls and memory jobs); their fields are part of the data format too.

From the first RC on, every format change bumps its number and adds an upgrade from the previous one to the `apply` step in `maintenance/upgrade.py`. The updater takes a full snapshot before that step.

## Packaging

```sh
uv run --no-sync python scripts/build_release.py /tmp/lenbot-release
```

This rebuilds the panel in a copy and produces the sdist, the wheel, the Linux/macOS/Windows packages and the release manifest. The project has no release yet; the release process will be documented once it is settled.

[CI](.github/workflows/ci.yml) compiles, runs tests, builds the panel and packages. Tests run on both Python 3.13 and 3.14 ([check.yml](.github/workflows/check.yml)): 3.13 is the minimum in `pyproject.toml`, and 3.14 catches problems on the next interpreter early. The same workflow runs actionlint over every workflow file. Unit tests run on Linux only; Windows and macOS are covered by the install smoke tests alone.

## Submitting changes

- Use the [bug template](.github/ISSUE_TEMPLATE/bug.md) and the [PR template](.github/PULL_REQUEST_TEMPLATE.md).
- Run `git diff --check` before committing. Never commit real configuration, databases, credentials, personal personas or build output.
- Commit messages say what behavior changed, what you checked and what is still unconfirmed.
- When behavior or interfaces change, update the matching docs in the README, the documentation site `website/`, `developer/` or `deploy/`. Chinese is the primary version; files that have an English version (README, CONTRIBUTING, deployment overview, plugin interface) are updated together. If you touch `website/`, run `npm run build` there; dead links fail the build.
- Authors are people. Do not add tool or model attribution to commits or PRs, such as `Co-Authored-By:` lines pointing to machine identities or `Generated with …` footers.

## License

Code contributed to this repository is licensed under [AGPL-3.0-only](LICENSE); the plugin template is GPL-3.0-only. Sources and licenses of third-party material are listed in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md); update it when you bring in third-party code or assets.
