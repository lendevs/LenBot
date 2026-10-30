# 参与开发

[English](CONTRIBUTING.en.md)

只编写角色包或插件时无需阅读本文，可从[插件接口 v1](developer/plugins-v1.md)、[插件模板](https://github.com/lendevs/lenbot-plugin-template)或文档站的扩展开发章节开始。

## 本机开发

需要 [uv](https://docs.astral.sh/uv/) 和 Node.js 22。

```sh
./scripts/install.sh       # uv sync，并构建网页面板
uv sync --locked           # 安装包含测试工具的 dev 依赖组
uv run --no-sync len-bot   # 启动；缺少配置时打开首次配置向导
```

仓库根目录即本机运行实例目录。`lenbot.config.json`、数据库、`state/` 和 `personas/` 都存放在根目录，并由 `.gitignore` 排除。本机开发与日常运行共用同一份检出目录，通过 `uv` 直接启动。

修改前端代码后，在 `src/len_bot/web/frontend` 执行 `npm run typecheck`、`npm run lint` 和 `npm run build`。构建产物 `src/len_bot/web/static/dist/` 不提交到 Git。开发阶段可使用 `npm run dev` 调试，前端结构约定见[面板前端](developer/panel.md)。

从 Git 检出运行 `len-bot` 时，启动器会核对前端源码指纹；构建产物缺失或源码变更时先执行 `npm ci` 和 `npm run build`，未变更时直接启动。

### 在隔离副本上测试

需要在不改动在用数据的前提下验证代码时，先停止原实例，再导出测试副本：

```sh
uv run --no-sync python -m len_bot.next.maintenance.test_copy . /tmp/lenbot-test --panel-port 8089
cd /tmp/lenbot-test && uv run --project /path/to/LenBot --no-sync len-bot
```

命令会复制 `lenbot.config.json` 及其引用的数据库、记忆、角色、资料与任务目录。副本自动设为模拟发送、断开 OneBot，并监听指定的面板端口；指向原实例目录内部的绝对路径会重写为副本路径。模型、插件和后台任务服务在副本中按原配置运行。

## 源码结构

运行核心位于 `src/len_bot/next/`，入口模块为 `len_bot.next.host`，`len-bot` 命令通过 `launcher.py` 启动宿主。模块协作关系见[架构](developer/architecture.md)。

| 位置（相对 `src/len_bot/next/`） | 职责 |
|---|---|
| `host.py`、`launcher.py`、`instance_lock.py` | 宿主装配、启动器、单实例锁 |
| `config.py`、`configuration/` | 根配置与各子域配置校验 |
| `runtime/` | 平台连接、场景调度、实时设置应用、日志与数据保留 |
| `platform/` | 统一身份与消息模型、OneBot v11 适配器 |
| `chat/` | 场景会话、唤醒与合批、上下文拼装、发言投递、工具分派、提醒 |
| `models/` | 模型协议请求、并发槽位、额度与用量记录 |
| `persona/`、`learning/` | 角色包加载，以及群内说法、黑话、表情和回复效果学习 |
| `memory/` | 本地 Markdown 记忆存储、混合索引、自动召回与后台整理 |
| `reference/` | 角色设定资料与本群资料文件的提取、全文索引和按需向量检索 |
| `work/`、`browser/` | 后台任务（Pi 容器）与公共浏览器协作 |
| `storage/` | SQLite 表结构、连接配置与严格 JSON 编解码 |
| `plugins/` | 插件发现、清单校验、同进程与独立进程运行、候选安装与回退 |
| `tools/`、`media/` | 网页搜索与读取、技能目录、MCP 客户端、图片与语音处理 |
| `panel/` | 网页面板后端路由与首次配置向导 |
| `maintenance/` | 停机或只读维护命令：健康检查、版本升级、索引重建、插件依赖、存储池、测试副本 |
| `trials/` | 面板内的隔离对话测试与角色草稿试聊 |

仓库其他目录：

| 位置 | 内容 |
|---|---|
| `src/len_bot/plugin.py`、`plugin_testing.py`、`text_cards.py`、`image_assets.py` | 面向插件公开的稳定接口，插件仅从这些模块导入 |
| `src/len_bot/prompts/` | 框架提示词模板 |
| `src/len_bot/default_personas/` | 首次配置使用的默认角色模板（小然） |
| `src/len_bot/builtin_skills/` | 内置后台任务技能 |
| `src/len_bot/web/frontend/` | Vue 3 管理面板前端源码 |
| `src/len_bot/eval/` | 表达与社交回放评测 |
| `developer/` | 核心设计与插件接口 v1 参考文档 |
| `website/` | VitePress 文档站源码，用 `npm --prefix website run dev` 在本地预览 |
| `deploy/` | 部署包脚本、容器配方与共用更新控制器 `deploy/updater/` |
| `docker/next-worker/` | 后台任务容器镜像与浏览器扩展 |
| `scripts/` | 安装、打包与评测辅助脚本 |
| `examples/` | 示例角色、示例记忆插件与公开回放用例 |
| `tests/` | 自动化测试 |

维护命令统一通过 `uv run --no-sync python -m len_bot.next.maintenance.<模块>` 调用。包内代码直接从具体实现模块导入，`__init__.py` 不做汇总重导出。

## 编写代码

- 只解决真实存在的问题。不吞掉异常返回默认值，不猜测未声明字段，不为类型系统已排除的分支增加冗余判断。模型或外部服务报错时，不自动切换模型、服务或篡改请求参数重试。
- 外部输入（平台事件、模型与服务响应、配置文件）在边界处一次性解析校验。解析失败时直接抛出携带原始片段的异常。
- 异常仅在一轮对话、一次工具或插件调用、一个后台任务的执行边界捕获，记录错误原文后结束该执行单元。工具报错原文直接交还给聊天模型。
- 请求归属、代词指代和回复对象等语境判断交给聊天模型处理；宿主只维护真实平台身份和执行状态。新增数据表、持久状态或抽象层时，在 PR 中说明对应的具体问题。
- 日志使用模块级 `logging.getLogger(__name__)`，结构化事件调用 `runtime/logs.py` 的 `log_event(logger, '事件名', **字段)`，不使用 `print`。异常对象传入 `error=`，数据库错误列记录单行 `Type: message`（`error_text`）。新增后台流程或外部回调入口时，用 `log_context` 绑定关联 ID。
- 运行参数统一来自实例根目录的 `lenbot.config.json`，运行期间由面板写回。不引入环境变量、`.env`、命令行开关或数据库配置覆盖层。

## 测试

```sh
uv run --no-sync pytest -q
uv run --no-sync python -m compileall -q src/len_bot
uv run --no-sync ruff check src/len_bot scripts deploy/updater deploy/package tests
```

单元测试聚焦三类边界，样本采用脱敏后的真实协议数据：

- 外部协议解析：OneBot v11、Pi RPC、各模型协议与检索服务响应
- 身份与工具权限校验
- 配置文件与插件清单校验

测试不模拟内部调用序列，不测私有辅助函数，不对提示词文本做全文快照。

调整提示词或默认角色表达时，使用[表达与社交回放](examples/replay/README.md)在改动前后做对照评测。遇到失真回复时先提炼为回放用例再修改提示词，避免在提示词中堆叠零散禁令。虚构通用用例归入 `examples/replay/`，涉及真实群聊记录的用例仅保留在本机。

## 数据格式

在首个候选发布版（RC）之前，以下六个格式与接口编号固定为 `1`。在此期间调整表结构或配置字段时直接修改建表语句与配置模型，不编写迁移步骤，本机开发实例按需手动调整或重建。

| 编号项 | 当前值 | 定义位置 |
|---|---|---|
| 插件接口版本 | `1` | `src/len_bot/plugin.py` 的 `INTERFACE` |
| 根配置格式 | `1` | `src/len_bot/next/config.py` 的 `CONFIG_VERSION` |
| 业务数据库 | `1` | `src/len_bot/next/storage/store.py` 的 `FORMAT_VERSION` |
| 记忆处理库 | `1` | `src/len_bot/next/memory/jobs.py` 的 `FORMAT_VERSION` |
| 本地记忆索引 | `1` | `src/len_bot/next/memory/local.py` 的 `FORMAT_VERSION` |
| 插件键值存储 | `1` | `src/len_bot/next/plugins/kv.py` 的 `FORMAT_VERSION` |

上述四个 SQLite 数据库通过 `PRAGMA application_id` 标识文件类型，通过 `PRAGMA user_version` 记录格式编号；宿主只打开这两个值与当前代码一致的数据库文件。资料检索索引库（`reference/library.py`）仅保存可由源文档重建的派生数据，表结构变化时自动重建。

写入数据库的 JSON 字段按对应 dataclass 严格解码（`ChatMessage`、`Sender`、`Segment`、`Task`、`TaskFile`、`Schedule` 以及模型调用和记忆整理记录），字段结构同样属于持久化格式契约。

自首个 RC 起，任何持久化格式变更都递增对应编号，并在 `maintenance/upgrade.py` 的 `apply` 阶段补齐从上一版本的迁移实现；更新控制器在执行迁移前自动建立完整实例快照。

## 打包与持续集成

```sh
uv run --no-sync python scripts/build_release.py /tmp/lenbot-release
```

打包脚本在独立临时目录中构建前端面板，产出源码包、wheel、Linux／macOS／Windows 部署包及发行清单。

持续集成工作流（[ci.yml](.github/workflows/ci.yml) 与 [check.yml](.github/workflows/check.yml)）在 Python 3.13（`pyproject.toml` 最低要求版本）与 Python 3.14 上运行编译、静态检查与测试，使用 `actionlint` 校验全部工作流文件，并验证前端构建与发行打包。单元测试在 Linux 与 Windows 上执行，macOS 与各平台部署包由安装冒烟测试（[install-smoke.yml](.github/workflows/install-smoke.yml)）覆盖。

## 提交规范

- 提交缺陷报告与代码变更分别使用[缺陷模板](.github/ISSUE_TEMPLATE/bug.md)和 [PR 模板](.github/PULL_REQUEST_TEMPLATE.md)。
- 提交前执行 `git diff --check`。不提交本机配置文件、数据库、密钥凭据、个人角色包或前端构建产物。
- 提交说明写清行为变化、已核对范围与未确认事项。
- 改动用户可见行为或开发接口时，同步更新 `README.md`、`website/`、`developer/` 或 `deploy/` 中的对应文档。中文文档为主版本；设有英文镜像的文件（`README.en.md`、`CONTRIBUTING.en.md`、`deploy/README.en.md`、`developer/plugins-v1.en.md`）同步修改。修改 `website/` 后执行 `npm --prefix website run build` 校验构建与内部链接。
- 提交与文档的作者仅限人类贡献者，不加入工具或模型的署名标记与机器邮箱。

## 许可证

提交至本仓库的代码按 [AGPL-3.0-only](LICENSE) 授权；独立插件模板按 GPL-3.0-only 授权。第三方代码与素材的来源及许可证记录在 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) 中，引入新第三方材料时一并更新。
