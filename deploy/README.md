# 部署资料

[English](README.en.md)

本目录存放运行 LenBot 所需的模板、配套服务配置和维护说明。安装和日常使用见[文档站](https://lendevs.github.io/LenBot/)。LenBot 目前只能从源码运行，步骤见[快速开始](https://lendevs.github.io/LenBot/guide/quick-start)。

## 实例目录

实例目录保存一个 Bot 的全部数据。从源码运行时，仓库根目录就是实例目录。

| 内容 | 位置 |
|---|---|
| 运行配置（含密钥） | `lenbot.config.json` |
| 聊天数据库和记忆处理库 | 配置中的 `database`，以及同名的 `.memory.sqlite3` |
| 角色包 | `personas/<角色ID>/` |
| 插件和插件数据 | `plugins/`、`plugins/.data/` |
| 记忆、提示词修改、任务目录 | `state/` 等，位置由配置决定 |
| 运行日志 | `logs/lenbot.jsonl` |

运行配置保存在 `lenbot.config.json`。运行期间在面板中修改配置；手动编辑前先停止 LenBot。

## 文件

| 文件 | 内容 |
|---|---|
| [current/README.md](current/README.md) | 可选服务与配置：OneBot、模型、向量、语音转写、后台任务、公共浏览器、面板访问 |
| [current/operations.md](current/operations.md) | 使用与维护：面板操作细节、插件、记忆、日志、升级、数据格式 |
| [current/lenbot.service](current/lenbot.service) | Linux systemd 模板 |
| [current/start.command](current/start.command) | macOS 双击启动 |
| [current/services.compose.yaml](current/services.compose.yaml) | 向量服务（Ollama） |
| [current/start-asr.sh](current/start-asr.sh)、[current/asr.md](current/asr.md) | 本地语音转写（whisper.cpp） |
| [current/task-storage.md](current/task-storage.md) | 后台任务的存储池和容量上限 |
| [current/first-setup.example.json](current/first-setup.example.json) | 首次配置向导提交内容的示例 |

`deploy/updater/`、`deploy/package/`、`current/Dockerfile` 和 `current/host*.compose.yaml` 用于部署包和 Docker 发行，发行流程尚未定稿，暂无使用说明。

源码安装的更新步骤见[更新与备份](../website/guide/maintenance.md)。
