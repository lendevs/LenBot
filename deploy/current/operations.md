# 命令行维护与主机运维

面板的各页面操作、角色管理、插件安装、长期记忆与日志查看说明统一见文档站[管理面板](https://lendevs.github.io/LenBot/use/panel)。本文记录宿主的进程锁与启动器机制、网络代理配置、停机维护命令以及数据格式和记账规则。

所有维护命令均在实例根目录执行：源码安装使用 `uv run --no-sync python -m ...`，部署包使用 `releases/<版本>/python` 中的解释器（Linux 为 `bin/python3`，Windows 为 `python.exe`），Docker 镜像使用 `/opt/lenbot/.venv/bin/python`（下文统一简写为 `python -m ...`）。除标明只读的命令外，执行维护命令或手动修改 `lenbot.config.json` 前均需先停止 LenBot。

## 进程、重启与实例锁

- `len-bot` 启动器管理单个 `len_bot.next.host` 子进程。面板确认重启后，宿主停止接收新消息与新工作，等当前回合结束并以退出码 `75` 退出（后台任务中断但保留工作区与会话供后续续接，试聊停止），启动器随即拉起新进程。直接运行 `python -m len_bot.next.host` 不带进程内重启能力。
- 宿主、面板与所有维护写命令共用实例根目录下的 `.lenbot-instance.lock`。锁被占用时新命令直接退出；终端中按 `Ctrl-Z` 挂起的进程仍持有该锁，需 `fg` 恢复后按 `Ctrl-C` 正常结束。
- 配置中所有账号均带平台前缀（如 `onebot:70001`），场景写成 `onebot:group:80001` 或 `onebot:private:70001`。真实发送开关保存在 `state/send-hold.json`，文件无法读取时按开启模拟发送处理。

## 群内设置管理

当角色工具许可同时包含 `host_manage` 和 `tool_search`（重启生效）时，全局主人与全局管理员可在群聊中直接要求 Bot 修改运行设置，涵盖各群聊天开关、参与方式与学习、提醒与任务参数、角色绑定、网页与记忆参数、模型生成参数与额度、数据保留，以及已安装插件的启停、普通参数和启用群。

- 宿主按模型指明的真实请求消息校验发送者身份，群主、群管理员与单群管理员无权调用 `host_manage`。
- 密钥、身份授权、平台连接方式及需停机迁移的字段不可从群内修改；默认仅保存并即时应用热配置，明确要求时才触发重启。
- 跨群切换聊天开关最多等待目标群执行锁 1 秒，超时报告失败；关闭当前群自身时在当前回合结束后生效。

## 网络与反向代理

### 面板登录限制与 `trusted_proxies`

面板默认监听 `127.0.0.1:8088`，密码以 `pbkdf2_sha256$600000$盐$哈希`（PBKDF2-HMAC-SHA256，600,000 次迭代）存储。登录按来源 IP 计数：15 分钟内失败或正在校验的请求达到 5 次后，该 IP 返回 HTTP `429`，直至窗口结束或此前某次校验成功清零。

通过 HTTPS 反向代理对外提供面板时，将代理地址或网段写入根配置的 `panel.trusted_proxies`（默认 `["127.0.0.1"]`）并重启。来自可信代理的请求按 `X-Forwarded-For` 和 `X-Forwarded-Proto` 解析客户端地址与协议，用于登录限速、同源写入校验和 WebSocket 连接；反向代理需保留原始 `Host` 并覆盖传入的转发头。Docker 部署配方仅在宿主机 `127.0.0.1` 发布端口，容器内自动将该 Docker 网络网关与 `127.0.0.1` 一并视为可信代理。

### 本机代理的 `fake-ip` 模式

本机运行 Clash、Surge 等开启 `fake-ip` 模式的代理工具时，域名解析会返回 `198.18.0.0/15` 等保留地址，触发宿主外网访问的私网与保留地址拦截（报错 `resolved to 198.18.… (私有或保留地址)`）。此时在 `lenbot.config.json` 中声明代理使用的 `fake-ip` 网段和一个支持 DNS JSON 查询的公网地址：

```json
"network": {
  "fake_ip_networks": ["198.18.0.0/15"],
  "public_dns_url": "https://dns.google/resolve"
}
```

域名解析结果落入 `fake_ip_networks` 时，宿主向 `public_dns_url`（接受 `name`、`type` 参数并返回 `Status` 与 `Answer`）查询真实 `A` / `AAAA` 公网地址并固定连接。直接请求保留 IP 或解析结果为私网地址的请求仍被拒绝；`fake_ip_networks` 不可包含 `10.0.0.0/8`、`192.168.0.0/16` 等真实局域网段或公网网段。

## 维护命令

| 命令 | 是否需停机 | 作用 |
|---|---|---|
| `python -m len_bot.next.maintenance.doctor` | 否（只读打开数据库） | 检查根配置、业务数据库、记忆处理库、本地记忆索引及各插件的数据版本与键值库格式，每项输出一行 JSON，任一失败退出码为 `1` |
| `python -m len_bot.next.maintenance.upgrade run --snapshot <新目录>` | 是 | 持有实例锁，将实例目录与外部引用目录完整备份至 `<新目录>`，执行数据升级、恢复插件依赖并运行 `doctor`；任一步失败自动从快照还原 |
| `python -m len_bot.next.maintenance.upgrade restore --snapshot <快照目录>` | 是 | 从指定快照目录还原实例数据，配合切回旧版程序使用 |
| `python -m len_bot.next.maintenance.memory_reindex` | 是 | 重建本地长期记忆的全文与向量索引，保留正文和修改历史，清空目录摘要以便后续按新正文重生成 |
| `python -m len_bot.next.maintenance.reindex_expressions` | 是 | 更换学习向量绑定后重建群聊说法向量索引 |
| `python -m len_bot.next.maintenance.plugin_dependencies` | 是 | 重建 Python 环境后，合并并一次性安装所有已安装插件声明的依赖 |
| `python -m len_bot.next.maintenance.apply_plugins` | 是 | 直接运行 `len_bot.next.host`（未经过启动器）时，应用面板中已选定待重启生效的插件候选版本 |
| `python -m len_bot.next.maintenance.archive_tasks` | 是 | 按 `task_archive` 配置离线导出已结束任务的记录与原生文件归档 |
| `python -m len_bot.next.maintenance.test_copy <原目录> <新目录> --panel-port 8089` | 是 | 复制实例配置与内部数据文件生成隔离测试副本，自动改为 `simulated` 发送、断开 OneBot 并重写指向原实例内部的绝对路径 |

### 记忆维护

在面板中执行记忆文件的`仅删除文件`会保留修改历史；执行`彻底忘记`会清除正文、索引、历史版本与目录摘要，并可勾选原消息不再参与后续抽取。手动在磁盘修改记忆 Markdown 文件，或更换 `memory.local.embedding` 的地址、模型、维数并重启后，可在面板记忆页一键重建，或停机执行上表中的 `memory_reindex`（表达学习向量变更对应 `reindex_expressions`）。

### 升级与备份

面板启动 60 秒后及之后每 24 小时检查一次新版本（源码运行查询 GitHub Releases，托管部署查询本机更新控制器；设置 `panel.update_check: false` 可关闭）。

- 源码安装按上表 `upgrade run --snapshot <新目录>` 升级，快照路径须位于实例目录与外部任务目录之外。
- 部署包与 Docker 更新器在升级前将快照写入部署目录的 `backups/`（以 UTC 时间命名），面板**系统 → 版本与更新**可查看或清理旧快照。上次更新失败且尚未恢复时，对应恢复快照锁定不可删除；快照失败会清理半成品并重新拉起旧版本。
- 不经更新器、直接 `docker run` 的宿主容器比较 `.runtime/release.json` 记录的版本与镜像版本：镜像较新时先把实例快照到数据卷的 `/data/backups/`，再执行与 `upgrade run` 相同的迁移；数据卷由更新的版本用过时拒绝启动。

## 数据格式版本

第一个候选发布版（RC）之前，以下 6 项持久化格式与接口编号均固定为 `1`：`lenbot.config.json` 的 `config_version`、业务数据库 `storage/store.py`、记忆处理库 `memory/jobs.py`、本地记忆索引 `memory/local.py`、插件键值库 `plugins/kv.py` 以及插件公开接口 `plugin/manifest.py`。资料库派生索引 `state/reference/index.sqlite3` 在结构版本变化时自动重建。格式编号不匹配时宿主启动直接报错；从第一个 RC 起，跨版本结构变更统一由 `upgrade` 处理。

## 用量记账与后台任务资源

每次模型调用结束时，宿主在业务库 `usage` 表写入一行（开始时间、场景、用途、服务商连接、模型名，以及服务商报告的输入、输出和缓存 token），数据保留期清理旧回合与调用正文时保留 `usage` 表。每日 token 上限统计当天 `usage` 表中除语音转写（`asr`）和向量（`embedding`）外的全部输入加输出 token，失败但已由服务商报告用量的请求同样计入。

后台任务的资源与交付约束：

- `worker.max_calls` 按单次执行或单次续接统计；`max_tokens` 按整个任务跨续接累计的输入加输出 token 统计。HTTP `4xx` 拒绝且无 `usage` 的请求可在修复后继续续接；已被接受后中断或 `5xx` 导致用量未知时，若配置了任务 token 上限则暂停续接。
- `max_daily_tasks` 仅统计新建任务数，续接原任务不重复扣减。
- 单个交付文件默认上限 25 MiB，单任务累计登记交付默认上限 500 MiB（`worker.max_delivery_bytes`，续接继续累计）。任务镜像内置 `lenbot-render`，可将 HTML 渲染为 PDF 或 PNG 截图。
- 运行日志统一写入 `logs/lenbot.jsonl`（按天轮转，默认保留 14 天），自动遮盖配置与插件密钥；通过面板导出日志文件或诊断包时，5 位及以上的连续数字一并遮盖。

## 无 QQ 连接运行

设置 `onebot: null` 且 `delivery: "simulated"` 时宿主不连接 OneBot：

- 保留 `panel` 配置时，面板、插件、模型与后台任务照常运行，可在面板内做隔离试聊。
- 同时设置 `panel: null` 时，`len-bot` 从标准输入逐行读取 OneBot 原始事件 JSON，读至输入末尾并处理完已入库消息后自动退出。公开回放套件见 [examples/replay/](../../examples/replay/README.md)。
