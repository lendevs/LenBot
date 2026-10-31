"""The chat-data tools a task worker may call on the host, and the route each one uses."""

# Tool name -> route on the worker's model bridge. The worker's extension registers one tool per
# entry the host opened for the scene; ``worker_bridge.TASK_ROUTES`` lists the same routes.
DATA_ROUTES = {
    "recall_chat": "/task/recall-chat",
    "memory": "/task/memory",
    "transcribe": "/task/transcribe",
    "knowledge": "/task/knowledge",
    "web_read": "/task/web-read",
    "web_search": "/task/web-search",
}
