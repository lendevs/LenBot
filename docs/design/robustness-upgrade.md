# 运行稳健性升级设计

范围：聊天路径上的 SQLite 访问、数据库日志模式与快照、事件循环卡顿监测、模型提供商故障转移。
插件系统、平台适配器和面板界面不在本文范围内；本文只给面板提供只读接口。

## 1. 现状与问题

| 编号 | 现状 | 问题 |
|---|---|---|
| S1 | 业务库 `Store` 只有一个 `sqlite3` 连接，所有方法同步执行；场景会话、注意力、表达发送都在事件循环线程直接调用。 | 每次写入在 `synchronous=FULL` + 回滚日志下要做多次 fsync（日志文件、主文件、目录），慢盘上单次几十到几百毫秒。事件循环被占用期间，其他群、面板、OneBot 心跳一起等待。审计 C-2 记录面板发言上限显示会滞后约 2 秒。 |
| S2 | 回滚日志（`journal_mode=DELETE`）。 | 写事务持有排他锁时，面板另开的只读连接（`ModelBudget` 在线程里读）只能等待 `busy_timeout`；读写不能并行。 |
| S3 | 停机快照逐文件复制实例目录；文档假定数据库没有 `-wal` 旁路文件。 | 若改用 WAL，单独复制 `.db` 会丢掉尚未检查点（checkpoint）的提交。 |
| S4 | `runtime/loop_monitor.py` 只在卡顿后记录一次延迟毫秒数。 | 不知道是谁卡住了循环；面板看不到累计情况。 |
| S5 | 每个角色只绑定一个提供商/模型；`retry_delays_seconds` 只重发同一请求。 | 提供商宕机、限流或超时时，整轮对话直接失败。 |

## 2. 设计

### 2.1 数据库工作线程（S1）

参考 AstrBot 等框架常见的“异步 ORM / 线程池执行同步驱动”做法，但 LenBot 的 `Store` 有上百个同步方法、还有十几个
共享 `store.db` 的子存储（`TaskStore`、`PluginStore`、学习存储等），一次性改成 async 风险太大。采用渐进方案：

- `storage/sqlite.py` 的读写连接改为 `SerializedConnection`：底层连接 `check_same_thread=False`，外面包一层
  可重入锁。`with db:` 事务在整个事务期间持锁；事务外单条 `execute` 也持锁。这样同一连接可以同时被事件循环线程
  （尚未迁移的调用）和数据库线程使用，事务不会交错。
- 每个 `Store` 有一个单线程执行器（数据库工作线程）。`await store.call(fn, *args)` 把一次存储调用放到这个线程上执行，
  事件循环线程只等待结果。
- 聊天路径上的写入逐步改为 `await store.call(...)`：表达发送（准备、每段开始、每段结束、失败记录、发言计数）、
  回合开始/结束、工具结果、注意力批次写入、待处理消息读取等。
- **发送意图的持久化保证不变**：`start_expression_part` 提交（含 fsync）之后才调用平台发送，`finish_expression`
  提交之后才发下一段；改为 `await` 后顺序完全相同，只是等待期间事件循环可以处理别的群。
- 平台回调 `_receive` 仍同步写入收到的消息（消息顺序和“先入库再唤醒”的语义依赖它），本次不改；WAL 已经让这一步
  只需一次 fsync。

### 2.2 WAL + synchronous=FULL 与快照（S2、S3）

- 读写连接统一改为 `journal_mode=WAL`、`synchronous=FULL`。WAL 下 FULL 在每次提交时同步 WAL 文件，已提交的写入
  断电后仍在，满足发送意图和消费游标的要求；读连接不再被写事务阻塞。
- 停机快照（`upgrade backup`、测试副本）前，对快照路径下每个带 `-wal` 旁路文件的 SQLite 库执行
  `PRAGMA wal_checkpoint(TRUNCATE)`，把 WAL 内容写回主文件并清空 WAL；快照里的 `.db` 因此自身完整。`-wal`、`-shm`
  若仍存在（长度为 0）也一并复制，不影响恢复。
- 恢复：实例目录内的旧旁路文件随目录整体替换；实例目录外的数据库，`data_paths` 已经把 `-wal`/`-shm`/`-journal`
  列为“快照时不存在”的条目，恢复时会删除失败新版本留下的旁路文件，避免旧 WAL 套在恢复后的主文件上。
- 只读 `immutable=1` 打开会忽略 WAL；现有用法（任务归档、可移植历史）已经要求 `-wal` 为空，保持不变。
- 打开时 `journal_mode` 是持久属性，旧库第一次被读写连接打开时自动切换，不需要格式升级。

### 2.3 事件循环卡顿监测（S4）

- 保留异步探针（每 0.5 s 睡眠，醒来迟到即记一次卡顿）。
- 增加一个看门狗线程：探针每次醒来更新心跳；看门狗发现心跳超过阈值未更新时，立即用
  `sys._current_frames()` 抓取事件循环线程此刻的调用栈，并记录当时正在运行的 asyncio 任务名。这是“正在阻塞循环的代码”，
  而不是卡顿结束后的现场。
- 指标保存在内存：卡顿次数、累计卡顿时长、最大延迟、最近 20 次卡顿（时间、延迟、任务名、栈），
  通过 `GET /api/host/event-loop` 给面板。

### 2.4 模型提供商故障转移（S5）

参考 AstrBot 的 `fallback_chat_models`（主模型报错后按顺序尝试备用提供商），针对 LenBot 做以下不同设计：

- 配置挂在角色绑定上：`models.roles.<role>.fallbacks = [{provider, model, ...可选覆盖}]`，列表顺序即优先级，主绑定
  优先级最高。默认空列表，即与现在完全一致（不切换）。
- **只允许同一协议（`api`）的提供商互为备用**。LenBot 保存并续接原生助手消息（Anthropic 思考签名、Gemini
  thoughtSignature、Responses 加密推理），跨协议切换会让历史无法续接，所以在配置校验阶段拒绝。
- 只在“换一家可能成功”的错误上切换：传输错误、超时、HTTP 408/409/425/429/5xx，以及 401/403（单家密钥失效）。
  请求本身不合法（其他 4xx）、协议解析失败、上下文超窗等错误直接抛出，不切换，避免把问题掩盖成“换个模型”。
- 断路器：每个“提供商/模型”一个状态。连续失败达到 `failure_threshold`（默认 3）后打开，冷却 `cooldown_seconds`
  （默认 60 s）内跳过；冷却后半开，放行一次试探，成功即关闭、失败重新打开。所有候选都处于打开状态时，仍按优先级尝试
  冷却最早结束的那个，而不是直接拒绝服务。
- 记录：每次调用实际服务的提供商与模型写入 `model_call` 日志事件（`served_provider`、`served_model`、`fallback_from`），
  并保存在内存状态中；`GET /api/host/model-providers/health` 给面板显示每个候选的断路器状态、成功/失败计数、最近错误
  和最近一次服务时间。
- 这与 [CONTRIBUTING](../../CONTRIBUTING.md) 中“失败时不自动更换模型或服务”的原则冲突。本设计把它做成显式开关：
  只有运维在配置中写了 `fallbacks` 才会切换，并且每次切换都会记录。是否接受需要仓库所有者确认。

## 3. 不做的事

- 不把 `Store` 全部方法改成 async；不改平台回调的同步入库。
- 不为故障转移改写请求参数（温度、输出额度等沿用备用条目里的值），不跨协议转换历史。
- 不改面板界面；新接口的使用由面板负责人决定。

## 附录 A：面板接口（只读，均需面板登录，未登录返回 401）

### `GET /api/host/event-loop`

```json
{
  "running": true,
  "started_at": 1792252800.0,
  "interval_ms": 500,
  "threshold_ms": 500,
  "probes": 7200,
  "stalls": 3,
  "stalled_ms_total": 2140,
  "max_lag_ms": 1210,
  "recent": [
    {"at": 1792256400.5, "lag_ms": 1210, "task": "Task-42",
     "stack": "  File \".../chat/attention.py\", line 452, in receive_message\n    ..."}
  ]
}
```

`recent` 最多 20 条，新的在前。`task`、`stack` 是卡顿期间看门狗抓到的现场；卡顿短于看门狗检查间隔时为 `null`。
时间为 Unix 秒。

### `GET /api/host/model-providers/health`

```json
{
  "failure_threshold": 3,
  "cooldown_seconds": 60.0,
  "roles": {
    "mind": {
      "candidates": [
        {"priority": 0, "provider": "main", "model": "model-a", "state": "open",
         "consecutive_failures": 3, "reopens_in_seconds": 42.5, "successes": 120, "failures": 3,
         "last_error": "ModelHTTPError: Model HTTP 503: ...", "last_error_at": 1792256400.0,
         "last_success_at": 1792256300.0},
        {"priority": 1, "provider": "spare", "model": "model-b", "state": "closed",
         "consecutive_failures": 0, "reopens_in_seconds": null, "successes": 4, "failures": 0,
         "last_error": null, "last_error_at": null, "last_success_at": 1792256401.0}
      ],
      "last_served": {"provider": "spare", "model": "model-b", "priority": 1,
                      "failed_before": [{"provider": "main", "model": "model-a", "error": "..."}],
                      "at": 1792256401.0}
    }
  }
}
```

`state` 取值 `closed`（正常）、`open`（冷却中，跳过）、`half_open`（冷却结束，下一次请求试探）。
只有配置了 `fallbacks` 并已打开过模型的角色出现在 `roles` 中。

## 附录 B：配置

见 [developer/model-fallback.md](../../developer/model-fallback.md)。
