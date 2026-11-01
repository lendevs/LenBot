# 发布到插件目录

LenBot 随附的插件目录只收录官方插件。其他插件收录在社区插件目录 [lenbot-plugin-index](https://github.com/lendevs/lenbot-plugin-index) 中，用户在面板**插件 → 发现插件 → 目录来源**填入社区目录的地址后即可浏览和安装：

```text
https://raw.githubusercontent.com/lendevs/lenbot-plugin-index/main/catalog.json
```

## 收录条件

- 插件是一个独立的公开 Git 仓库，仓库根目录有 `plugin.toml`、`__init__.py`、README 和许可证文件。
- 条目的 `ref` 是完整的 40 位提交号。更新插件时提交新的条目，把 `ref` 和 `version` 改到新的提交。
- 条目的 `name`、`version`、`interface` 与这个提交中的 `plugin.toml` 一致；写了 `permissions` 和 `requires_lenbot` 时也要一致。
- 插件名在目录中唯一，不与官方插件重名。

## 提交条目

在 `lenbot-plugin-index` 仓库的 `catalog.json` 中加一项，提交 Pull Request。格式与随附目录相同：

```json
{
  "name": "example_feed",
  "title": "示例订阅",
  "description": "按指定时刻发送订阅更新。",
  "authors": ["插件维护者"],
  "license": "GPL-3.0-only",
  "version": "1.0.0",
  "interface": 1,
  "requires_lenbot": ">=0.2,<1",
  "category": "自动播报",
  "capabilities": ["无模型", "RSS"],
  "usage": ["填写订阅地址并保存。", "选择启用的群。"],
  "install": "git",
  "repository": "https://github.com/author/example_feed.git",
  "homepage": "https://github.com/author/example_feed",
  "ref": "0123456789abcdef0123456789abcdef01234567",
  "permissions": ["send", "schedule"]
}
```

| 字段 | 内容 |
|---|---|
| `title`、`description` | 面板中显示的名称和介绍 |
| `category`、`capabilities` | 分类和能力标签，用于搜索和筛选 |
| `usage` | 安装后的使用步骤，每项一句 |
| `install` | 固定为 `git` |
| `repository`、`homepage` | 仓库地址和主页 |
| `permissions` | 插件实际使用的宿主权限，与清单一致；安装前展示给用户 |

Pull Request 的 CI 运行宿主仓库中的 `scripts/check_plugin_catalog.py`：逐项取出 `ref` 指向的提交，核对清单和文件，不导入、不运行插件代码。本机可以先自行检查：

```sh
uv venv --python 3.13
uv pip install ../LenBot
uv run --no-project python ../LenBot/scripts/check_plugin_catalog.py catalog.json --only example_feed
```

## 自建目录

目录也可以放在任何 HTTP(S) 地址上，格式与随附目录相同：顶层 `{"version": 1, "entries": [...]}`。用户在**目录来源**填入地址后点刷新读取。私人目录和需要凭据的仓库都保存在用户自己的配置中。
