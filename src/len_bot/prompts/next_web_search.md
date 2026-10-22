来源：本次网页搜索，服务商见 provider，搜索时间见 fetched_at。每条结果有标题、链接、摘要和可用的发布日期。top_page 是第一条能读取的结果的正文开头；next_offset 非空时，用 web_read 的同一 document 和这个字符位置续读。

$result

要看其他结果的正文时用 web_read 读取原始链接。
