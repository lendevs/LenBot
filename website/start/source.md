# 源码运行

从源码运行跟随 `master` 分支，适合参与开发或试用未发布的改动。

## 准备

- [uv](https://docs.astral.sh/uv/)：管理 Python 解释器与依赖。
- [Node.js](https://nodejs.org/) 22 或更新版本：构建网页面板前端。
- Git。

## 安装并启动

```sh
git clone https://github.com/lendevs/LenBot.git
cd LenBot
./scripts/install.sh      # 安装运行依赖并构建网页面板
uv run --no-sync len-bot  # 启动宿主
```

首次启动时终端输出一次性配置链接，按[首次配置](./first-setup)填写向导。

每次启动时，启动器核对面板前端的文件指纹，前端源码有变更时自动重新构建。

## 实例目录

从源码运行时，仓库根目录就是实例目录。`lenbot.config.json`、数据库、`state/`、`personas/` 与 `plugins/` 都保存在根目录，已列入 `.gitignore`。

## 更新

停止实例后拉取代码、同步依赖，再执行带快照的升级检查，步骤见[更新代码](../use/maintenance#从源码运行的实例)。

## 参与开发

代码、测试与数据格式的约定见[参与开发](../develop/contributing)。
