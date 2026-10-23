# 静态插件目录

插件目录帮助用户了解插件的用途和安装位置。插件接口、配置和运行能力由安装后的 `plugin.toml` 决定。默认目录随宿主一起打包，内容见 [plugin_catalog.json](../src/len_bot/next/plugins/plugin_catalog.json)。

## 使用

在「插件 → 发现插件」中可以搜索插件的名称、用途、作者和能力，也可以按分类筛选。详情中包含用法、许可证、接口要求和源码位置。准备候选版本后，转到配置、应用和选择启用的群。

在「目录来源」中填写 HTTP(S) JSON 地址，保存并读取。留空时恢复为随附的目录。对应的根配置如下。

```json
"plugin_catalog": {"url": "https://example.com/lenbot-plugins.json"}
```

远程目录在点击刷新时读取。页面显示目录的来源和成功读取的时间。读取失败时显示原始错误，已经读取的同一来源的内容保留原来的时间。更换 URL 后，需要等待读取新的目录。目录快照只保存在当前进程中。

### 市场接口

面板之外的客户端也可以通过管理接口使用目录，接口都需要登录。

- `GET /api/host/plugin-market?query=&category=`：按关键词（名称、标题、描述、分类、能力、作者，多个词需同时出现）和分类筛选，返回全部分类、目录总数和条目。每个条目附带 `installed`、`installed_version`、`update_available`（按版本号比较）、`compatible` 和 `incompatible_reason`（接口版本或宿主版本范围不符）。
- `GET /api/host/plugin-market/{name}`：单个条目，格式同上。
- `POST /api/host/plugin-market/{name}/install`：用条目里的仓库和 ref 准备候选版本，之后的配置和应用与手动安装相同。已经安装的返回 409，请改用更新；不兼容的返回 422。仓库 `plugin.toml` 中的插件名与条目的 `name` 不一致时返回 422，不准备候选版本。更新已安装的插件时同样要求清单名称不变。

## 索引格式

顶层的 `version` 是索引格式的版本，目前为 1。每一项中的 `version` 是用于展示的插件版本。下面示例中的仓库和主页都是占位地址。

```json
{
  "version": 1,
  "entries": [{
    "name": "example_feed",
    "title": "示例订阅",
    "description": "按指定时刻发送订阅更新。",
    "authors": ["插件维护者"],
    "license": "MIT",
    "version": "1.0.0",
    "interface": 1,
    "category": "自动播报",
    "capabilities": ["无模型", "RSS"],
    "usage": ["填写订阅地址并保存。", "选择启用场景。"],
    "install": "git",
    "repository": "https://example.com/author/example_feed.git",
    "homepage": "https://example.com/author/example_feed",
    "ref": "v1.0.0",
    "permissions": ["send", "schedule"]
  }]
}
```

- 同一个目录中的名称必须唯一。
- `capabilities` 和 `usage` 可以省略。`homepage`、`ref` 和 `requires_lenbot` 可以为空。
- `requires_lenbot` 是展示用的宿主版本范围，兼容性检查使用安装清单。
- Git 条目需要一个独立的插件仓库，`ref` 支持标签、分支或提交。
- 所有条目都使用 `install: "git"`，业务插件独立安装和更新。
- `permissions` 写插件实际使用的宿主权限，名称与 `plugin.toml` 的 `permissions` 相同，可以省略。它在安装前展示，装上后的能力由插件自己的清单决定。从目录安装时，仓库清单也声明了权限的，两边必须一致，否则不准备候选版本。

## 版本与发布

- 已安装版本和候选版本分别取自各自的清单，运行版本取自实际运行的插件。Git 提交和选定的 ref 单独显示。
- 指定了 ref 的安装使用 detached HEAD，并在实例的 `plugins/.installations/<name>.json` 中保存选择的 ref 和 commit。明确更新时重新获取。
- 没有指定 ref 的安装跟随默认分支，更新时重新获取并准备候选版本。需要切换时，在更新框中填写新的标签、分支或提交。
- 第三方发布者先提供独立的 Git 仓库、清单和使用说明，再把条目加入自己选择的目录。私人站点和凭据保存在用户自己的配置中。

目录是插件的分发索引。手动填写仓库地址的安装和从目录安装使用同一个管理器。

## 官方插件发行准备

群聊总结、GSUID、A-SOUL、哔哩哔哩和[插件模板](https://github.com/lendevs/lenbot-plugin-template)都已经在 lendevs 组织下公开。随附的目录收录四个业务插件，模板作为开发的起点。

所有独立插件和模板都使用接口 1，`requires_lenbot` 为 `>=0.2,<1`。当前源码需要包含插件接口扩展的宿主开发提交，最低基线见各插件的 CHANGELOG。

每个插件的 `CHANGELOG.md` 记录版本、最低接口能力、参数变化和数据迁移事项，标题格式为 `# X.Y.Z`。

插件仓库的 CI 和发行流程都调用宿主提供的可复用工作流（`.github/workflows/plugin-ci.yml` 和 `plugin-release.yml`）。打包统一使用宿主的 `scripts/package_plugin.py`，从 Git 中的运行文件生成 ZIP。ZIP 包含运行文件、prompts、skills、assets 和许可文件。

只有维护者明确推送 `v<清单版本>` 标签后才会发行。标签必须与 `plugin.toml` 中的版本一致，发行说明取自 CHANGELOG 中对应版本的一节。

随附目录中的条目来自各插件仓库的 `catalog-entry.json`，用同步脚本写入并固定到提交。

```sh
uv run --no-sync python scripts/sync_plugin_catalog.py ../lenbot-plugin-asoul ../lenbot-plugin-bilibili@v1.1.0
```

参数是插件仓库在本机的检出目录，`@ref` 可选，默认为当前的 `HEAD`。脚本会核对条目与该提交中 `plugin.toml` 的名称、版本和接口是否一致，并要求这个提交已经推送到远端分支。`plugin.toml` 声明了 `permissions` 时，脚本把它写进条目；`catalog-entry.json` 写了不同的权限时拒绝同步。

目录 ref 必须是已经推送、可以取得的提交，展示版本与源码一起用同步脚本更新。

宿主 CI 中的 `official-plugins` 作业按目录中固定的提交检出每个 lendevs 插件，用当前的宿主运行这些插件的测试和打包检查。因此，如果宿主的改动导致目录中的插件无法运行，CI 会直接失败。

目前还没有发行，目录固定在各插件已核对的开发提交。更新和回退时，按插件的 CHANGELOG 选择与宿主匹配的版本；插件数据在更新、回退和卸载时都会保留。
