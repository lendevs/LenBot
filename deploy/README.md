# 部署资料

[English](README.en.md)

本目录存放运行 LenBot 的部署配方、系统服务模板和命令行运维说明。面向运营者的日常界面操作说明在[文档站](https://lendevs.github.io/LenBot/)：安装方式见[部署包](https://lendevs.github.io/LenBot/start/package)、[Docker 部署](https://lendevs.github.io/LenBot/start/docker)和[源码运行](https://lendevs.github.io/LenBot/start/source)，CI 候选构建的部署包与镜像用法见 [current/installation.md](current/installation.md)，源码安装的日常更新见[更新与备份](https://lendevs.github.io/LenBot/use/maintenance)。

## 实例目录

一个实例目录保存一个 Bot 的全部运行数据。从源码直接运行时，仓库根目录即为实例目录；使用部署包安装时，数据位于部署目录下的 `instance/`。

| 内容 | 位置 |
|---|---|
| 运行配置（含密钥） | `lenbot.config.json` |
| 聊天数据库与记忆处理库 | 配置中的 `database`，以及同名的 `.memory.sqlite3` |
| 角色包 | `personas/<角色ID>/` |
| 插件与插件业务数据 | `plugins/`、`plugins/.data/` |
| 长期记忆、提示词覆盖、资料索引与运行状态 | `state/`（具体子路径按配置） |
| 运行日志 | `logs/lenbot.jsonl` |

运行期间通过面板修改设置；手动编辑 `lenbot.config.json` 或执行停机维护命令前先停止 LenBot。

## 目录结构

| 文件或目录 | 内容 |
|---|---|
| [current/installation.md](current/installation.md) | Linux、macOS、Windows 部署包与 Docker Compose 安装、无交互初始化 |
| [current/README.md](current/README.md) | 系统服务模板、配套容器（Ollama 向量、任务镜像）与服务启动顺序 |
| [current/operations.md](current/operations.md) | 命令行维护、反向代理、本机代理 `fake-ip`、快照升级与用量记账 |
| [current/asr.md](current/asr.md)、[current/start-asr.sh](current/start-asr.sh) | macOS 本地语音转写（`whisper.cpp`）编译与接入 |
| [current/task-storage.md](current/task-storage.md) | 后台任务独立文件系统存储池（Linux `ext4` / macOS `APFS`） |
| [current/lenbot.service](current/lenbot.service)、[current/start.command](current/start.command) | Linux `systemd` 单元模板与 macOS 双击启动脚本 |
| [current/Dockerfile](current/Dockerfile)、`current/host*.compose.yaml`、[current/services.compose.yaml](current/services.compose.yaml) | 宿主容器镜像、Compose 编排与本地向量服务配置 |
| [current/first-setup.example.json](current/first-setup.example.json) | 首次配置无交互初始化的 JSON 模板 |
| `package/`、`updater/` | 跨平台部署包安装脚本与本机更新控制器源码 |

CI 产出各平台候选部署包；Release 工作流以 `publish=false` 执行时产出各架构的宿主、任务执行器与更新器候选镜像。
