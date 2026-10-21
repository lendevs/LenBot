<send_file>
send_file 只接受本群任务返回的 task_id 和 file_id，发送的是已登记的副本，不能自己拼路径。
- uploaded 表示平台接口返回了文件回执；failed 是这次明确失败；unconfirmed 是结果未知。
- 重复调用会重复上传。结果未知时先看任务状态里最近的上传回执。
</send_file>
