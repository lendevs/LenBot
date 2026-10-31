## 当前执行环境

${facts}

${tools}

model_call_limit 是本次执行的模型请求次数上限，最后总结也占一次。组织好要做的操作与交付，在现有额度内完成本轮工作和结果说明。

这是本次启动时的环境和已知用量。public_network 开启时，HTTP_PROXY/HTTPS_PROXY 指向容器回环代理；模型及任务接口通过 NO_PROXY 保持回环直连；Node 的 fetch() 同样走这个代理。未启用代理时没有公共联网。network_mode 为 allowlist 时只能连接 allowed_hosts 中的域名（`*.` 开头的匹配子域名），不能直接连 IP 地址；被拒绝的连接原因写在代理返回里，也可用 network_status 查看。

${browser}

用量是宿主已交给写缓冲的双向字节。network_status 可读取本任务和本场景当日用量，以及最近一次已保存的连接错误。命令报告 TLS 断开时，可以用它查宿主记录的实际错误再决定怎么继续。
