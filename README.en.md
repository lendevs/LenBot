<p align="center"><img src="website/public/brand/lenbot-banner.en.png" alt="LenBot: a group chat agent that decides for itself" width="860"></p>

<p align="center">
  <a href="README.md">中文</a> ·
  <a href="https://lendevs.github.io/LenBot/">Documentation (zh)</a> ·
  <a href="https://lendevs.github.io/LenBot/guide/quick-start">Quick start (zh)</a> ·
  <a href="https://lendevs.github.io/LenBot/develop/personas">Personas (zh)</a> ·
  <a href="developer/plugins-v1.en.md">Plugin interface</a>
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0-b4476a">
  <img alt="Python" src="https://img.shields.io/badge/python-3.13%2B-b4476a">
  <img alt="Platform" src="https://img.shields.io/badge/platform-QQ-b4476a">
</p>

**LenBot is a group chat agent that decides for itself.** When to speak, whom to answer, what to look up first and when to follow up are decided by one chat model in a multi-step tool loop. It connects to QQ (OneBot v11) and requires only a chat model and its API key.

<img src="website/public/screenshots/live.gif" alt="Live view of a group: after the bot is mentioned, its turn unfolds step by step, first searching the chat history, then replying in two messages" width="860">

<sub>The live view in the panel shows every turn as it happens: which chat history was searched, what the model thought at each step and what it sent. The recording comes from a demo instance.</sub>

## Highlights

- **One decision loop.** Once woken, the same chat model decides, looks things up and replies within one tool loop. Staying silent and continuing to listen is a decision too.
- **Checks before answering.** Searches the web, reads pages, queries chat history and long-term memory, retrieves persona and group reference files, inspects images, opens forwarded threads and calls MCP (Model Context Protocol) servers on demand.
- **Follow-ups and background tasks.** The model can set reminders for group members, register ongoing topics to watch on its own, or hand long-running work to background tasks in isolated containers.
- **Memory, reference files and learning.** Memory is stored locally as Markdown files per group, and persona or group files support hybrid full-text and vector retrieval. While the group is idle, the chat model continues the same session prefix to curate memory and learn group phrasing, slang and reply reception, reusing the provider's prompt cache.
- **Persona packages.** A persona package requires only a name and a short profile, and can include voice notes, weighted rotating styles, dialogue examples, reference documents and stickers. Each group binds its own persona and switches without a restart.
- **Plugins.** Python plugins add commands, scheduled broadcasts, model tools or custom long-term memory backends, enabled per group and run either inline or in an isolated worker process.
- **Web panel.** First-time setup, daily settings, draft trial chats, token usage and step-by-step turn diagnostics all live in the web panel.

## Quick start

You need [uv](https://docs.astral.sh/uv/), Node.js 22, a OneBot v11 implementation logged in to QQ (for example [NapCat](https://github.com/NapNeko/NapCatQQ)) and an API key for a chat model service.

```sh
git clone https://github.com/lendevs/LenBot.git
cd LenBot
./scripts/install.sh
uv run --no-sync len-bot
```

On first start the terminal prints a one-time setup link. Open it in a browser and follow the five-step wizard to set up the panel account, connect QQ, fill in the owner account, and choose a chat model and persona. Start with simulated delivery, test a few turns in the panel's test chat, then switch to sending to QQ on the overview page.

Full setup and operations instructions are on the [quick-start page (zh)](https://lendevs.github.io/LenBot/guide/quick-start).

<img src="website/public/screenshots/home.png" alt="Panel overview" width="860">

## Documentation

The documentation site is in Chinese. The web panel is available in Chinese and English.

| Audience and topic | Entry |
|---|---|
| Setup and daily operations | [Documentation site (zh)](https://lendevs.github.io/LenBot/guide/introduction) |
| Writing persona packages | [Authoring personas (zh)](https://lendevs.github.io/LenBot/develop/personas), [example persona](examples/personas/companion/) |
| Writing plugins | [Authoring plugins (zh)](https://lendevs.github.io/LenBot/develop/plugins), [Plugin interface v1](developer/plugins-v1.en.md), [plugin template](https://github.com/lendevs/lenbot-plugin-template) |
| Deployment bundles, containers and host operations | [Deployment guide](deploy/README.en.md) |
| Core architecture and module notes | [Developer docs (zh)](developer/README.md) |
| Contributing to core | [CONTRIBUTING](CONTRIBUTING.en.md) |

## Status

LenBot is under active development and has no formal release yet; run it from source. Built-in prompts are in Chinese; the web panel supports Chinese and English.

## License

Original code is licensed under [AGPL-3.0-only](LICENSE); see [NOTICE](NOTICE). Third-party dependencies and separate services keep their own licenses; see [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).
