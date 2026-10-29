# 参与开发

只编写角色包或独立插件时无需阅读本页，请直接前往[写角色包](./personas)或[写插件](./plugins)。本页面向修改 LenBot 宿主核心、网页面板或文档站的贡献者。

## 搭建本地开发环境

需要安装 [uv](https://docs.astral.sh/uv/) 以及 Node.js 22 或更高版本。

```sh
git clone https://github.com/lendevs/LenBot.git
cd LenBot
./scripts/install.sh       # 同步运行依赖并构建网页面板
uv sync --locked           # 安装 pytest、ruff 等开发依赖组
uv run --no-sync pytest -q
```

`./scripts/install.sh` 仅安装运行期依赖，运行测试与静态检查前需执行一次 `uv sync --locked`。

日常开发常用校验命令：

- **Python 代码与测试**：执行 `uv run --no-sync pytest -q` 与 `uv run --no-sync ruff check src/len_bot scripts deploy/updater deploy/package tests`。
- **管理面板前端**：修改 `src/len_bot/web/frontend/` 后，在该目录执行 `npm run typecheck`、`npm run lint` 和 `npm run build`（产物 `src/len_bot/web/static/dist/` 不提交到 Git）。
- **文档站**：修改 `website/` 后，执行 `npm --prefix website run dev` 在本地预览，提交前执行 `npm --prefix website run build` 检查死链。

## 仓库核心文档索引

完整的工程约定与模块细节维护在仓库内，避免与文档站重复：

- [CONTRIBUTING.md](https://github.com/lendevs/LenBot/blob/master/CONTRIBUTING.md)：源码目录结构、错误处理与配置原则、测试边界、持久化数据格式编号、打包与提交规范。
- [developer/README.md](https://github.com/lendevs/LenBot/blob/master/developer/README.md)：内部架构总览、唤醒与合批机制、上下文与缓存分段、模型协议适配、面板前端规范及插件接口 v1 完整契约。
- [问题反馈](https://github.com/lendevs/LenBot/issues)：提交缺陷报告或功能讨论；涉及安全漏洞请按 [SECURITY.md](https://github.com/lendevs/LenBot/blob/master/SECURITY.md) 私下报告。
