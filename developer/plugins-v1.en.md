# Plugin interface v1

[中文](plugins-v1.md)

## Minimal plugin

A plugin package directory contains `plugin.toml` and `__init__.py`, and `__init__.py` defines exactly one `Plugin` subclass. Start from the [plugin template repository](https://github.com/lendevs/lenbot-plugin-template). Plugins interact with the host through the public `len_bot.plugin` package.

The manifest requires the fields below. `name` matches the installed directory name; a Git repository root or ZIP root does not need that directory name beforehand.

The public interface generation is **1**, frozen starting from 0.2.0. Subsequent 0.x releases only make compatible additions (optional parameters, new methods, optional manifest fields) without changing existing signatures or semantics; breaking changes increment the generation. The host loads plugins targeting the current generation.

```toml
name = "counter"
version = "1.0.0"
interface = 1
permissions = ["send"]
requires_lenbot = ">=0.2,<1"
requires_python = ">=3.13"
platforms = ["linux", "darwin", "win32"]
reload = "plugin"
authors = ["Plugin maintainer"]
license = "GPL-3.0-only"
description = "Per-scene counter"
```

- `version` is parsed and normalized with Python packaging rules (`X.Y.Z` recommended).
- `requires_lenbot` and `requires_python` are explicit version specifiers checked against the running host and Python interpreter.
- `platforms` uses Python `sys.platform` values: Linux (`linux`), macOS (`darwin`), and Windows (`win32`). Deployment packages cover Linux and Windows, the Docker image is Linux, and a source checkout may run on any of the three.
- `reload` is `plugin` (hot-reloadable without stopping other plugins) or `host` (applied on host restart).
- Optional `repository` and `homepage` are HTTP(S) URLs.
- Optional `data_version` (positive integer, default `1`) numbers the format of the plugin's data directory and KV store; see [Data versions](#data-versions).

`dependencies = ["pkg>=version"]` declares Python package requirements resolved by `uv` and installed into the instance's `.runtime/plugin-packages/<host version>-py313`, reinstalled when the host changes versions. Packages already installed in the host environment act as constraints, and conflicts report the underlying resolver output. Document external binaries, services, and credentials in the plugin's README.

### Permissions

Optional `permissions` lists the host capabilities the plugin calls. When declared, only listed capabilities are permitted; calling any unlisted capability raises `PermissionError` naming the missing permission.

```toml
permissions = ["send", "history"]
```

| Permission | Capability |
|---|---|
| `send` | Send messages in enabled scenes, including `ctx.reply` |
| `events` | Wake the chat model via `emit_event` |
| `history` | Read `recent_messages` and `messages_between` |
| `memory` | Call `ctx.memory` |
| `generate` | Run single-shot model calls via `ctx.generate` |
| `delegate` | Create background worker tasks via `ctx.delegate` on behalf of the requester |
| `network` | Download public images via `fetch_image` |
| `schedule` | Register cron jobs via `ctx.cron` |

Plugin-local KV, `data_dir`, logging, commands, message rules, tools, and notices require no permission entry. Duplicate or unknown permission names invalidate the manifest. Manifests without `permissions` retain full capabilities and appear as **Undeclared permissions** in the panel. New plugins and official plugins declare the exact capabilities they call.

### Process isolation

`isolation = "process"` runs the plugin in a dedicated worker subprocess; the default `inline` runs in the host process.

- The host imports the plugin inside the subprocess, inspects its entry points, and registers commands, exact-text and regex rules, notices, `@background` loops, `@recall`, and `@compact`. Calls are forwarded over standard input/output as JSON lines.
- All `ctx` capabilities execute back in the host process under the host's recorded plugin name, scene checks, and `permissions`. For `ctx.delegate`, the host resolves the requester from the real triggering message rather than trusting subprocess input; background loops and completed invocations cannot delegate.
- If the subprocess crashes, exits, or writes an unparseable protocol line, pending calls fail, `@background` loops stop, and only that plugin is marked failed with its exit code while the host and other plugins continue. Reloading the plugin in the panel starts a fresh subprocess.
- On shutdown the host requests `stop()` first and terminates the subprocess on timeout or cancellation. Subprocess `print` output goes to `stderr`.
- `@tool`, `@memory_tool`, `ctx.cron`, and `ctx.start_task` are not supported in `process` mode; plugins using them report the reason on load. Cross-process values must serialize to JSON (images transfer as base64).
- Subprocesses share the host Python environment; `process` mode isolates crashes while keeping the same OS file and network permissions as the host.

Public imports for plugin authors are `len_bot.plugin` (including `ChatMessage`, `Notice`, `Sender`, `Segment`), `len_bot.plugin_testing`, `len_bot.image_assets`, and `len_bot.text_cards`. Modules under `len_bot.next` are internal.

## Installation and maintenance

### Sources

- **Git**: Provide a complete HTTPS or `ssh://` URL in the panel, optionally pinned to a tag, branch, or commit. The repository root must contain `plugin.toml` and `__init__.py`. Private repositories use local Git credentials. Omitting `ref` tracks the default branch on updates; specifying `ref` re-fetches that ref.
- **ZIP**: `plugin.toml` and `__init__.py` sit either at the archive root or inside a single top-level directory. Archives fail validation on path traversal, duplicate paths, symlinks, `.pyc` bytecode, more than 4096 entries, or more than 200 MiB compressed/extracted (macOS Finder metadata is ignored). ZIP preparation works offline; installing new Python dependencies may still access the network.

Both sources prepare a **candidate version** without interrupting the currently running plugin. After saving candidate configuration in the panel, click apply. Newly installed plugins start disabled until enabled and assigned to scenes.

### File layout

All plugin files live under `plugins/` in the instance root:

| Content | Path |
|---|---|
| Installed source | `plugins/<name>` |
| Staged candidate | `plugins/.candidates/<name>` |
| Installation record | `plugins/.installations/<name>.json` |
| Staged configuration | `plugins/.installations/.candidate-values/` |
| Business data | `plugins.data_directory/<name>` (defaults to `plugins/.data/<name>`) |

Active plugin configuration and enabled scenes are stored in `lenbot.config.json`. Staged candidate values move into `lenbot.config.json` when the candidate is applied and are discarded if the candidate is canceled. `plugins.paths` defaults to `["plugins"]`; directories copied into `plugins/` manually are discovered as unmanaged plugins.

### Applying changes

- Applying a managed Git candidate aborts if the installed working tree has local modifications or untracked files (excluding host-generated `__pycache__`).
- Switching a plugin's Git repository URL or switching between Git and ZIP requires explicit source replacement in the panel and preserves the plugin's data directory.
- When dependencies are unchanged and `reload = "plugin"`, the host stops only that plugin, swaps source directories, re-imports, and calls `start()`. Saving configuration or enabled scenes also reloads only that plugin.
- When dependencies change or `reload = "host"`, applying marks the candidate pending restart. On explicit restart, after the old host exits cleanly, the launcher runs `len_bot.next.maintenance.apply_plugins` under the instance lock to validate candidate configuration, resolve combined Python dependencies, swap source directories, and start the new host. If dependency resolution fails, the launcher exits while keeping the candidate and error message intact.

For instances running `len_bot.next.host` directly without the launcher, stop the host, run `python -m len_bot.next.maintenance.apply_plugins` in the instance root, and start the host again. After rebuilding a Python virtual environment, restore installed plugin requirements with `python -m len_bot.next.maintenance.plugin_dependencies`. Deployment details are in [deploy/current/README.md](../deploy/current/README.md).

### Canceling, disabling and uninstalling

- **Cancel candidate** keeps the installed source; canceling an unapplied first installation removes its configuration entry.
- **Disable** stops the plugin while keeping configuration, scene assignments, and data.
- **Uninstall** removes source, candidates, and configuration while keeping business data and shared Python packages. Data deletion is a separate action while the plugin is stopped.

### Rollback

Applying a new version moves the previous source to `plugins/.previous/<name>` alongside its previous parameters, enabling one-step rollback in the panel. If the new version fails during import, `migrate_data`, or `start()`, the host automatically restores the previous source, parameters, and pre-migration data backup.

### Data versions

Plugin data and `kv.sqlite3` live in `ctx.data_dir`. The host records the current `data_version` in `.lenbot-data.json` (existing directories without that file count as version `1`; new empty directories take the manifest's `data_version`).

When the manifest's `data_version` exceeds the recorded version, before calling `start()` the host:

1. Copies `ctx.data_dir` to `plugins.data_directory/.backups/<name>-v<old>-<timestamp>`.
2. Calls `await plugin.migrate_data(from_version)` while `ctx.data_dir` and KV are available.
3. Writes the new version number and calls `start()`, or restores the backup and marks the plugin failed if `migrate_data` raises.

Raising `data_version` without implementing `migrate_data` fails startup. A manifest `data_version` lower than the recorded version is rejected; rolling back across a data migration requires restoring the matching directory from `.backups`.

See [plugin-examples.md](plugin-examples.md) for standalone plugins and [plugin-catalog.md](plugin-catalog.md) for the static discovery catalog format.

## Entry points

```python
from len_bot.plugin import Plugin, Invocation, command, fullmatch, regex, tool, background, on_notice
```

| Decorator | Async handler signature | Behavior |
|---|---|---|
| `@command("query", "Description")` | `self, ctx: Invocation, args: str` | Matches `/query` and passes remaining text in `args` |
| `@fullmatch("live today", "Description")` | `self, ctx: Invocation` | Matches exact trimmed plain text |
| `@regex(r"find (?P<name>.+)", "Description", priority=0)` | `self, ctx: Invocation, match` | Python `re.fullmatch`; read named groups from `match` |
| `@on_notice("group_increase")` | `self, ctx: Invocation, notice` | OneBot `notice_type` or `type.sub_type` |
| `@tool("plugin_read", "Full description", summary="Short summary", needs_source=False)` | `self, ctx: Invocation, ...` | Typed schema for chat model tool discovery; returns `str` or JSON value |
| `@background(every="5m")` | `self, ctx: PluginContext` | Waits one interval after each run finishes (minimum 10 seconds) |
| `@recall()` | `self, request: RecallRequest` | Supplies per-turn automatic recall when `memory_plugin` names this plugin |
| `@memory_tool("Description")` | `self, ctx: Invocation, ...` | Supplies the scene's `memory` tool when `memory_plugin` names this plugin |
| `@compact()` | `self, request: CompactRequest` | Writes compaction recaps when `recap_plugin` names this plugin |

Each method takes one entry decorator. Matching order is command, `fullmatch`, then `regex` (sorted by `priority` descending). At most one handler consumes a message and does not wake the chat model. By default matching considers plain text after stripping a leading reply segment or mention of the bot itself. Pass `allow_mentions=True` to `@command` to accept mentions inside command arguments: real target segments remain in `ctx.message.segments` while each mention becomes a single space in `args`. Media segments are not matched by text rules.

Plugin commands match before built-in host commands. Registering `/角色` overrides the host persona-switching command in scenes where the plugin is active.

Operators can disable individual text rules per plugin via `plugins.disabled_rules` in `lenbot.config.json` (for example `"disabled_rules": {"asoul": ["今日直播"]}` using `/command`, exact text, or regex pattern strings); disabled rules pass through as normal chat messages.

Handler return values are recorded as background context for subsequent chat turns; sending a message to the scene requires `await ctx.reply(...)`. If a `@tool` calls a model internally, state that in its description.

### Automatic recall

Setting a scene's `memory_plugin` to an enabled plugin delegates per-turn automatic recall to that plugin's `@recall` entry (at most one per plugin) and suspends native recall and background extraction for that scene while keeping existing native memory files intact. Saving `memory_plugin` or `recap_plugin` in the panel switches at the end of the scene's current turn; uninstalling the plugin returns the scene to native memory.

`@memory_tool("Description")` provides that scene's `memory` tool for the chat model, other plugins' `ctx.memory()`, and task workers (subject to persona `memory` tool permission; without `@memory_tool`, the scene has no `memory` tool). To read existing native files during migration, call `await self.ctx.native_memory(scene, arguments)` (`browse`, `read`, `search`, `history`).

```python
from len_bot.plugin import Plugin, RecallBlock, RecallRequest, recall

class Notes(Plugin):
    @recall()
    async def remember(self, request: RecallRequest) -> list[RecallBlock]:
        hits = await self.search(request.scene, request.messages, limit=5)
        return [RecallBlock(hit.title, hit.text) for hit in hits]
```

| `RecallRequest` field | Content |
|---|---|
| `scene`, `persona`, `turn_id` | Scene ID, active persona ID, current turn ID |
| `observed_at` | Turn start timestamp in Unix seconds |
| `messages` | Latest 8 read or delivered messages in chronological order (excluding undelivered bot messages) |
| `recap` | Current compaction recap or `None` |
| `tasks` | Active work tasks, one line per task |
| `budget_chars` | Character budget from `memory.recall_budget_chars` (or `1500` when native memory is unconfigured) |

The host keeps non-blank `RecallBlock`s in order, truncating output past `budget_chars`, and records them under `plugin:<name>` with `title` as path for all requests in that turn. Recall times out after 10 seconds; timeouts or errors log on the plugin and continue the turn without recall.

Plugins indexing raw chat messages via `ctx.messages_between` report progress with `await self.ctx.report_memory_progress(scene, message.id)` (monotonic, restricted to the scene's active `memory_plugin`) so `retention.message_days` preserves unprocessed messages. Switching back to native memory resumes native extraction from the latest message at switch time.

### Compaction recap

When a scene's `recap_plugin` names an enabled plugin, conversation compaction calls that plugin's `@compact` entry (at most one per plugin):

```python
from len_bot.plugin import CompactRequest, Plugin, compact

class Notes(Plugin):
    @compact()
    async def fold(self, request: CompactRequest) -> str:
        return await self.ctx.generate(request.scene, "Summarize into a recap:\n" + request.source)
```

`CompactRequest(scene, persona, turn_id, source, budget_tokens)` provides the current recap plus complete oldest conversation entries (`source`, never splitting a tool call from its results) and `budget_tokens` (estimated by the host as UTF-8 bytes divided by 3). Within a 120-second timeout, non-blank output within `budget_tokens` commits the new recap, advances the compaction cursor, and resets discovered tools in one transaction; failures preserve existing history and end the current turn. Persona handover recaps always use the native prompt.

## Configuration form

The panel renders a settings form from `[config.<field>]` declarations in `plugin.toml`. Every field requires `type` and `description`; fields with `default` are optional and others are required. Validated values appear in `ctx.config`.

| Type | Value | Panel control | Width |
|---|---|---|---|
| `string` | Text | Single-line input, or textarea when `multiline = true` | Half; full when multiline |
| `secret` | Masked text | Password input; leaving an already-saved secret empty preserves it | Half |
| `integer`, `number` | Numeric | Number input showing bounds (`integer` spans ≤ 100 get `−`/`+` buttons) | Half |
| `boolean` | Boolean | Switch row | Half |
| `string_list` | List of strings | Tag input (Enter or pasted lines add items) | Full |
| `scene` | Single scene ID | Scene picker showing configured group avatars and names (no `default`) | Half |
| `scene_list` | Multiple scene IDs | Multi-scene picker (`default` may only be `[]`) | Full |
| `path` | Absolute path | Monospace input (`default = ""` permits blank) | Full |
| `url` | HTTP(S) URL | URL input (`default = ""` permits blank) | Full |
| `object_list` | List of objects | Collapsible summary rows expanding into child fields | Full |

Optional attributes: `label`, `group` (top-level fields only), `placeholder`, `options` (values or `{ value = "auto", label = "Auto" }`; ≤ 3 options with labels ≤ 8 characters render as segmented buttons, otherwise a dropdown), `minimum`/`maximum`, and `object_list.fields.<child>` (one level of child fields of any type except `secret` and `object_list`).

### Form layout

- Each `group` renders as a two-column card in order of first appearance; ungrouped plain fields share a leading untitled card, and each ungrouped `object_list` gets its own card showing its item count. Four or more cards display a section jump list on wide screens.
- Labels sit above controls with `description` in a tooltip; missing required values, out-of-range numbers, or invalid JSON show inline errors. Collapsed `object_list` rows summarize their first non-empty string (or numeric) child followed by secondary fields and badges.
- Runtime parameters live in `lenbot.config.json`; `ctx.get_kv` / `set_kv` / `delete_kv` are reserved for runtime business state.

### Declaration guidelines

Keep `label` concise (include units such as `Timeout (s)`), explain limits in `description`, place the identifying string field first in `object_list.fields`, group forms with more than 6 fields, represent mutually exclusive modes with `options`, and pair half-width fields cleanly.

## How tool definitions reach the chat model

Each `@tool` carries three layers of documentation:

- `summary`: shown in the discovery catalog and `tool_search` results (defaults to the full `description` verbatim when omitted).
- `description`: full callable instructions loaded after discovery.
- Typed parameters with defaults and `Annotated[..., Field(description=..., examples=...)]`: exported as JSON Schema (with auto-generated Pydantic titles stripped). Python docstrings, `README.md`, manifest `description`, and worker `SKILL.md` files are not injected into chat prompts.

The active persona must allow both `tool_search` and the tool name. Discovered tools become callable on the next model request within the session until compaction resets discovery.

Cross-tool workflows belong in an optional package-relative guide declared in `plugin.toml`:

```toml
[model]
instructions = "prompts/tools.md"
```

When at least one allowed tool from the plugin has been discovered, `instructions` is loaded once into the system prompt, refreshed on plugin reload, and withdrawn on disable, uninstall, or compaction.

Tools may return `str` or JSON-serializable `dict`, `list`, `int`, `float`, `bool`, or `None` (no tuples, arbitrary objects, non-string dict keys, or non-finite floats). Current scene IDs come from `ctx.scene` rather than model parameters. Distinguish data lookups, confirmed platform deliveries (`Sent.status == "sent"`), and background jobs (`{"status": "started", "delivery": "plugin"}`) in return values.

## Organizing tools by capability

Group related list, search, and detail operations into one capability tool discriminated by a strict `action` union, while keeping read queries separate from message sending and account writes:

| Plugin | Tools |
|---|---|
| `asoul` | 4 (`schedule`, `dynamics`, `creations`, card sending) |
| `bilibili` | 5 (video info, search, live/follow monitor, account read, account write) |
| `group_digest` | 2 |
| `gscore_adapter` | 1 |
| `counter` (template) | 2 |

```python
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

class Query(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

class Search(Query):
    action: Literal["search"]
    query: str = Field(description="Search keywords")

class Read(Query):
    action: Literal["read"]
    item_id: str = Field(description="Item ID returned by search")

Request = Annotated[Search | Read, Field(discriminator="action")]

@tool("content_query", "Search or read items.", summary="Query items")
async def query(self, ctx: Invocation,
                request: Annotated[Request, Field(description="Search or read request")]) -> dict:
    if request.action == "search":
        return await self.search_source(request.query)
    return await self.read_source(request.item_id)
```

## Verified request source

Tools that delegate worker tasks or perform account-level actions set `needs_source=True`. The host automatically adds a required `source_message_id` parameter to the model schema (do not declare `source_message_id` in the Python signature), verifies the referenced message in the current scene, and populates `Invocation.message`:

```python
@tool("owner_action", "Run an owner-requested action.",
      summary="Owner action", needs_source=True)
async def action(self, ctx: Invocation) -> dict:
    ctx.require_owner()
    return {"requester": ctx.message.sender.uid}
```

A valid source message must be saved in the current scene, not recalled, received from a non-self user, and not sent by a known bot or blocklisted account.

## Configuration availability

Override synchronous `unavailable_tools(self, scene: str) -> dict[str, str]` to map unconfigured tool names to human-readable reasons (never include credentials). Unavailable tools remain visible in the panel's **Tools & skills** preview tab alongside scene enablement, persona permission, schema, and shared guides, while discovery and execution skip them.

## Invocation context

- Command, `fullmatch`, `regex`, and `needs_source=True` tool calls populate `Invocation.message`; ordinary tools and cron handlers have `ctx.message == None`.
- Scene IDs (`onebot:group:80001`) and user IDs (`onebot:70001`) always carry their platform prefix.

| Capability | Usage |
|---|---|
| Reply | `await ctx.reply(text)`, `reply_image(data, description)`, `reply_parts(parts)` |
| Message parts | `Text(text)`, `Image(bytes, description)`, `Mention("onebot:70001")` |
| KV store | `await ctx.get_kv(key, default=None)`, `set_kv(key, value)`, `delete_kv(key)` (plugin-scoped; include `scene` in keys for per-scene records) |
| Recent history | `ctx.recent_messages(limit=20)` (current scene, up to 100) |
| Time-window history | `ctx.messages_between(after, before, offset=0, limit=200)` (`after <= time < before`, chronological, up to 500 per page) |
| Memory | `await ctx.memory(arguments)` (active scene memory tool); `await self.ctx.native_memory(scene, arguments)` (read-only native files) |
| Wake chat model | `await ctx.emit_event(text)` |
| Scene clock | `ctx.now()`, `ctx.timezone()` |
| Owner check | `ctx.require_owner()` |
| Verified public image | `await ctx.fetch_image(url, timeout_seconds=15)` |

`self.ctx` (`PluginContext`) is used in `start()`, `stop()`, and `@background`, where scene-bound methods take an explicit `scene` argument. `self.ctx.scenes` lists enabled scenes whose chat switch is currently on. `Sent.status` is one of `sent`, `failed`, `unconfirmed`, `simulated`, or `partial`.

Public image and card rendering helpers are `len_bot.image_assets` (`inspect_image`, `MAX_IMAGE_BYTES`, `MAX_IMAGE_PIXELS`, `OriginalImage`) and `len_bot.text_cards` (`CardSection`, `TextCards`, `CardPage`). Run CPU-bound rendering in `await asyncio.to_thread(...)`.

## Single generation, work tasks and scheduled jobs

### `generate`

`await ctx.generate(prompt, role="mind", system=...)` (`role` is `"mind"` or `"learner"`, falling back to `"mind"` when `"learner"` is unconfigured) runs one model request under host concurrency slots and usage accounting (`plugin` recorded on `model_calls`) and returns text without sending.

### `delegate`

`await ctx.delegate(goal, deliverable, context="", materials=())` requires a verified non-self `ctx.message` (from a command/rule or `needs_source=True` tool) and submits a container work task under the sender's permissions; completion returns to the scene session asynchronously.

### Scheduled jobs

Register five-field cron jobs in `start()` with `self.ctx.cron(name, "0 8 * * *", handler, scene=scene, timezone=self.ctx.timezone(scene))` using explicit IANA timezones. Registrations live for the current plugin run; restarts schedule from the current time without replaying offline intervals.

### Plugin skills

Files under `skills/<skill-name>/SKILL.md` are exposed read-only to task workers in scenes where the plugin is enabled, subject to persona `skills` permissions.

## Lifecycle and errors

`start()` (60-second timeout) acquires resources and `stop()` (30-second timeout) releases them; `migrate_data` has no timeout. Register long-lived plugin coroutines via `self.ctx.start_task(name, coroutine)` so the host cancels them on shutdown. Unhandled handler exceptions log `plugin_error` and end only that invocation. Use `self.ctx.log` (`logging.Logger`) to write structured entries to `logs/lenbot.jsonl` tagged with plugin, scene, turn, and tool call IDs.

Each plugin exposes in-memory `health` (`level` in `ok`, `degraded`, `failed`, `stopped`, `starting`, plus `errors_last_hour`, `failing`, `last_error_at`) via `GET /api/host/plugins/health`.

## Local testing and publishing

`len_bot.plugin_testing.PluginTest` runs the real plugin lifecycle, config validation, rule matching, tool boundary serialization, and on-disk KV in a temporary directory without OneBot, panel, or worker containers (all sends record as `simulated`):

```python
from pathlib import Path
from len_bot.plugin_testing import PluginTest

async def check():
    async with PluginTest(Path("counter"), config={"step": 2}) as bot:
        assert await bot.message("计数加一")
        assert bot.deliveries[-1].text == "本群计数：2"
        result = await bot.tool("counter_read", {})
        assert "2" in result
```

- Pass `scenes`, `owners`, `now=lambda: 1791298800`, or `data=Path("tests/data-v1"), data_version=1` (runs `migrate_data` before `start()`) in the constructor.
- `message(text, scene=..., sender=..., parts=...)` and `add_message(...)` support `Segment` lists to test mention and media matching boundaries; `add_message` returns a `ChatMessage` whose `platform_message_id` can be passed as `source_message_id`.
- `recall(...)`, `memory(...)`, and `compact(...)` exercise `@recall`, `@memory_tool`, and `@compact` under host checks.
- `preview_tools(scene)` returns discovery summaries, full descriptions, shared guides, schemas, `needs_source`, allowed scenes, and unavailability reasons.
- `wait_tasks(name_prefix)` awaits one-shot background tasks registered via `start_task` matching `name_prefix`.
- Model calls are disabled by default; pass `models={...}` pointing at a local synthetic protocol server when testing `ctx.generate`.

To publish, generate a repository from [lenbot-plugin-template](https://github.com/lendevs/lenbot-plugin-template):

- `plugin-ci.yml` runs the plugin's tests and `scripts/package_plugin.py` against LenBot `master` (or a pinned `host_ref`).
- Pushing a `v*` tag matching `plugin.toml` triggers `plugin-release.yml` to attach an importable release ZIP containing source, `prompts/`, `skills/`, `assets/`, and license files.
- **License**: The LenBot host is `AGPL-3.0-only`, and the plugin template is `GPL-3.0-only`. Because `inline` plugins run in the host process, `GPL-3.0` is recommended (GPLv3 Section 13 permits combining GPLv3 works with AGPLv3 works).

Before 0.2.0 is released, official plugin CI tracks host `master` and host CI runs the pinned official plugin test suites from `plugin_catalog.json` on every push.
