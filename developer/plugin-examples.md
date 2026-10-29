# 独立插件与示例

业务插件独立发布和更新，不随宿主打包。面板中的安装、候选应用和群启用操作见文档站[插件](https://lendevs.github.io/LenBot/guide/plugins)，插件发现目录格式见[静态插件目录](plugin-catalog.md)。

| 插件 | 群内入口与工具 | 依赖条件 | 仓库 |
|---|---|---|---|
| `group_digest` | `/群日报 [小时数]`、`/群总结 [要求]`、`/群工作 要求`，以及两项聊天工具 | 总结使用已配置的模型绑定；群工作需要任务执行器且请求人具备任务权限 | [lenbot-plugin-group-digest](https://github.com/lendevs/lenbot-plugin-group-digest) |
| `gscore_adapter` | `/gs 命令`、`/gs连接`，以及一项状态查询工具 | 已运行的早柚核心（GSUID Core）；工具遵循角色许可 | [lenbot-plugin-gscore-adapter](https://github.com/lendevs/lenbot-plugin-gscore-adapter) |
| `asoul` | `/日程`、`/日程高亮`，以及日程、动态、二创查询与发卡片四项工具 | 配置日历与动态站地址；工具遵循角色许可 | [lenbot-plugin-asoul](https://github.com/lendevs/lenbot-plugin-asoul) |
| `bilibili` | 视频查询、搜索、直播与关注监测、账号读取、账号写入五项工具 | 公开查询无需登录凭据；读取或操作账号需开启对应配置并由宿主校验真实发送者为主人 | [lenbot-plugin-bilibili](https://github.com/lendevs/lenbot-plugin-bilibili) |
| `counter` | `/计数`、`计数加一`、`/计数清零`，以及查询与后台制卡两项工具 | 基础计数按群使用独立键值存储；制卡说明调用模型生成 | [lenbot-plugin-template](https://github.com/lendevs/lenbot-plugin-template) |

仓库内另附两份本地示例：

- [examples/plugins/notebook](../examples/plugins/notebook/README.md)：记忆插件示例，演示 `@recall`、`@memory_tool` 和 `report_memory_progress`。
- [examples/plugin-tools](../examples/plugin-tools/README.md)：固定上下文下的插件工具选择与参数回放用例。

插件的命令匹配和定时播报直接发送消息，处理结果作为背景记录进入后续会话上下文，不会额外唤醒聊天模型。
