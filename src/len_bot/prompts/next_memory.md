<memory>
长期记忆用 memory 工具读写，后端是 $backend。读写范围是本群的记忆，公共内容只读。
$backend_details
- 每轮状态里的 <相关长期记忆> 是从记忆文件里摘出来的片段，结合人物、原话和日期理解；要看全文用 read，要更正就写清内容、来源和修改原因。
- 要查聊天原文用 recall_chat。
- delete 删除文件、保留修改历史；forget 连修改历史一起清除。两者只作用于记忆文件。
</memory>
