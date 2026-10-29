# 开发者文档

本目录面向修改宿主源码或深入了解内部协议的开发者。部署与日常运营见[文档站](https://lendevs.github.io/LenBot/)，角色包与插件编写入门见文档站开发栏目，部署包内附说明见 [deploy/](../deploy/README.md)，代码、测试与数据格式约定见 [CONTRIBUTING](../CONTRIBUTING.md)。

| 文档 | 内容 |
|---|---|
| [架构](architecture.md) | 模块职责、数据流向、数据库并发与面板实时协议 |
| [持续关注与局部收尾](attention.md) | 消息合批、回复效果系数、跨回合关注意图与局部收尾 |
| [上下文与模型输入](context.md) | 请求组装、预算估算、压缩回想与续接协议 |
| [角色包装配](personas.md) | 角色目录校验、原子读写、提示词拼装与运行期切换 |
| [群聊表达](expression-materials.md) | 框架与角色口吻分工、提示词职责与防复读机制 |
| [面板前端](panel.md) | 设计规范、组件、数据层、实时事件与双语约定 |
| [插件接口 v1](plugins-v1.md)（[English](plugins-v1.en.md)） | 插件清单、入口装饰器、上下文、测试与发布 |
| [独立插件与示例](plugin-examples.md) | 官方业务插件、教学模板与本仓库插件示例 |
| [静态插件目录](plugin-catalog.md) | 插件发现目录的索引格式与同步脚本 |
| [模型协议与用途绑定](model-protocols.md) | 模型协议、用途绑定与网页搜索读取服务 |

## 写插件

插件接口代次为 `interface = 1`，公开入口从 `len_bot.plugin` 导入。新建插件可在 GitHub 上从[插件模板](https://github.com/lendevs/lenbot-plugin-template)生成仓库。

插件与宿主共享 Python 环境（默认同进程，可选独立工作子进程），用于实现精确命令、规则接管、后台监测和专用工具。耗时或需要文件系统隔离的工作由插件通过 `ctx.delegate` 交给容器后台任务执行。

编写面向聊天模型的工具时，按完整操作组织接口：

- 同类列表、搜索和详情合并为一个工具，用带判别字段的严格请求模型区分 `action`。
- 数据查询与消息发送分开，与账号写入操作也分开。

工具说明与参数如何进入模型上下文，见[工具说明如何交给聊天模型](plugins-v1.md#工具说明如何交给聊天模型)。可用[插件工具回放](../examples/plugin-tools/README.md)验证模型选工具和填参数的结果。
