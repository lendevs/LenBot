<p align="center"><img src="website/public/brand/lenbot-banner.png" alt="LenBot：自主决策的群聊 Agent" width="860"></p>

<p align="center">
  <a href="README.en.md">English</a> ·
  <a href="https://lendevs.github.io/LenBot/">文档站</a> ·
  <a href="https://lendevs.github.io/LenBot/guide/quick-start">快速开始</a> ·
  <a href="https://lendevs.github.io/LenBot/develop/plugins">写插件</a>
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0-b4476a">
  <img alt="Python" src="https://img.shields.io/badge/python-3.13%2B-b4476a">
  <img alt="Platform" src="https://img.shields.io/badge/platform-QQ-b4476a">
</p>

**LenBot 是自主决策的群聊 Agent。** 何时开口、回复谁、先查什么、何时跟进，由模型在多步工具循环中决定。接入 QQ（OneBot v11），只需要一个聊天模型和它的 API Key。

<img src="website/public/screenshots/live.gif" alt="群聊现场：群友 @ Bot 后，回合卡片逐步展开，先查询聊天记录，再分两条回复" width="860">

<sub>面板的群聊现场实时显示每一个回合：查询了哪些聊天记录、每一步的想法、最后发出的消息。录屏来自演示实例。</sub>

## 特点

- **统一的决策回合**：唤醒后，判断、查询和回复由同一个聊天模型在一个工具循环中完成。不回复也是一种决定。
- **先查证再回答**：搜索网页、读取正文、查询聊天记录和记忆、识别图片、读取合并转发，也可以接入 MCP 服务。搜索和读网页均可选择免费方式或付费接口。
- **自己安排跟进**：模型可以给群友设提醒，也可以提醒自己之后再看，或把耗时工作交给后台任务。
- **记忆与学习**：记忆以 Markdown 文件按群保存在本地。群内空闲时，聊天模型在同一会话中整理记忆，并学习群内的说法、黑话和回复效果，复用服务商的缓存。
- **角色**：角色包至少包含名字和人物设定。每个群可以使用不同的角色，切换无需重启。
- **插件**：用 Python 添加命令、定时推送和模型工具，按群启用，修改设置无需重启。
- **网页面板**：首次配置、日常设置、试聊和日志都在面板中完成，每一轮的经过完整可查。

## 快速开始

需要 [uv](https://docs.astral.sh/uv/)、Node.js 22、一个已登录 QQ 的 OneBot 实现（例如 [NapCat](https://github.com/NapNeko/NapCatQQ)）和模型服务的 API Key。

```sh
git clone https://github.com/lendevs/LenBot.git
cd LenBot
./scripts/install.sh
uv run --no-sync len-bot
```

第一次启动时，终端输出首次配置的链接。在浏览器中打开，按五步向导连接 QQ、选择模型和角色。发送方式建议先选模拟发送，在面板的**对话测试**中试聊，确认效果后再改为真实发送。

详细步骤见[快速开始](https://lendevs.github.io/LenBot/guide/quick-start)。

<img src="website/public/screenshots/home.png" alt="面板总览" width="860">

## 文档

| 内容 | 位置 |
|---|---|
| 安装、配置和日常使用 | [文档站](https://lendevs.github.io/LenBot/) |
| 编写插件 | [写插件](https://lendevs.github.io/LenBot/develop/plugins)、[插件接口 v1](developer/plugins-v1.md)、[插件模板](https://github.com/lendevs/lenbot-plugin-template) |
| 编写角色包 | [写角色包](https://lendevs.github.io/LenBot/develop/personas)、[示例角色小然](examples/personas/companion/) |
| 本机配套服务 | [部署资料](deploy/README.md) |
| 内部结构 | [开发者文档](developer/README.md) |
| 参与开发 | [CONTRIBUTING](CONTRIBUTING.md) |

## 状态

LenBot 仍在开发中，尚未发布版本，请从源码运行。提示词只有中文，面板支持中文和英文。

## 许可证

原创代码采用 [AGPL-3.0-only](LICENSE) 许可，详见 [NOTICE](NOTICE)。第三方依赖和独立服务沿用各自的许可，见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
