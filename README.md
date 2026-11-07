<picture>
  <source media="(prefers-color-scheme: dark)" srcset="website/public/readme/hero.dark.svg">
  <img src="website/public/readme/hero.svg" alt="LenBot：自主决策的群聊 Agent" width="100%">
</picture>

<p align="center">
  <a href="https://lendevs.github.io/LenBot/"><b>文档</b></a> ·
  <a href="https://lendevs.github.io/LenBot/start/quick-start">快速开始</a> ·
  <a href="https://lendevs.github.io/LenBot/develop/personas">写角色包</a> ·
  <a href="https://lendevs.github.io/LenBot/develop/plugins">写插件</a> ·
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/lendevs/LenBot/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/lendevs/LenBot?include_prereleases&color=b4476a&label=release"></a>
  <img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0-b4476a">
  <img alt="Python" src="https://img.shields.io/badge/python-3.13%2B-b4476a">
  <img alt="Platform" src="https://img.shields.io/badge/platform-QQ%20%7C%20Telegram%20%7C%20Feishu-b4476a">
</p>

**LenBot 是自主决策的群聊 Agent。** 何时开口、回复谁、先查什么，以及什么时候跟进，由 ReAct Loop 决定。接入 QQ（OneBot v11）、Telegram 和飞书，几个平台可以同时运行，需要一个聊天模型和它的 API Key。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="website/public/readme/turn.dark.svg">
  <img src="website/public/readme/turn.svg" alt="没人 @ 时，小然看到老周甩锅，先查询聊天记录找出原话，再分两条当场抓包" width="100%">
</picture>

## 能力

<p align="center">
  <a href="https://lendevs.github.io/LenBot/use/chatting"><picture><source media="(prefers-color-scheme: dark)" srcset="website/public/readme/listen.dark.svg"><img src="website/public/readme/listen.svg" alt="何时开口" width="49%"></picture></a>
  <a href="https://lendevs.github.io/LenBot/connect/web"><picture><source media="(prefers-color-scheme: dark)" srcset="website/public/readme/lookup.dark.svg"><img src="website/public/readme/lookup.svg" alt="先查再答" width="49%"></picture></a>
  <a href="https://lendevs.github.io/LenBot/use/tasks"><picture><source media="(prefers-color-scheme: dark)" srcset="website/public/readme/follow.dark.svg"><img src="website/public/readme/follow.svg" alt="定时提醒" width="49%"></picture></a>
  <a href="https://lendevs.github.io/LenBot/use/memory"><picture><source media="(prefers-color-scheme: dark)" srcset="website/public/readme/memory.dark.svg"><img src="website/public/readme/memory.svg" alt="长期记忆" width="49%"></picture></a>
  <a href="https://lendevs.github.io/LenBot/use/personas"><picture><source media="(prefers-color-scheme: dark)" srcset="website/public/readme/persona.dark.svg"><img src="website/public/readme/persona.svg" alt="角色包" width="49%"></picture></a>
  <a href="https://lendevs.github.io/LenBot/use/plugins"><picture><source media="(prefers-color-scheme: dark)" srcset="website/public/readme/plugin.dark.svg"><img src="website/public/readme/plugin.svg" alt="Python 插件" width="49%"></picture></a>
</p>

- **决策回合**：连发消息合批等待后唤醒，判断、查询与回复在同一个 Agent 循环中完成；没话可接就旁听，发言后等待对方下一句接话，无人接话时自动拉长插话间隔。
- **查证回答**：按需搜索网页并读取正文，查询聊天记录和长期记忆、检索角色与本群资料，还能识别图片和读取合并转发。
- **主动跟进**：模型可以为群友创建提醒、登记持续关注的事项，或把耗时工作交给隔离容器中的后台任务。
- **记忆学习**：记忆以 Markdown 文件按群保存在本地。学习群内的说法、黑话和回复效果。
- **角色包**：名字和人物设定即可组成一个角色，可配置说话方式、轮换风格，并附上样例、资料与表情库。
- **插件**：用 Python 添加命令和定时播报，或扩展模型工具与长期记忆实现，按群启用。

## 对话测试

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="website/public/readme/playground.dark.svg">
  <img src="website/public/readme/playground.svg" alt="对话测试页：依次以老周、橘子、小满的身份发言，小然在左侧回复，右侧列出每个回合" width="100%">
</picture>

在面板的对话测试里可以模拟群聊：添加群友、选择发言身份，再复制群内最近的消息作为初始上下文。[对话测试 →](https://lendevs.github.io/LenBot/start/playground)

## 快速开始

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="website/public/readme/setup.dark.svg">
  <img src="website/public/readme/setup.svg" alt="四步：选择部署方式、首次配置、模拟群聊、接入群聊" width="100%">
</picture>

把这段发给你的 Agent，它会问清部署方式和平台，再帮你装好并启动：

```text
请阅读 https://lendevs.github.io/LenBot/start/agent ，按页面中给 Agent 的部署步骤帮我部署 LenBot：先问我选择部署方式和要接入的聊天平台，再在这台机器上安装并启动，最后把首次配置链接交给我。
```

也可以自己部署。准备要接入的平台和聊天模型服务的 API Key：QQ 需要一个已登录的 OneBot v11 实现（例如 [SnowLuma](https://github.com/SnowLuma/SnowLuma)，推荐使用），Telegram 用 BotFather 给出的 Bot 令牌，飞书则准备一个企业自建应用。

| 部署方式 | 运行环境 | 文档 |
|---|---|---|
| Docker | Docker Engine 或 Docker Desktop | [Docker 部署](https://lendevs.github.io/LenBot/start/docker) |
| 部署包 | Linux（x64、arm64）、Windows（x64），解压即可启动 | [部署包](https://lendevs.github.io/LenBot/start/package) |
| 源码 | uv 与 Node.js 22，跟随 `master` 开发 | [源码运行](https://lendevs.github.io/LenBot/start/source) |

<details>
<summary><b>Docker</b></summary>

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.6
docker logs lenbot
```

</details>

<details>
<summary><b>部署包</b></summary>

从 [Releases](https://github.com/lendevs/LenBot/releases/tag/v0.2.6) 下载对应平台的部署包，解压后启动：

```sh
tar -xzf lenbot-0.2.6-linux-x64.tar.gz
lenbot-0.2.6-linux-x64/run
```

Windows 解压 `lenbot-0.2.6-windows-x64.zip` 后双击 `run.cmd`。

</details>

<details>
<summary><b>源码</b></summary>

```sh
git clone https://github.com/lendevs/LenBot.git
cd LenBot
./scripts/install.sh
uv run --no-sync len-bot
```

</details>

<img src="website/public/screenshots/home.png" alt="面板总览" width="100%">

## 文档

| 用途 | 入口 |
|---|---|
| 部署、接入与日常使用 | [文档站](https://lendevs.github.io/LenBot/) |
| 编写角色包 | [写角色包](https://lendevs.github.io/LenBot/develop/personas)、[示例角色小然](examples/personas/companion/) |
| 编写插件 | [写插件](https://lendevs.github.io/LenBot/develop/plugins)、[插件接口 v1](developer/plugins-v1.md)、[插件模板](https://github.com/lendevs/lenbot-plugin-template)、[插件开发 skill](skills/lenbot-plugin/SKILL.md) |
| 部署包、容器配方与本机运维 | [部署资料](deploy/README.md) |
| 核心架构与模块说明 | [开发者文档](developer/README.md) |
| 参与核心开发 | [CONTRIBUTING](CONTRIBUTING.md) |

内置提示词为中文，网页面板支持中文和英文。

## 许可证

原创代码采用 [AGPL-3.0-only](LICENSE) 许可，详见 [NOTICE](NOTICE)。第三方依赖和独立服务沿用各自的许可，见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
