# 日志与排查

Bot 没有回复或者回复内容不对时，以及插件报错时，请先查看日志。

## 在面板中查看

每一轮回复的经过在**群聊 → 现场**里看。展开 Bot 的回合卡片，可以看到 Bot 当时召回的记忆、每一步调用的模型和想法、使用的工具和结果，以及最终发出的内容。回合结束后，卡片底部有两个按钮。

- **这一轮的运行日志**：打开系统日志，只显示这一轮的记录。
- **下载诊断包**：这一轮的详情、模型和工具调用，以及同一轮的运行日志，打包成 ZIP。

**系统 → 日志**有两个页签。

- **系统日志**：LenBot 各个部分写下的记录。可以按级别（全部、警告以上、只看错误）、群、来源、插件和任务编号筛选，也可以按事件类型筛选或在结果里搜索；打开**实时跟随**后新记录自动出现。点记录上的轮次编号可以只看这一轮，上方同时显示这一轮的经过。筛选出的记录可以导出。下方的**日志文件**按天列出，可以直接下载。
- **运行健康**：主循环有没有卡顿、最近的卡顿和进程暂停记录。

后台任务的诊断包在**群聊 → 任务**中打开任务，点**下载诊断包（不含文件）**。

回复诊断包包含消息、模型请求和回复正文，任务诊断包包含任务文字；导出时会遮盖配置密钥和长数字，但不会删除对话内容。分享前请检查其中的文字。

## 日志文件

运行日志写在实例目录的 `logs/lenbot.jsonl`，每天生成一个新文件，默认保留 14 天。日志目录和保留天数可以在**系统 → 设置 → 高级 → 日志**中修改。

每行是一条 JSON 记录，包含时间、级别和事件名，还带有用来关联同一件事的编号。

| 编号 | 关联的范围 |
|---|---|
| `turn_id` | 一轮回复，包括收到消息、调用模型和工具、插件处理、发出消息 |
| `task_id` | 一个后台任务从创建到结束 |
| `scene` | 同一个群或私聊 |
| `plugin` | 同一个插件 |

出错的记录包含完整的错误类型和错误信息，以及调用栈。配置中的密钥和插件的密钥字段不会写入日志。下载日志文件时，5 位以上的数字也会被遮盖，便于发给别人查看。

## 其他日志

| 安装方式 | 位置 |
|---|---|
| 部署包 | 更新器的记录在安装目录的 `updates/updater.jsonl` 和 `updates/updater.log`。macOS 服务自身的输出在 `logs/service.stdout.log` 和 `logs/service.stderr.log`。Linux 服务用 `journalctl --user -u lenbot.service` 查看 |
| Docker | 终端输出用 `docker compose -p lenbot logs lenbot` 查看，更新器用 `docker compose -p lenbot logs lenbot-updater` |
| 从源码运行 | 终端中每条记录显示为一行简短摘要，完整内容以日志文件为准 |

## 检查实例

数据格式或插件出现问题时，在实例目录中执行检查命令。

| 安装方式 | 命令 |
|---|---|
| 部署包 | 在 `instance` 目录执行 `../releases/<当前版本>/.venv/bin/python -m len_bot.next.maintenance.doctor`（Windows 上是 `..\releases\<当前版本>\.venv\Scripts\python.exe`） |
| Docker | `docker compose -p lenbot exec -w /srv/lenbot lenbot /opt/lenbot/.venv/bin/python -m len_bot.next.maintenance.doctor` |
| 从源码运行 | `uv run --no-sync python -m len_bot.next.maintenance.doctor` |

这条命令逐项检查配置和数据库，也检查插件，包括插件的数据版本。每一项输出一行，全部为 `ok` 或 `disabled` 时说明没有问题。检查只读取数据，Bot 运行期间也可以执行。

## 报告问题

在 [GitHub Issues](https://github.com/lendevs/LenBot/issues) 提问时，请附上以下内容。

- LenBot 的版本和安装方式。
- 出问题的那一轮回复或那个任务的诊断包。也可以从 `lenbot.jsonl` 中按 `turn_id` 或 `task_id` 摘出日志。
- `doctor` 的输出。

发送之前请再检查一遍，确认其中没有不想公开的聊天内容。
